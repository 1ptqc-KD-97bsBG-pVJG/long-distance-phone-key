"""Phone-facing GATT adapter on Netsim; same network client as the hardware path."""
import argparse
import asyncio
import logging
from pathlib import Path
from bumble.core import AdvertisingData, UUID
from bumble.device import Device, DeviceConfiguration
from bumble.gatt import Characteristic, CharacteristicValue, Service
from bumble.hci import Address
from bumble.transport import open_transport
from .framing import SERVICE, TO_VEHICLE, FROM_VEHICLE, Decoder, frame, chunks
from .wire import RelayClient

log = logging.getLogger(__name__)


async def run(args):
    client = RelayClient("127.0.0.1", args.port, Path(args.token_file).read_text().strip())
    print("Backend:", await client.connect(), flush=True)
    try:
        async with await open_transport(args.transport) as hci:
            service_id = UUID(SERVICE)
            advertising = bytes(AdvertisingData([
                (AdvertisingData.FLAGS, b"\x06"),
                (AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS, service_id.to_bytes()),
            ]))
            scan_response = bytes(AdvertisingData([
                (AdvertisingData.COMPLETE_LOCAL_NAME, args.name.encode()),
            ]))
            config = DeviceConfiguration(name=args.name, address=Address("F0:F1:F2:F3:F4:F5"),
                                         advertising_data=advertising, scan_response_data=scan_response,
                                         advertising_interval_min=100, advertising_interval_max=100)
            device = Device.from_config_with_hci(config, hci.source, hci.sink)
            decoder = Decoder()
            writes = asyncio.Queue(maxsize=128)
            stopped = asyncio.Event()
            connection = None
            failure = None

            def fail(error):
                nonlocal failure
                failure = error
                stopped.set()

            def incoming(conn, data):
                try:
                    for message in decoder.feed(bytes(data)):
                        writes.put_nowait(message)
                except (ValueError, asyncio.QueueFull) as error:
                    fail(error)

            rx = Characteristic(FROM_VEHICLE, Characteristic.Properties.NOTIFY | Characteristic.Properties.INDICATE,
                                Characteristic.READABLE, b"")
            tx = Characteristic(TO_VEHICLE, Characteristic.Properties.WRITE | Characteristic.Properties.WRITE_WITHOUT_RESPONSE,
                                Characteristic.WRITEABLE, CharacteristicValue(write=incoming))
            device.add_services([Service(SERVICE, [tx, rx])])

            def connected(conn):
                nonlocal connection
                if connection is not None:
                    fail(ConnectionError("only one phone may connect"))
                    return
                connection = conn
                print("Android connected to virtual proxy", flush=True)
                def disconnected(reason):
                    nonlocal connection
                    connection = None
                    stopped.set()
                conn.on("disconnection", disconnected)

            device.on("connection", connected)

            async def write_loop():
                try:
                    while True:
                        await client.write(await writes.get())
                except Exception as error:
                    fail(error)

            async def read_loop():
                try:
                    while True:
                        message = await client.read()
                        if connection is None:
                            raise ConnectionError("response without a phone session")
                        for chunk in chunks(frame(message), min(20, connection.att_mtu - 3)):
                            # Deliver using the mode selected in the phone's CCCD.
                            await device.notify_subscribers(rx, chunk)
                            await device.indicate_subscribers(rx, chunk)
                except Exception as error:
                    fail(error)

            await device.power_on()
            await device.start_advertising(auto_restart=False)
            print(f"Virtual proxy advertising {args.name}; ready for Android", flush=True)
            workers = [asyncio.create_task(write_loop()), asyncio.create_task(read_loop())]
            try:
                await stopped.wait()
                if failure:
                    raise failure
            finally:
                for worker in workers:
                    worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                if connection:
                    await connection.disconnect()
                await device.power_off()
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-file", default="lab.token")
    parser.add_argument("--name", default="PKLab")
    parser.add_argument("--transport", default="android-netsim:name=phone-key-lab-proxy")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
