import asyncio
import json
from .framing import MAX_MESSAGE

WIRE_LIMIT = 4096


async def receive(reader):
    line = await reader.readline()
    if not line:
        raise ConnectionError("relay peer disconnected")
    if len(line) > WIRE_LIMIT:
        raise ValueError("relay packet too large")
    packet = json.loads(line)
    if not isinstance(packet, dict) or not isinstance(packet.get("type"), str):
        raise ValueError("invalid relay packet")
    return packet


async def send(writer, packet):
    data = json.dumps(packet, separators=(",", ":")).encode() + b"\n"
    if len(data) > WIRE_LIMIT:
        raise ValueError("relay packet too large")
    writer.write(data)
    await writer.drain()


def payload(packet):
    value = packet.get("data")
    if not isinstance(value, str) or len(value) > MAX_MESSAGE * 2:
        raise ValueError("invalid payload")
    result = bytes.fromhex(value)
    if not 1 <= len(result) <= MAX_MESSAGE:
        raise ValueError("invalid payload length")
    return result


class RelayClient:
    def __init__(self, host, port, token):
        self.host, self.port, self.token = host, port, token
        self.lock = asyncio.Lock()

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port, limit=WIRE_LIMIT)
        try:
            await send(self.writer, {"type": "hello", "token": self.token})
            ready = await asyncio.wait_for(receive(self.reader), 45)
            if ready["type"] != "ready":
                raise ConnectionError(ready.get("message", "relay rejected connection"))
            return ready
        except BaseException:
            await self.close()
            raise

    async def write(self, data):
        async with self.lock:
            await send(self.writer, {"type": "write", "data": data.hex()})

    async def read(self):
        packet = await receive(self.reader)
        if packet["type"] != "notify":
            raise ConnectionError(packet.get("message", "unexpected relay response"))
        return payload(packet)

    async def close(self):
        if hasattr(self, "writer"):
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except ConnectionError:
                pass
