"""Offline intent + fresh snapshot lifecycle: no real desktop or paid API."""
import asyncio
import base64
import io
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from pipecat.frames.frames import LLMContextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from server.dsh import ProjectionStore
from server.dsh_llm import DSHLLMService
from server.screen_companion import ScreenCompanion
from server.screen_request import RequestedScreen
from server.storage import DEFAULTS, Store
from server.systemone import SCREEN_REQUEST_QUESTIONS, SystemOneClient
from server.systemone_providers import ARK_MODEL


def picture(stream, request, seq=1):
    out = io.BytesIO()
    Image.new('RGB', (40, 30), 'red').save(out, 'JPEG')
    return {'stream_id': stream, 'request_id': request, 'seq': seq, 'width': 40, 'height': 30,
        'mime_type': 'image/jpeg', 'data': base64.b64encode(out.getvalue()).decode()}


def frame(text='看看我当前屏幕上的图表'):
    return LLMContextFrame(LLMContext(messages=[{'role': 'user', 'content': text}]))


async def fixture(probability=.98, shared=True, **patch):
    client = SimpleNamespace(source='fixture', model='fixture', screen_request=AsyncMock(return_value=probability))
    settings = {**DEFAULTS, 'screen_companion_enabled': True, 'systemone_enabled': True, **patch}
    events = []
    async def notify(event): events.append(event)
    control = ScreenCompanion(client, settings, on_reply=AsyncMock(), busy=lambda: False, on_status=notify)
    stream = str(uuid.uuid4())
    if shared:
        await control.activate({'active': True, 'stream_id': stream})
    request = RequestedScreen(client, settings, control, lambda: [], notify)
    return request, control, client, events, stream


async def pending(request, events):
    async with asyncio.timeout(1):
        while not any(e['type'] == 'voice.screen.request' for e in events):
            await asyncio.sleep(0)
    return next(e for e in events if e['type'] == 'voice.screen.request')


@pytest.mark.asyncio
async def test_requested_fresh_snapshot_bypasses_proactive_budget_cooldown_and_retains_question():
    r, c, client, events, stream = await fixture()
    c.budget.judgments.extend([c.clock()] * 1000)
    c.budget.replies.extend([c.clock()] * 1000)
    c.budget.mark_reply(c.clock())
    f = frame()
    task = asyncio.create_task(r.prepare(f))
    query = await pending(r, events)
    assert r.busy
    assert not await r.answer(picture(stream, str(uuid.uuid4())))
    assert not await r.answer(picture(str(uuid.uuid4()), query['request_id']))
    invalid = picture(stream, query['request_id']);invalid['extra'] = True
    assert not await r.answer(invalid)
    assert not await r.answer(picture(stream, query['request_id'], 0))
    assert await r.answer(picture(stream, query['request_id']))
    assert not await r.answer(picture(stream, query['request_id'])), 'duplicate snapshot'
    assert await task
    assert f.context.messages[-1]['content'] == '看看我当前屏幕上的图表'
    assert f.metadata['dafeiyu_screen_state'] == 'attached'
    assert f.metadata['dafeiyu_requested_screen_valid']()
    assert f.metadata['dafeiyu_requested_screen']['width'] == 40
    assert c.seq == 1 and r.pending is None and not r.busy
    assert events[-1]['reason'] == 'request_attached'
    assert len(c.budget.judgments) == 1000, 'user request creates no autonomous judgment/reply'
    client.screen_request.assert_awaited_once()
    await r.close(); await c.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('probability,shared,reason',[(.1,True,'request_low_intent'),(.98,False,'request_not_shared'),(None,True,'request_intent_unavailable')])
async def test_no_snapshot_without_positive_intent_and_active_permission(probability, shared, reason):
    r, c, _, events, _ = await fixture(probability, shared)
    f = frame()
    assert await r.prepare(f)
    assert 'dafeiyu_requested_screen' not in f.metadata
    assert not any(e['type'] == 'voice.screen.request' for e in events)
    assert events[-1]['reason'] == reason
    await r.close(); await c.close()


@pytest.mark.asyncio
async def test_disabled_classifier_has_zero_calls_and_truthful_state():
    r, c, client, events, _ = await fixture(screen_request_enabled=False)
    f = frame()
    assert await r.prepare(f)
    assert f.metadata['dafeiyu_screen_state'] == 'request_disabled'
    client.screen_request.assert_not_called()
    await r.close(); await c.close()


@pytest.mark.asyncio
async def test_snapshot_timeout_is_bounded_then_next_turn_can_recover():
    r, c, _, events, stream = await fixture(screen_request_timeout_ms=10)
    f = frame()
    assert await r.prepare(f)
    assert f.metadata['dafeiyu_screen_state'] == 'snapshot_timeout'
    expired = next(e for e in events if e['type'] == 'voice.screen.request')
    assert not await r.answer(picture(stream, expired['request_id']))
    assert r.pending is None and not r.busy
    r.invalidate(); events.clear()
    fresh = frame(); task = asyncio.create_task(r.prepare(fresh)); query = await pending(r, events)
    assert await r.answer(picture(stream, query['request_id']))
    assert await task and fresh.metadata['dafeiyu_screen_state'] == 'attached'
    await r.close(); await c.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['new_input','screen_off','close'])
async def test_stop_or_new_input_cannot_revive_a_pending_snapshot(action):
    r, c, _, events, stream = await fixture()
    f = frame(); task = asyncio.create_task(r.prepare(f)); query = await pending(r, events)
    if action == 'new_input': r.invalidate()
    elif action == 'screen_off':
        await c.activate({'active': False, 'stream_id': stream}); r.sharing_changed()
    else: await r.close()
    result = await task
    assert result is (action == 'screen_off')
    assert 'dafeiyu_requested_screen' not in f.metadata
    assert not await r.answer(picture(stream, query['request_id']))
    if action == 'screen_off': assert f.metadata['dafeiyu_screen_state'] == 'not_shared'
    await r.close(); await c.close()


@pytest.mark.asyncio
async def test_input_invalidation_cancels_slow_classifier_without_cancelling_processor():
    r, c, client, events, _ = await fixture()
    started = asyncio.Event()
    async def slow(*args): started.set(); await asyncio.Event().wait()
    client.screen_request = slow
    f = frame(); task = asyncio.create_task(r.prepare(f)); await started.wait()
    r.invalidate()
    assert not await task and not task.cancelled() and not r.busy
    assert not any(e['type'] == 'voice.screen.request' for e in events)
    await r.close(); await c.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['ark','tokentosea'])
async def test_real_provider_serialization_uses_text_only_one_semantic_question(provider):
    calls = []
    def handler(request):
        body = json.loads(request.content); calls.append(body)
        return httpx.Response(200, json={'model': ARK_MODEL if provider == 'ark' else 'clef-omni',
            'answers': {'look_at_screen': {'type': 'noul', 'noul': .97}}})
    client = SystemOneClient({'systemone_provider': provider, 'systemone_ark_api_key': 'fixture',
        'systemone_api_key': 'fixture'}, transport=httpx.MockTransport(handler))
    try:
        assert await client.screen_request('看看当前屏幕', []) == .97
        assert len(calls) == 1 and calls[0]['questions'] == SCREEN_REQUEST_QUESTIONS
        assert 'images' not in calls[0] and 'audio' not in calls[0]
        prompt = SCREEN_REQUEST_QUESTIONS['look_at_screen']['instructions']
        assert '禁止' in prompt and '硬件' in prompt and '未来' in prompt
    finally: await client.close()


@pytest.mark.asyncio
async def test_normal_bridge_gets_image_once_then_stop_downgrades_without_old_image(tmp_path):
    r, c, _, events, stream = await fixture()
    f = frame(); task = asyncio.create_task(r.prepare(f)); query = await pending(r, events)
    await r.answer(picture(stream, query['request_id'])); assert await task
    bodies = []
    class Bridge:
        async def voice_turn(self, body): bodies.append(body)
    settings = Store(tmp_path)
    projection = ProjectionStore(settings, 's1', [], Bridge())
    llm = DSHLLMService(projection, 's1', DEFAULTS)
    llm.push_frame, llm.push_error = AsyncMock(), AsyncMock()
    await llm.process_frame(f, FrameDirection.DOWNSTREAM)
    assert bodies[-1]['dafeiyu']['kind'] == 'normal'
    assert bodies[-1]['dafeiyu']['screen_state'] == 'attached'
    assert len(bodies[-1]['dafeiyu']['images']) == 1
    await c.activate({'active': False, 'stream_id': stream}); r.sharing_changed()
    await llm.process_frame(f, FrameDirection.DOWNSTREAM)
    assert bodies[-1]['dafeiyu']['screen_state'] == 'not_shared'
    assert 'images' not in bodies[-1]['dafeiyu']
    r.invalidate()
    await llm.process_frame(f, FrameDirection.DOWNSTREAM)
    assert len(bodies) == 2, 'new input retires old generation before bridge'
    settings.db.close(); await r.close(); await c.close()
