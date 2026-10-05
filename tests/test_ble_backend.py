# VIN-like values in this file are synthetic fixtures, not real vehicles.
import asyncio
from types import SimpleNamespace
import pytest
import bleak
from phone_key_lab.backends import BleVehicle
from phone_key_lab.framing import SERVICE, TO_VEHICLE, FROM_VEHICLE, frame, chunks


class FakeServices:
    def __init__(self, write_without_response=True):
        self.tx = SimpleNamespace(properties=["write", "write-without-response"] if write_without_response else ["write"], max_write_without_response_size=37)
        self.rx = SimpleNamespace(properties=["indicate"])
    def get_service(self, uuid):
        return SimpleNamespace(uuid=SERVICE)
    def get_characteristic(self, uuid):
        return self.tx if uuid == TO_VEHICLE else self.rx


@pytest.fixture
def fake_ble(monkeypatch):
    devices = []
    class Client:
        def __init__(self, device, disconnected_callback):
            self.services = FakeServices()
            self.mtu_size = 80
            self.writes = []
            self.disconnected_callback = disconnected_callback
            self.closed = False
            devices.append(self)
        async def connect(self):
            pass
        async def disconnect(self):
            self.closed = True
        async def start_notify(self, characteristic, callback, **kwargs):
            assert characteristic == self.services.rx
            assert kwargs["force_indicate"] is True
            self.callback = callback
        async def write_gatt_char(self, characteristic, data, response):
            assert characteristic == self.services.tx
            self.writes.append((bytes(data), response))
    async def find(predicate, timeout):
        device = SimpleNamespace(address="test")
        assert predicate(device, SimpleNamespace(local_name="S0123456789abcdefC")) is False
        return device
    monkeypatch.setattr(bleak, "BleakClient", Client)
    monkeypatch.setattr(bleak.BleakScanner, "find_device_by_filter", find)
    return devices


async def test_adapter_rechunks_and_reassembles_indications(fake_ble):
    vehicle = BleVehicle("TESTVIN0000000001")
    async with vehicle:
        client = fake_ble[0]
        payload = bytes(range(256)) * 4
        await vehicle.write(payload)
        assert b"".join(data for data, response in client.writes) == frame(payload)
        assert all(len(data) <= 37 and response is False for data, response in client.writes)
        for chunk in chunks(frame(payload), 19):
            client.callback(client.services.rx, chunk)
        assert await vehicle.read() == payload
    assert client.closed


async def test_adapter_write_with_response_fallback(fake_ble):
    vehicle = BleVehicle("TESTVIN0000000001")
    async with vehicle:
        client = fake_ble[0]
        client.services.tx.properties = ["write"]
        vehicle.response = True
        await vehicle.write(b"a" * 200)
        assert all(len(data) <= 77 and response for data, response in client.writes)


async def test_adapter_disconnect_unblocks_pending_read(fake_ble):
    vehicle = BleVehicle("TESTVIN0000000001")
    async with vehicle:
        pending = asyncio.create_task(vehicle.read())
        await asyncio.sleep(0)
        fake_ble[0].disconnected_callback(fake_ble[0])
        with pytest.raises(ConnectionError, match="vehicle disconnected"):
            await asyncio.wait_for(pending, 1)


async def test_adapter_rejects_bad_notification(fake_ble):
    async with BleVehicle("TESTVIN0000000001") as vehicle:
        fake_ble[0].callback(None, b"\xff\xff")
        with pytest.raises(ValueError, match="length"):
            await vehicle.read()


async def test_adapter_stale_notification_unblocks_read(fake_ble):
    async with BleVehicle("TESTVIN0000000001") as vehicle:
        vehicle.decoder.timeout = .01
        fake_ble[0].callback(None, frame(b"partial")[:3])
        with pytest.raises(ConnectionError, match="timed out"):
            await asyncio.wait_for(vehicle.read(), 1)
