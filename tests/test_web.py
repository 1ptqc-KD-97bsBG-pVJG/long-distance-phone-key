import asyncio
from contextlib import asynccontextmanager
import pytest
from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer
from phone_key_lab.web_server import BrowserSession, BrowserVehicle, make_app, validate_public_url
from phone_key_lab.server import RelayServer
from phone_key_lab.wire import RelayClient


@asynccontextmanager
async def setup_session(lifetime=60):
    session = BrowserSession('PKLab', simulation=True, lifetime=lifetime)
    async with TestServer(make_app(session)) as server:
        origin = str(server.make_url('')).rstrip('/')
        session.origins = {origin}
        async with ClientSession() as client:
            yield session, server, client, origin
        await session.end()


async def join(client, server, origin, token):
    ws = await client.ws_connect(server.make_url('/relay'), headers={'Origin': origin})
    await ws.send_json({'type': 'join', 'token': token})
    return ws


async def test_browser_bridge_real_sockets_order_sizes_and_disconnect():
    async with setup_session() as (s, server, http, origin):
        ws = await join(http, server, origin, s.invitation)
        assert (await ws.receive_json())['type'] == 'waiting'
        response = await http.post(server.make_url('/api/approve'), headers={'Authorization': 'Bearer ' + s.admin, 'Origin': origin})
        assert response.status == 200
        assert (await ws.receive_json())['simulation'] is True
        await ws.send_json({'type': 'ready'})
        relay = RelayServer(s.relay_token, lambda: BrowserVehicle(s))
        port = await relay.start()
        phone = RelayClient('127.0.0.1', port, s.relay_token)
        try:
            assert (await phone.connect())['backend'] == 'simulation'
            for size in (1, 19, 20, 21, 255, 512, 1024):
                value = bytes(i % 256 for i in range(size))
                await phone.write(value)
                packet = await ws.receive_json()
                assert packet == {'type': 'write', 'data': value.hex()}
                await ws.send_json({'type': 'notify', 'data': packet['data']})
                assert await phone.read() == value
            await ws.close()
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(phone.read(), 2)
            assert s.ended
        finally:
            await phone.close()
            await relay.close()


async def test_wrong_token_and_origin_do_not_consume_invitation():
    async with setup_session() as (s, server, http, origin):
        response = await http.get(server.make_url('/relay'), headers={'Origin': 'https://evil.example'})
        assert response.status == 403
        ws = await join(http, server, origin, 'wrong')
        assert (await ws.receive()).type == WSMsgType.CLOSE
        assert not s.claimed
        valid = await join(http, server, origin, s.invitation)
        assert (await valid.receive_json())['type'] == 'waiting'
        await valid.close()


async def test_approval_requires_private_key_and_matching_origin():
    async with setup_session() as (s, server, http, origin):
        for headers in ({}, {'Authorization': 'Bearer ' + s.admin, 'Origin': 'https://evil.example'}):
            response = await http.post(server.make_url('/api/approve'), headers=headers)
            assert response.status == 403
        response = await http.get(server.make_url('/api/status'))
        assert response.status == 403
        assert not s.approved.is_set()
        page = await http.get(server.make_url('/'))
        assert page.headers['Referrer-Policy'] == 'no-referrer'
        assert s.invitation not in await page.text()


async def test_invitation_single_use_and_close_while_waiting():
    async with setup_session() as (s, server, http, origin):
        first = await join(http, server, origin, s.invitation)
        await first.receive_json()
        second = await join(http, server, origin, s.invitation)
        assert (await second.receive()).type == WSMsgType.CLOSE
        assert not s.ended
        await first.close()
        await asyncio.wait_for(s.ready.wait(), 2)
        assert s.ended
        third = await join(http, server, origin, s.invitation)
        assert (await third.receive()).type == WSMsgType.CLOSE


async def test_expired_invitation_rejected():
    async with setup_session(lifetime=-1) as (s, server, http, origin):
        ws = await join(http, server, origin, s.invitation)
        assert (await ws.receive()).type == WSMsgType.CLOSE
        assert not s.claimed


@pytest.mark.parametrize('packet', [{'type': 'ready'}, {'type': 'notify', 'data': '00'}])
async def test_browser_cannot_send_before_approval(packet):
    async with setup_session() as (s, server, http, origin):
        ws = await join(http, server, origin, s.invitation)
        await ws.receive_json()
        await ws.send_json(packet)
        assert (await ws.receive()).type == WSMsgType.CLOSE
        await s.ready.wait()
        assert s.ended


async def test_host_stop_wakes_waiting_backend_and_closes_browser():
    async with setup_session() as (s, server, http, origin):
        ws = await join(http, server, origin, s.invitation)
        await ws.receive_json()
        pending = asyncio.create_task(BrowserVehicle(s).__aenter__())
        await s.end()
        with pytest.raises(ConnectionError, match='ended'):
            await pending
        assert (await ws.receive()).type == WSMsgType.CLOSE


def test_remote_url_requires_https_and_no_credentials():
    for url in ('http://remote.example', 'https://user:pass@remote.example', 'https://remote.example/path', 'https://remote.example/#secret'):
        with pytest.raises(ValueError):
            validate_public_url(url)
    assert validate_public_url('https://near.tailnet.ts.net/') == 'https://near.tailnet.ts.net'
    assert validate_public_url('http://localhost:8787') == 'http://localhost:8787'


async def test_malformed_payload_after_approval_terminates_session():
    async with setup_session() as (s, server, http, origin):
        ws = await join(http, server, origin, s.invitation)
        await ws.receive_json()
        s.approved.set()
        await ws.receive_json()
        await ws.send_json({'type': 'ready'})
        await s.ready.wait()
        await ws.send_json({'type': 'notify', 'data': 'not-hex'})
        assert (await ws.receive()).type == WSMsgType.CLOSE
        assert s.ended


async def test_host_end_endpoint_releases_active_connection():
    async with setup_session() as (s, server, http, origin):
        ws = await join(http, server, origin, s.invitation)
        await ws.receive_json()
        response = await http.post(server.make_url('/api/end'), headers={'Authorization': 'Bearer ' + s.admin, 'Origin': origin})
        assert response.status == 200
        assert (await ws.receive()).type == WSMsgType.CLOSE
        assert s.ended


async def test_diagnostic_metadata_and_physical_backend_are_preserved():
    s = BrowserSession('SFixture', diagnostic=True)
    async with TestServer(make_app(s)) as server, ClientSession() as http:
        origin = str(server.make_url('')).rstrip('/')
        s.origins = {origin}
        assert (await http.get(server.make_url('/ui.js'))).status == 200
        assert (await http.get(server.make_url('/private.token'))).status == 404
        ws = await join(http, server, origin, s.invitation)
        await ws.receive_json()
        s.approved.set()
        packet = await ws.receive_json()
        assert packet['diagnostic'] is True and packet['simulation'] is False
        assert BrowserVehicle(s).info()['backend'] == 'ble'
        await ws.close()
        await s.end()
