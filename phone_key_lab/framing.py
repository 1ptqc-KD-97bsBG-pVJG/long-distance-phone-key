import hashlib
import time

SERVICE = "00000211-b2d1-43f0-9b88-960cebf8b91e"
TO_VEHICLE = "00000212-b2d1-43f0-9b88-960cebf8b91e"
FROM_VEHICLE = "00000213-b2d1-43f0-9b88-960cebf8b91e"
MAX_MESSAGE = 1024


def vehicle_name(vin: str) -> str:
    vin = vin.strip().upper()
    if len(vin) != 17 or not vin.isascii() or not vin.isalnum():
        raise ValueError("VIN must contain 17 ASCII letters/digits")
    return "S" + hashlib.sha1(vin.encode()).hexdigest()[:16] + "C"


def frame(payload: bytes) -> bytes:
    if not 1 <= len(payload) <= MAX_MESSAGE:
        raise ValueError("message must contain 1..1024 bytes")
    return len(payload).to_bytes(2, "big") + payload


def chunks(data: bytes, size: int):
    if size < 1:
        raise ValueError("chunk size must be positive")
    for i in range(0, len(data), size):
        yield data[i:i + size]


class Decoder:
    """Fail the session on malformed/stale fragments rather than guessing recovery."""

    def __init__(self, timeout=1.0):
        self.buffer = bytearray()
        self.last = None
        self.timeout = timeout

    def feed(self, data: bytes, now=None) -> list[bytes]:
        now = time.monotonic() if now is None else now
        if self.buffer and self.last is not None and now - self.last > self.timeout:
            self.reset()
            raise ValueError("incomplete BLE message timed out")
        self.last = now
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= 2:
            length = int.from_bytes(self.buffer[:2], "big")
            if not 1 <= length <= MAX_MESSAGE:
                self.reset()
                raise ValueError("invalid BLE message length")
            if len(self.buffer) < length + 2:
                break
            result.append(bytes(self.buffer[2:length + 2]))
            del self.buffer[:length + 2]
        return result

    def reset(self):
        self.buffer.clear()
        self.last = None
