import asyncio
import hmac
import logging
from .wire import receive, send, payload, WIRE_LIMIT

log = logging.getLogger(__name__)


class RelayServer:
    def __init__(self, token, backend_factory):
        if len(token) < 32:
            raise ValueError("use a random token of at least 32 characters")
        self.token, self.backend_factory = token, backend_factory
        self.busy = False
        self.sessions = set()

    async def start(self, port=0, host="127.0.0.1"):
        if host not in ("127.0.0.1", "::1"):
            raise ValueError("bind to loopback; use SSH forwarding between laptops")
        self.server = await asyncio.start_server(self.handle, host, port, limit=WIRE_LIMIT)
        return self.server.sockets[0].getsockname()[1]

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.sessions):
            task.cancel()
        await asyncio.gather(*self.sessions, return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.sessions.add(task)
        acquired = False
        try:
            hello = await asyncio.wait_for(receive(reader), 5)
            token = hello.get("token")
            if hello["type"] != "hello" or not isinstance(token, str) or not hmac.compare_digest(token, self.token):
                raise ValueError("authentication failed")
            if self.busy:
                raise ConnectionError("another phone session is active")
            self.busy = acquired = True
            async with self.backend_factory() as backend:
                await send(writer, {"type": "ready", **backend.info()})
                log.info("session ready (%s)", backend.info()["backend"])

                async def writes():
                    while True:
                        packet = await receive(reader)
                        if packet["type"] != "write":
                            raise ValueError("expected write packet")
                        data = payload(packet)
                        log.info("phone → vehicle: %d bytes", len(data))
                        await asyncio.wait_for(backend.write(data), 15)

                async def notifications():
                    while True:
                        data = await backend.read()
                        log.info("vehicle → phone: %d bytes", len(data))
                        await send(writer, {"type": "notify", "data": data.hex()})

                children = [asyncio.create_task(writes()), asyncio.create_task(notifications())]
                try:
                    done, _ = await asyncio.wait(children, return_when=asyncio.FIRST_EXCEPTION)
                    for finished in done:
                        finished.result()
                finally:
                    for child in children:
                        child.cancel()
                    await asyncio.gather(*children, return_exceptions=True)
        except (Exception, asyncio.CancelledError) as error:
            log.info("session ended: %s", error)
            if not isinstance(error, asyncio.CancelledError):
                try:
                    await asyncio.wait_for(send(writer, {"type": "error", "message": str(error)}), 1)
                except Exception:
                    pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            finally:
                if acquired:
                    self.busy = False
                self.sessions.discard(task)
