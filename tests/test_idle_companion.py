import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from server.companion_context import native_context
from server.dsh import BridgeClient, BridgeUnavailable
from server.idle_companion import IdleCompanion
from server.screen_companion import ScreenBudget
from server.storage import DEFAULTS


def fixture(**overrides):
    clock = [100.0]
    events, offers = [], []
    budget = ScreenBudget()
    request = SimpleNamespace(busy=False, tool_pending=None, snapshot=AsyncMock(return_value={'available': False, 'reason': 'not_shared'}),
                              cancel_tool=lambda *a, **kw: None)
    screen = SimpleNamespace(user_speaking=False, bot_speaking=False, generating=False, pending_reply=False,
        playback_busy=lambda: False, external_busy=lambda: False, request=request,
        control=SimpleNamespace(budget=budget, task=None, stream_id=None), on_accept=lambda: None)
    async def offer(*args):
        offers.append(args)
    async def notify(event):
        events.append(event)
    screen.offer_idle = offer
    native = AsyncMock(return_value={'persona': 'fixture', 'busy': False})
    settings = {**DEFAULTS, 'idle_companion_enabled': True, 'idle_companion_after_s': 30,
                'idle_companion_cooldown_s': 30, **overrides}
    idle = IdleCompanion(settings, screen, native, notify=notify, clock=lambda: clock[0], jitter=lambda: 0)
    return idle, screen, native, clock, events, offers


@pytest.mark.asyncio
async def test_idle_timer_activity_optional_image_and_no_backlog():
    idle, screen, native, clock, events, offers = fixture(idle_companion_include_screen=False)
    clock[0] += 29
    assert not await idle.tick() and native.await_count == 0
    idle.activity()
    clock[0] += 29
    assert not await idle.tick()
    clock[0] += 1
    assert await idle.tick() and offers == [(None, idle.generation, None)]
    screen.request.snapshot.assert_not_awaited()
    assert events[-1] == {'type': 'voice.idle', 'status': 'accepted', 'reason': 'idle'}
    assert not await idle.tick() and len(offers) == 1
    clock[0] += 3600
    assert await idle.tick() and len(offers) == 2
    assert not await idle.tick()


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['user_speaking', 'bot_speaking', 'generating', 'pending_reply'])
async def test_busy_never_calls_native(field):
    idle, screen, native, clock, events, offers = fixture()
    setattr(screen, field, True)
    clock[0] += 30
    assert not await idle.tick() and not offers and native.await_count == 0
    assert events[-1]['reason'] == 'busy'


@pytest.mark.asyncio
async def test_native_busy_unavailable_and_shared_cooldown_and_budget():
    idle, screen, native, clock, events, offers = fixture(idle_companion_max_per_hour=1)
    clock[0] += 30
    native.return_value = {'persona': 'p', 'busy': True}
    assert not await idle.tick() and not offers
    clock[0] += 30
    native.return_value = {'persona': 'p', 'busy': False}
    screen.control.budget.mark_reply(clock[0])
    assert not await idle.tick() and events[-1]['reason'] == 'cooldown'
    clock[0] += 30
    assert await idle.tick()
    clock[0] += 30
    assert not await idle.tick() and events[-1]['reason'] == 'budget'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['activity', 'revoke', 'disconnect'])
async def test_stale_idle_snapshot_never_generates(change):
    idle, screen, native, clock, events, offers = fixture()
    screen.control.stream_id = 'shared'
    requested, resume = asyncio.Event(), asyncio.Event()
    async def snapshot(*, purpose):
        assert purpose == 'idle'
        requested.set()
        await resume.wait()
        return {'available': True, 'image': {'data': 'fixture'}, 'stream_id': 'shared'}
    screen.request.snapshot = snapshot
    clock[0] += 30
    task = asyncio.create_task(idle.tick())
    await requested.wait()
    if change == 'activity':
        idle.activity()
    elif change == 'revoke':
        screen.control.stream_id = None
    else:
        idle.closed = True
    resume.set()
    assert not await task and not offers


@pytest.mark.asyncio
async def test_idle_snapshot_is_fresh_and_optional():
    idle, screen, native, clock, events, offers = fixture()
    screen.control.stream_id = 'shared'
    screen.request.snapshot.return_value = {'available': True, 'stream_id': 'shared', 'image': {'data': 'fresh'}}
    clock[0] += 30
    assert await idle.tick()
    screen.request.snapshot.assert_awaited_once_with(purpose='idle')
    assert offers[0][0] == {'data': 'fresh'} and native.await_count == 2


@pytest.mark.asyncio
async def test_idle_opportunity_expires_during_snapshot():
    idle, screen, native, clock, events, offers = fixture()
    screen.control.stream_id = 'shared'
    async def late_snapshot(*, purpose):
        clock[0] += 9
        return {'available': True, 'stream_id': 'shared', 'image': {'data': 'late'}}
    screen.request.snapshot = late_snapshot
    clock[0] += 30
    assert not await idle.tick() and not offers


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['idle', 'screen'])
@pytest.mark.parametrize('case,expected', [('before_submit', []), ('before_first', ['first','second']), ('after_first', ['first', 'second']),
                                         ('revoked', ['first'])])
async def test_preview_deadline_applies_before_submission_not_model_generation(kind, case, expected):
    from pipecat.frames.frames import LLMContextFrame, LLMTextFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.frame_processor import FrameDirection
    from server.dsh_llm import DSHLLMService

    state = {'now': 9 if case == 'before_submit' else 0, 'current': True}
    async def chunks(body):
        if case == 'before_first':
            state['now'] = 9
        yield 'first'
        state['now'] = 9
        if case == 'revoked':
            state['current'] = False
        yield 'second'
    bridge = SimpleNamespace(chat_text=chunks)
    store = SimpleNamespace(bridge=bridge, messages=lambda session: [], model='fixture', temperature_supported=False)
    processor = DSHLLMService(store, 's', DEFAULTS)
    processor.push_frame = AsyncMock()
    processor.push_error = AsyncMock()
    request = LLMContextFrame(LLMContext(messages=[{'role': 'user', 'content': 'background'}]))
    payload = {'image': None if kind == 'idle' else {'data': 'fixture'}, 'max_reply_chars': 64}
    if kind == 'screen':
        payload['screen_mode'] = 'direct'
    request.metadata[f'dafeiyu_{kind}'] = payload
    request.metadata[f'dafeiyu_{kind}_valid'] = lambda: state['now'] <= 8 and state['current']
    request.metadata[f'dafeiyu_{kind}_current'] = lambda: state['current']
    await processor.process_frame(request, FrameDirection.DOWNSTREAM)
    text = [call.args[0].text for call in processor.push_frame.await_args_list
            if isinstance(call.args[0], LLMTextFrame)]
    assert text == expected
    processor.push_error.assert_not_awaited()


@pytest.mark.asyncio
async def test_activity_only_cancels_idle_snapshot():
    from server.screen_request import RequestedScreen
    control = SimpleNamespace(enabled=True, stream_id='shared', seq=0)
    request = RequestedScreen(None, DEFAULTS, control, lambda: [], AsyncMock())
    future = asyncio.get_running_loop().create_future()
    request.tool_pending = {'purpose': 'tool', 'future': future}
    request.cancel_tool('activity', purpose='idle')
    assert not future.done()
    request.cancel_tool('activity')
    assert (await future)['reason'] == 'activity'


@pytest.mark.asyncio
async def test_native_context_is_bounded_and_does_not_include_environment_or_history():
    bridge = SimpleNamespace(voice_context=AsyncMock(return_value={
        'persona': 'p' * 9000, 'busy': False, 'environment': 'secret', 'messages': ['secret']}))
    result = await native_context(bridge, 's')
    assert result == {'persona': 'p' * 8000, 'busy': False}
    bridge.voice_context.return_value = {'persona': 'p', 'busy': 'false'}
    assert await native_context(bridge, 's') is None


@pytest.mark.asyncio
async def test_native_busy_after_snapshot_blocks_offer():
    idle, screen, native, clock, events, offers = fixture()
    native.side_effect = [{'persona': 'p', 'busy': False}, {'persona': 'p', 'busy': True}]
    clock[0] += 30
    assert not await idle.tick() and not offers
    assert events[-1]['reason'] == 'busy'


@pytest.mark.asyncio
async def test_shared_screen_reply_budget_blocks_idle():
    idle, screen, native, clock, events, offers = fixture(screen_companion_max_replies_per_hour=1)
    screen.control.budget.replies.append(clock[0])
    clock[0] += 30
    assert not await idle.tick() and not offers and native.await_count == 0
    assert events[-1]['reason'] == 'budget'


@pytest.mark.asyncio
@pytest.mark.parametrize('meta,allowed', [
    ({'kind': 'idle'}, True), ({'kind': 'screen', 'screen_mode': 'direct'}, True),
    ({'kind': 'screen', 'screen_mode': 'systemone'}, False), ({'kind': 'initiative'}, False),
])
async def test_empty_preview_requires_correct_kind_and_done(meta, allowed):
    async def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text='data: [DONE]\n\n')
    bridge = BridgeClient('http://127.0.0.1:1234', 'secret', transport=httpx.MockTransport(handler))
    async def collect():
        return [chunk async for chunk in bridge.chat_text({'dafeiyu': meta})]
    if allowed:
        assert await collect() == []
    else:
        with pytest.raises(BridgeUnavailable):
            await collect()


@pytest.mark.asyncio
async def test_empty_preview_truncated_stream_is_still_error():
    async def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text='data: {}\n\n')
    bridge = BridgeClient('http://127.0.0.1:1234', 'secret', transport=httpx.MockTransport(handler))
    with pytest.raises(BridgeUnavailable):
        _ = [chunk async for chunk in bridge.chat_text({'dafeiyu': {'kind': 'idle'}})]
