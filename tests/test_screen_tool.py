import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from server import main
from server.screen_registry import providers
from test_screen_request import fixture, pending, picture


@pytest.mark.asyncio
async def test_explicit_fresh_without_systemone_or_auto_and_input_invalidation():
    r, c, client, events, stream = await fixture(systemone_enabled=False, screen_request_enabled=False)
    task = asyncio.create_task(r.snapshot())
    query = await pending(r, events)
    assert query['purpose'] == 'tool'
    assert await r.snapshot() == {'available': False, 'reason': 'busy'}
    r.invalidate()
    assert not await r.answer(picture(str(uuid.uuid4()), query['request_id']))
    assert not await r.answer(picture(stream, str(uuid.uuid4())))
    assert not await r.answer(picture(stream, query['request_id'], 0))
    assert await r.answer(picture(stream, query['request_id']))
    result = await task
    assert result['available'] and result['stream_id'] == stream
    assert result['image']['width'] == 40 and result['captured_at'].endswith('+00:00')
    assert not await c.offer(picture(stream, query['request_id']))
    client.screen_request.assert_not_called()
    await r.close(); await c.close()


@pytest.mark.asyncio
async def test_explicit_and_automatic_are_independently_correlated():
    from test_screen_request import frame
    r, c, _, events, stream = await fixture()
    automatic = asyncio.create_task(r.prepare(frame()))
    first = await pending(r, events)
    tool = asyncio.create_task(r.snapshot())
    while len([e for e in events if e['type'] == 'voice.screen.request']) < 2:
        await asyncio.sleep(0)
    second = [e for e in events if e['type'] == 'voice.screen.request'][1]
    assert await r.answer(picture(stream, first['request_id'], 1))
    assert await automatic
    assert not await r.answer(picture(stream, second['request_id'], 1))
    assert await r.answer(picture(stream, second['request_id'], 2))
    assert (await tool)['available']
    await r.close(); await c.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('action,reason', [('revoke','sharing_changed'), ('close','no_connection'), ('timeout','timeout')])
async def test_pending_tool_is_retired(action, reason):
    r, c, _, events, stream = await fixture(screen_request_timeout_ms=20)
    task = asyncio.create_task(r.snapshot()); query = await pending(r, events)
    if action == 'revoke':
        await c.activate({'active': False, 'stream_id': stream}); r.sharing_changed()
    elif action == 'close':
        await r.close()
    assert await task == {'available': False, 'reason': reason}
    assert not await r.answer(picture(stream, query['request_id']))
    await r.close(); await c.close()


@pytest.mark.asyncio
async def test_no_sharing_and_disabled():
    r, c, _, _, _ = await fixture(shared=False)
    assert await r.snapshot() == {'available': False, 'reason': 'not_shared'}
    c.enabled = False
    assert await r.snapshot() == {'available': False, 'reason': 'disabled'}
    await r.close(); await c.close()


def test_endpoint_plugin_auth_and_exact_session(monkeypatch):
    monkeypatch.setattr(main.dsh, 'enabled', lambda: True)
    monkeypatch.setenv('DAFEIYU_PLUGIN_TOKEN', 'fixture-token')
    provider = type('Provider', (), {'snapshot': AsyncMock(return_value={'available': False, 'reason': 'not_shared'})})()
    providers['root-session'] = provider
    try:
        with TestClient(main.app) as client:
            assert client.post('/api/voice/screen/snapshot', json={'session_id': 'root-session'}).status_code == 401
            headers = {'X-Dafeiyu-Plugin-Token': 'fixture-token'}
            assert client.post('/api/voice/screen/snapshot', headers=headers, json={'session_id': 'other'}).json()['reason'] == 'no_connection'
            assert client.post('/api/voice/screen/snapshot', headers=headers, json={'session_id': 'root-session'}).json()['reason'] == 'not_shared'
            assert client.post('/api/voice/screen/snapshot', headers=headers, json={'session_id': 3}).status_code == 422
        provider.snapshot.assert_awaited_once()
    finally:
        providers.pop('root-session', None)


def test_endpoint_unsupported(monkeypatch):
    monkeypatch.setattr(main.dsh, 'enabled', lambda: False)
    with TestClient(main.app) as client:
        assert client.post('/api/voice/screen/snapshot', json={'session_id': 'root'}).json() == {'available': False, 'reason': 'unsupported_mode'}

@pytest.mark.asyncio
async def test_revoke_after_frame_before_waiter_resumes():
    r, c, _, events, stream = await fixture()
    task = asyncio.create_task(r.snapshot()); query = await pending(r, events)
    assert await r.answer(picture(stream, query['request_id']))
    await c.activate({'active': False, 'stream_id': stream}); r.sharing_changed()
    assert await task == {'available': False, 'reason': 'sharing_changed'}
    await r.close(); await c.close()


@pytest.mark.asyncio
async def test_session_retirement_unregisters_and_cancels(monkeypatch):
    r, c, _, events, _ = await fixture()
    providers['retired-root'] = r
    monkeypatch.setattr(main.dsh, 'enabled', lambda: True)
    bridge = type('Bridge', (), {'delete_session': AsyncMock(return_value={'deleted': True})})()
    monkeypatch.setattr(main.dsh, 'BridgeClient', lambda: bridge)
    task = asyncio.create_task(r.snapshot()); await pending(r, events)
    try:
        assert await main.delete_session('retired-root') == {'deleted': True}
        assert 'retired-root' not in providers
        assert await task == {'available': False, 'reason': 'no_connection'}
    finally:
        providers.pop('retired-root', None)
        await r.close(); await c.close()
