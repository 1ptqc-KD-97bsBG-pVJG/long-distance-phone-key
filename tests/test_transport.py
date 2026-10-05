# VIN-like values in this file are synthetic fixtures, not real vehicles.
import asyncio
import random
import pytest
from phone_key_lab.framing import Decoder, frame, chunks, vehicle_name
from phone_key_lab.backends import SimulatedVehicle
from phone_key_lab.server import RelayServer
from phone_key_lab.wire import RelayClient, receive, send

TOKEN = "a" * 64


def test_stream_random_boundaries_and_coalesced_frames():
    rng = random.Random(123)
    expected = [rng.randbytes(rng.randint(1, 1024)) for _ in range(200)]
    stream = b"".join(frame(value) for value in expected)
    decoder = Decoder()
    actual = []
    while stream:
        size = rng.randint(1, 600)
        actual.extend(decoder.feed(stream[:size]))
        stream = stream[size:]
    assert actual == expected
    assert not decoder.buffer


@pytest.mark.parametrize("bad", [b"\x00\x00", b"\x04\x01", b"\xff\xff"])
def test_invalid_frames_fail_and_clear(bad):
    decoder = Decoder()
    with pytest.raises(ValueError):
        decoder.feed(bad)
    assert not decoder.buffer


def test_stale_fragment_fails_without_splicing():
    decoder = Decoder()
    decoder.feed(frame(b"old")[:3], now=0)
    with pytest.raises(ValueError, match="timed out"):
        decoder.feed(frame(b"new"), now=2)
    assert decoder.feed(frame(b"fresh"), now=3) == [b"fresh"]


def test_name_and_chunk_limits():
    assert vehicle_name("TESTVIN0000000001") == "S" + __import__("hashlib").sha1(b"TESTVIN0000000001").hexdigest()[:16] + "C"
    assert b"".join(chunks(frame(b"x" * 1024), 20)) == frame(b"x" * 1024)
    with pytest.raises(ValueError):
        frame(b"x" * 1025)
    with pytest.raises(ValueError):
        vehicle_name("wrong")


@pytest.mark.parametrize("delay,jitter", [(0, 0), (10, 20), (100, 50)])
async def test_socket_roundtrip_order_and_sizes(delay, jitter):
    server = RelayServer(TOKEN, lambda: SimulatedVehicle(delay, jitter))
    port = await server.start()
    client = RelayClient("127.0.0.1", port, TOKEN)
    try:
        assert (await client.connect())["backend"] == "simulation"
        values = [bytes([i]) * size for i, size in enumerate([1, 19, 20, 21, 255, 512, 1024])]
        for data in values:
            await client.write(data)
        assert [await asyncio.wait_for(client.read(), 3) for _ in values] == values
    finally:
        await client.close()
        await server.close()


async def test_auth_busy_and_fresh_session_after_disconnect():
    server = RelayServer(TOKEN, lambda: SimulatedVehicle(100, 0))
    port = await server.start()
    first = RelayClient("127.0.0.1", port, TOKEN)
    second = RelayClient("127.0.0.1", port, TOKEN)
    bad = RelayClient("127.0.0.1", port, "wrong")
    try:
        with pytest.raises(ConnectionError, match="authentication failed"):
            await bad.connect()
        await first.connect()
        with pytest.raises(ConnectionError, match="active"):
            await second.connect()
        await first.write(b"old pending response")
        await first.close()
        for _ in range(50):
            if not server.busy:
                break
            await asyncio.sleep(.01)
        assert not server.busy
        await second.connect()
        await second.write(b"fresh")
        assert await second.read() == b"fresh"
    finally:
        await first.close()
        await second.close()
        await server.close()


async def test_malformed_packet_ends_session():
    server = RelayServer(TOKEN, SimulatedVehicle)
    port = await server.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        await send(writer, {"type": "hello", "token": TOKEN})
        assert (await receive(reader))["type"] == "ready"
        await send(writer, {"type": "write", "data": "zz"})
        assert (await receive(reader))["type"] == "error"
        assert await reader.read() == b""
    finally:
        writer.close()
        await writer.wait_closed()
        await server.close()


class FailedVehicle(SimulatedVehicle):
    async def write(self, data):
        raise ConnectionError("vehicle disconnected")


async def test_vehicle_failure_propagates():
    server = RelayServer(TOKEN, FailedVehicle)
    port = await server.start()
    client = RelayClient("127.0.0.1", port, TOKEN)
    try:
        await client.connect()
        await client.write(b"test")
        with pytest.raises(ConnectionError, match="vehicle disconnected"):
            await client.read()
    finally:
        await client.close()
        await server.close()
