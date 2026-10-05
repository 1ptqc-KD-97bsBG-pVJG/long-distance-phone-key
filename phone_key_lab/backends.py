import asyncio
import random
import time
from .framing import Decoder, frame, chunks, SERVICE, TO_VEHICLE, FROM_VEHICLE, vehicle_name


class SimulatedVehicle:
    """Echo transport fixture, NOT an implementation of Tesla authentication."""

    def __init__(self, delay_ms=0, jitter_ms=0, seed=1):
        self.delay_ms, self.jitter_ms = delay_ms, jitter_ms
        self.random = random.Random(seed)
        self.inbox = asyncio.Queue(maxsize=128)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def info(self):
        return {"backend": "simulation", "authentication": "not simulated"}

    async def write(self, data):
        delay = self.delay_ms + self.random.uniform(0, self.jitter_ms)
        await asyncio.sleep(delay / 1000)
        # Exercise framing with independent chunk sizes in both directions.
        decoded = Decoder()
        messages = []
        for chunk in chunks(frame(data), 17):
            messages.extend(decoded.feed(chunk))
        response = Decoder()
        for chunk in chunks(frame(messages[0]), 31):
            for message in response.feed(chunk):
                await self.inbox.put(message)

    async def read(self):
        return await self.inbox.get()


class ObserveVehicle(SimulatedVehicle):
    """Accept transport messages without fabricating authenticated vehicle replies."""

    def info(self):
        return {"backend": "observe", "authentication": "not implemented; no replies"}

    async def write(self, data):
        pass


class BleVehicle:
    def __init__(self, vin, timeout=20):
        self.name = vehicle_name(vin)
        self.timeout = timeout
        self.inbox = asyncio.Queue(maxsize=128)
        self.decoder = Decoder()
        self.failure = asyncio.Event()
        self.error = None
        self.client = None

    def fail(self, error):
        self.error = error
        self.failure.set()

    async def __aenter__(self):
        from bleak import BleakClient, BleakScanner
        device = await BleakScanner.find_device_by_filter(
            lambda d, a: a.local_name == self.name, timeout=self.timeout)
        if device is None:
            raise ConnectionError("target vehicle not found; wake it and check Bluetooth range")
        self.client = BleakClient(device, disconnected_callback=lambda _: self.fail(ConnectionError("vehicle disconnected")))
        try:
            await self.client.connect()
            self.tx = self.client.services.get_characteristic(TO_VEHICLE)
            self.rx = self.client.services.get_characteristic(FROM_VEHICLE)
            service = self.client.services.get_service(SERVICE)
            if not service or not self.tx or not self.rx:
                raise ConnectionError("vehicle does not expose the expected BLE interface")
            self.response = "write-without-response" not in self.tx.properties
            if self.response and "write" not in self.tx.properties:
                raise ConnectionError("vehicle transmit characteristic is not writable")
            await self.client.start_notify(self.rx, self.notification,
                                           force_indicate="indicate" in self.rx.properties)
            return self
        except BaseException:
            await self.client.disconnect()
            raise

    def info(self):
        return {"backend": "ble", "service": SERVICE, "tx_properties": self.tx.properties,
                "rx_properties": self.rx.properties, "mtu": self.client.mtu_size,
                "write_size": self.write_size}

    @property
    def write_size(self):
        return min(512, self.client.mtu_size - 3) if self.response else self.tx.max_write_without_response_size

    def notification(self, characteristic, data):
        try:
            for message in self.decoder.feed(bytes(data)):
                self.inbox.put_nowait(message)
        except (ValueError, asyncio.QueueFull) as error:
            self.fail(error)

    async def write(self, data):
        if self.failure.is_set():
            raise self.error
        for chunk in chunks(frame(data), self.write_size):
            await self.client.write_gatt_char(self.tx, chunk, response=self.response)

    async def read(self):
        take = asyncio.create_task(self.inbox.get())
        failure = asyncio.create_task(self.failure.wait())
        try:
            while True:
                done, _ = await asyncio.wait([take, failure], timeout=.2,
                                            return_when=asyncio.FIRST_COMPLETED)
                if failure in done:
                    raise self.error
                if take in done:
                    return take.result()
                if self.decoder.buffer and self.decoder.last is not None and time.monotonic() - self.decoder.last > self.decoder.timeout:
                    raise ConnectionError("incomplete vehicle message timed out")
        finally:
            take.cancel()
            failure.cancel()
            await asyncio.gather(take, failure, return_exceptions=True)

    async def __aexit__(self, *args):
        if self.client:
            await self.client.disconnect()
