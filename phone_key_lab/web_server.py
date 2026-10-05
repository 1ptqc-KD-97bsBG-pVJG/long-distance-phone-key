"""One-shot, self-hosted browser vehicle endpoint; network exposure is external."""
import argparse
import asyncio
import hmac
import logging
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from aiohttp import web, WSMsgType
from .framing import vehicle_name
from .server import RelayServer
from .wire import payload, WIRE_LIMIT

ASSETS = Path(__file__).with_name('web')
log = logging.getLogger(__name__)


class BrowserVehicle:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        await self.session.ready.wait()
        if self.session.ended:
            raise ConnectionError('browser session ended')
        if self.session.attached:
            raise ConnectionError('browser session already used')
        self.session.attached = True
        return self

    async def __aexit__(self, *_):
        await self.session.end('Phone-facing connection ended. Start a new session to retry.')

    def info(self):
        return {'backend': 'simulation' if self.session.simulation else 'ble', 'endpoint': 'browser'}

    async def write(self, data):
        if self.session.ended or not self.session.socket or self.session.socket.closed:
            raise ConnectionError('browser disconnected')
        await asyncio.wait_for(self.session.socket.send_json({'type': 'write', 'data': data.hex()}), 10)

    async def read(self):
        data = await self.session.inbox.get()
        if data is None:
            raise ConnectionError('browser session ended')
        return data


class BrowserSession:
    def __init__(self, name, *, simulation=False, diagnostic=False, lifetime=600):
        self.name, self.simulation = name, simulation
        self.diagnostic = diagnostic
        self.invitation = secrets.token_urlsafe(32)
        self.admin = secrets.token_urlsafe(32)
        self.relay_token = secrets.token_hex(32)
        self.code = f'{secrets.randbelow(1000000):06d}'
        self.deadline = time.monotonic() + lifetime
        self.approved = asyncio.Event()
        self.ready = asyncio.Event()
        self.inbox = asyncio.Queue(maxsize=64)
        self.socket = None
        self.claimed = self.attached = self.ended = False
        self.state = 'Waiting for your partner'
        self.origins = set()

    def valid(self, supplied, expected):
        return isinstance(supplied, str) and hmac.compare_digest(supplied, expected)

    async def end(self, reason='Session ended by host', code=1000):
        if self.ended:
            return
        self.ended = True
        self.state = reason
        self.ready.set()
        self.approved.set()
        # Make room for the disconnect sentinel, never continue stale replies.
        while not self.inbox.empty():
            self.inbox.get_nowait()
        self.inbox.put_nowait(None)
        if self.socket is not None:
            await self.socket.close(code=code, message=b'Session ended')

    def status(self):
        return {'state': self.state, 'code': self.code if self.claimed else None,
                'ready': self.ready.is_set() and not self.ended, 'claimed': self.claimed,
                'approved': self.approved.is_set() and not self.ended, 'ended': self.ended,
                'seconds_left': max(0, int(self.deadline - time.monotonic())),
                'simulation': self.simulation, 'diagnostic': self.diagnostic, 'name': self.name}

    async def socket_handler(self, request):
        if request.headers.get('Origin') not in self.origins:
            raise web.HTTPForbidden(text='Unexpected origin')
        ws = web.WebSocketResponse(max_msg_size=WIRE_LIMIT, heartbeat=15)
        await ws.prepare(request)
        owned = False
        try:
            packet = await asyncio.wait_for(ws.receive_json(), 5)
            if not isinstance(packet, dict) or packet.get('type') != 'join' or not self.valid(packet.get('token'), self.invitation):
                raise ValueError('Invalid invitation')
            if self.ended or time.monotonic() >= self.deadline:
                raise ValueError('Session expired. Ask for a new invitation.')
            if self.claimed:
                raise ValueError('Invitation already used. Ask for a new invitation.')
            self.claimed = owned = True
            self.socket = ws
            self.state = 'Partner waiting for approval'
            await ws.send_json({'type': 'waiting', 'code': self.code})
            # Receive while awaiting approval so a closed tab releases the session.
            approved_sent = False
            while not self.ended:
                if self.approved.is_set() and not approved_sent:
                    approved_sent = True
                    self.state = 'Partner connecting to vehicle'
                    await ws.send_json({'type': 'approved', 'name': self.name, 'simulation': self.simulation, 'diagnostic': self.diagnostic})
                try:
                    message = await asyncio.wait_for(ws.receive(), .2)
                except asyncio.TimeoutError:
                    continue
                if message.type == WSMsgType.TEXT:
                    import json
                    packet = json.loads(message.data)
                    if not isinstance(packet, dict):
                        raise ValueError('Invalid packet')
                    if not approved_sent:
                        raise ValueError('Host approval required')
                    if packet.get('type') == 'ready' and not self.ready.is_set():
                        self.state = 'Vehicle connected — ready for phone setup'
                        self.ready.set()
                    elif packet.get('type') == 'notify' and self.ready.is_set():
                        self.inbox.put_nowait(payload(packet))
                    elif packet.get('type') == 'end':
                        break
                    else:
                        raise ValueError('Unexpected browser packet')
                elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        except (ValueError, TypeError, asyncio.TimeoutError, asyncio.QueueFull):
            if owned:
                await self.end('Invalid browser message. Start a new session to retry.', code=1008)
            else:
                await ws.close(code=1008, message=b'Invalid or unavailable session')
        finally:
            if owned:
                await self.end('Partner disconnected. Start a new session to retry.')
            elif not ws.closed:
                await ws.close()
        return ws


def make_app(session):
    @web.middleware
    async def headers(request, handler):
        response = await handler(request)
        if not isinstance(response, web.WebSocketResponse):
            response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                'X-Content-Type-Options': 'nosniff',
                'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})
        return response

    app = web.Application(middlewares=[headers], client_max_size=WIRE_LIMIT)

    async def asset(request):
        filename = request.match_info.get('file') or 'index.html'
        if filename not in {'index.html', 'host.html', 'app.js', 'host.js', 'transport.js', 'ui.js', 'style.css'}:
            raise web.HTTPNotFound()
        return web.FileResponse(ASSETS / filename)

    def authorize(request):
        if not session.valid(request.headers.get('Authorization'), 'Bearer ' + session.admin):
            raise web.HTTPForbidden()
        if request.method != 'GET' and request.headers.get('Origin') not in session.origins:
            raise web.HTTPForbidden()

    async def status(request):
        authorize(request)
        return web.json_response(session.status())

    async def approve(request):
        authorize(request)
        if session.ended or not session.claimed or time.monotonic() >= session.deadline:
            raise web.HTTPConflict(text='No pending session')
        session.approved.set()
        return web.json_response({'approved': True})

    async def end(request):
        authorize(request)
        await session.end()
        return web.json_response({'ended': True})

    app.router.add_get('/', asset)
    app.router.add_get('/{file:host.html|app.js|host.js|transport.js|ui.js|style.css}', asset)
    app.router.add_get('/relay', session.socket_handler)
    app.router.add_get('/api/status', status)
    app.router.add_post('/api/approve', approve)
    app.router.add_post('/api/end', end)
    return app


def validate_public_url(url):
    parsed = urlsplit(url)
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('--public-url must be an origin without path, credentials, query or fragment')
    if not parsed.hostname or parsed.scheme not in ('http', 'https'):
        raise ValueError('Expected an HTTPS URL or local HTTP URL')
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '[::1]', '::1'):
        raise ValueError('Remote browser access requires HTTPS; use Tailscale Serve')
    return url.rstrip('/')


async def run(args):
    public_url = validate_public_url(args.public_url or f'http://localhost:{args.web_port}')
    test_peripheral = getattr(args, 'test_peripheral', None)
    if not args.simulation and not args.vin and not test_peripheral:
        raise ValueError('--vin is required; use --simulation or --test-peripheral for apartment-only testing')
    if test_peripheral and (not test_peripheral.isascii() or not test_peripheral.isalnum()
                            or not test_peripheral.startswith('S') or len(test_peripheral) > 29):
        raise ValueError('--test-peripheral must be 1–29 ASCII letters/digits starting with S')
    name = test_peripheral or ('PKLab' if args.simulation else vehicle_name(args.vin))
    session = BrowserSession(name, simulation=args.simulation, diagnostic=bool(test_peripheral), lifetime=args.minutes * 60)
    session.origins = {public_url, f'http://localhost:{args.web_port}', f'http://127.0.0.1:{args.web_port}'}
    relay = RelayServer(session.relay_token, lambda: BrowserVehicle(session))
    relay_port = await relay.start(args.relay_port)
    token_file = Path(args.token_file).resolve()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite another active session's token.
    with token_file.open('x') as file:
        token_file.chmod(0o600)
        file.write(session.relay_token + '\n')
    runner = web.AppRunner(make_app(session), access_log=None)
    try:
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', args.web_port).start()
        print(f'Host controls (keep private): http://localhost:{args.web_port}/host.html#{session.admin}', flush=True)
        suffix = '&demo=1' if args.simulation else '&test=1' if test_peripheral else ''
        print(f'Partner invitation: {public_url}/#invite={session.invitation}{suffix}', flush=True)
        print(f'Mac proxy: --name {name} --mode {"name-only" if args.simulation or test_peripheral else "tesla-name"} --port {relay_port} --token-file {token_file} --auto-start', flush=True)
        print('Approve the matching code in host controls. Start the Mac proxy only after the browser is ready.', flush=True)
        if args.simulation:
            print('SIMULATION ONLY: no vehicle Bluetooth connection. Run the existing echo probe after approval.', flush=True)
        if test_peripheral:
            print('APARTMENT BLUETOOTH DIAGNOSTIC: select only your test peripheral, not a vehicle. No payload probe is enabled.', flush=True)
        try:
            await asyncio.sleep(args.minutes * 60)
        finally:
            await session.end('Session expired or server stopped')
    finally:
        await relay.close()
        await runner.cleanup()
        token_file.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Self-hosted browser endpoint for an authorized enrollment session')
    target = parser.add_mutually_exclusive_group()
    target.add_argument('--simulation', action='store_true')
    target.add_argument('--vin')
    target.add_argument('--test-peripheral', help='Apartment Bluetooth diagnostic: exact test-device name starting with S; never use with a vehicle')
    parser.add_argument('--public-url', help='HTTPS origin from Tailscale Serve; omit for localhost testing')
    parser.add_argument('--web-port', type=int, default=8787)
    parser.add_argument('--relay-port', type=int, default=18765)
    parser.add_argument('--token-file', default='artifacts/web-session.token')
    parser.add_argument('--minutes', type=float, default=10)
    args = parser.parse_args()
    if not 0 < args.minutes <= 30:
        parser.error('--minutes must be greater than zero and at most 30')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
