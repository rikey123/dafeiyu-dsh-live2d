import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pipecat.frames.frames import InterruptionFrame, LLMContextFrame, LLMTextFrame, LLMFullResponseStartFrame, LLMFullResponseEndFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from server.dsh import BridgeClient, BridgeUnavailable
from server.dsh_llm import DSHLLMService


def service(bridge):
    store = SimpleNamespace(bridge=bridge, model='dsh', temperature_supported=False,
                            messages=lambda _: [])
    instance = DSHLLMService(store, 'session', {'system_prompt': '', 'temperature': 0.7})
    instance.push_frame = AsyncMock()
    instance.push_error = AsyncMock()
    return instance


@pytest.mark.asyncio
async def test_submission_returns_without_waiting_for_output_and_interruption_only_mutes_current_generation():
    bridge = SimpleNamespace(voice_turn=AsyncMock())
    llm = service(bridge)
    frame = LLMContextFrame(LLMContext(messages=[{'role': 'user', 'content': 'hello'}]))
    await llm.process_frame(frame, FrameDirection.DOWNSTREAM)
    assert bridge.voice_turn.await_count == 1
    assert llm.push_frame.await_count == 0
    await llm._event({'type': 'response.start', 'generation_id': 'a', 'kind': 'normal'})
    await llm._event({'type': 'response.text', 'generation_id': 'a', 'kind': 'normal', 'text': 'first'})
    await llm.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await llm._event({'type': 'response.text', 'generation_id': 'a', 'kind': 'normal', 'text': 'muted'})
    await llm._event({'type': 'response.end', 'generation_id': 'a', 'kind': 'normal'})
    await llm._event({'type': 'response.start', 'generation_id': 'child', 'kind': 'child'})
    await llm._event({'type': 'response.text', 'generation_id': 'child', 'kind': 'child', 'text': 'later'})
    await llm._event({'type': 'response.end', 'generation_id': 'child', 'kind': 'child'})
    texts = [call.args[0].text for call in llm.push_frame.await_args_list if isinstance(call.args[0], LLMTextFrame)]
    assert texts == ['first', 'later']
    assert bridge.voice_turn.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', [
    {'type': 'response.error', 'code': 'AGENT_ERROR'},
    {'type': 'response.error', 'code': 'OTHER_TASK_ERROR'},
    {'type': 'response.end', 'outcome': 'error'},
])
async def test_agent_failure_closes_response_and_later_public_reply_is_delivered(ending):
    bridge = SimpleNamespace(voice_turn=AsyncMock())
    llm = service(bridge)
    await llm._event({'type': 'response.start', 'generation_id': 'a', 'kind': 'normal'})
    await llm._event({**ending, 'generation_id': 'a', 'kind': 'normal'})
    assert llm._generation is None
    await llm._event({'type': 'response.start', 'generation_id': 'parent', 'kind': 'normal'})
    await llm._event({'type': 'response.text', 'generation_id': 'parent', 'kind': 'normal', 'text': '任务失败了，我会继续处理。'})
    await llm._event({'type': 'response.end', 'generation_id': 'parent', 'kind': 'normal'})
    frames = [call.args[0] for call in llm.push_frame.await_args_list]
    assert [type(frame) for frame in frames] == [LLMFullResponseStartFrame, LLMFullResponseEndFrame,
                                                LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame]
    assert frames[1].metadata['generation_id'] == 'a'
    assert frames[3].text == '任务失败了，我会继续处理。'
    llm.push_error.assert_not_awaited()
    bridge.voice_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_stream_gap_reports_transport_error_and_closes_response():
    llm = service(SimpleNamespace())
    await llm._event({'type': 'response.start', 'generation_id': 'a', 'kind': 'normal'})
    await llm._event({'type': 'response.error', 'generation_id': 'a', 'kind': 'normal', 'code': 'VOICE_STREAM_GAP'})
    llm.push_error.assert_awaited_once_with(error_msg='DSH voice stream has missing or out-of-order text')
    assert llm._generation is None
    assert isinstance(llm.push_frame.await_args_list[-1].args[0], LLMFullResponseEndFrame)
    assert llm.push_frame.await_args_list[-1].args[0].metadata['generation_id'] == 'a'


@pytest.mark.asyncio
async def test_sse_cursor_reconnect_no_resubmit_and_cleanup():
    requests = []
    waiting = asyncio.Event()
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'id: ready\ndata: {"type":"ready"}\n\n'
            yield b'id: 42\ndata: {"type":"response.start","generation_id":"g","kind":"normal"}\n\n'
        async def aclose(self): pass
    class WaitStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'id: ready2\ndata: {"type":"ready"}\n\n'
            waiting.set()
            await asyncio.Event().wait()
            yield b''
        async def aclose(self): pass
    async def handler(request):
        requests.append(request)
        if request.url.path.endswith('/events'):
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream() if sum(r.url.path.endswith('/events') for r in requests) == 1 else WaitStream())
        return httpx.Response(200, json={'ok': True})
    bridge = BridgeClient('http://127.0.0.1:1234', 'secret', transport=httpx.MockTransport(handler))
    llm = service(bridge)
    llm._pipeline_started.set()
    await llm.start_listening()
    await asyncio.wait_for(waiting.wait(), 2)
    await llm.close_listening()
    events = [r for r in requests if r.url.path.endswith('/events')]
    assert events[1].headers['last-event-id'] == '42'
    assert not any(r.url.path.endswith('/turns') for r in requests)
    states = [json.loads(r.content) for r in requests if r.url.path.endswith('/state')]
    assert [s['active'] for s in states] == [True, False]
    assert states[0]['connection_id'] == states[1]['connection_id']


@pytest.mark.asyncio
async def test_invalid_admission_and_event_data_fail_closed():
    async def handler(request):
        if request.url.path.endswith('/turns'):
            return httpx.Response(200, json={'accepted': True, 'request_id': 'wrong'})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=b'id: 1\ndata: secret-not-json\n\n')
    bridge = BridgeClient('http://127.0.0.1:1234', 'secret', transport=httpx.MockTransport(handler))
    with pytest.raises(BridgeUnavailable):
        await bridge.voice_turn({'dafeiyu': {'request_id': 'right'}})
    with pytest.raises(BridgeUnavailable) as exc:
        _ = [event async for event in bridge.voice_events('s')]
    assert 'secret' not in str(exc.value)

@pytest.mark.asyncio
async def test_preview_uses_compat_stream_not_native_admission():
    async def preview(body):
        yield 'preview'
    bridge = SimpleNamespace(voice_turn=AsyncMock(), chat_text=preview)
    llm = service(bridge)
    llm.initiative = lambda: True
    await llm.process_frame(LLMContextFrame(LLMContext(messages=[{'role': 'user', 'content': 'hello'}])), FrameDirection.DOWNSTREAM)
    bridge.voice_turn.assert_not_awaited()
    assert [c.args[0].text for c in llm.push_frame.await_args_list if isinstance(c.args[0], LLMTextFrame)] == ['preview']

@pytest.mark.asyncio
async def test_ready_handshake_blocks_admission_until_listener_connected():
    allow_ready = asyncio.Event()
    opened = asyncio.Event()
    calls = []
    async def events(session, cursor):
        opened.set()
        await allow_ready.wait()
        yield '1', {'type': 'ready'}
        await asyncio.Event().wait()
    async def turn(body):
        calls.append(body)
    bridge = SimpleNamespace(voice_state=AsyncMock(), voice_events=events, voice_turn=turn)
    llm = service(bridge)
    startup = asyncio.create_task(llm.start_listening())
    await opened.wait()
    frame = LLMContextFrame(LLMContext(messages=[{'role': 'user', 'content': 'hello'}]))
    submission = asyncio.create_task(llm.process_frame(frame, FrameDirection.DOWNSTREAM))
    await asyncio.sleep(0)
    assert not startup.done() and not calls
    allow_ready.set()
    await asyncio.wait_for(asyncio.gather(startup, submission), 1)
    assert len(calls) == 1
    await llm.close_listening()


@pytest.mark.asyncio
async def test_reset_ends_current_response_and_allows_future_generation_without_resubmit():
    bridge = SimpleNamespace(voice_turn=AsyncMock())
    llm = service(bridge)
    await llm._event({'type': 'response.start', 'generation_id': 'first', 'kind': 'normal'})
    await llm._event({'type': 'reset', 'reason': 'private-secret'})
    assert llm._generation is None
    llm.push_error.assert_awaited_once_with(error_msg='DSH voice event history unavailable')
    from pipecat.frames.frames import LLMFullResponseEndFrame
    ends = [c.args[0] for c in llm.push_frame.await_args_list if isinstance(c.args[0], LLMFullResponseEndFrame)]
    assert len(ends) == 1 and ends[0].metadata['generation_id'] == 'first'
    await llm._event({'type': 'response.text', 'generation_id': 'first', 'kind': 'normal', 'text': 'stale'})
    await llm._event({'type': 'response.start', 'generation_id': 'later', 'kind': 'normal'})
    await llm._event({'type': 'response.text', 'generation_id': 'later', 'kind': 'normal', 'text': 'new'})
    assert [c.args[0].text for c in llm.push_frame.await_args_list if isinstance(c.args[0], LLMTextFrame)] == ['new']
    bridge.voice_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_before_first_start_does_not_suppress_future_native_attempt():
    llm = service(SimpleNamespace(voice_turn=AsyncMock()))
    await llm.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await llm._event({'type': 'response.start', 'generation_id': 'random-attempt', 'kind': 'normal'})
    await llm._event({'type': 'response.text', 'generation_id': 'random-attempt', 'kind': 'normal', 'text': 'future'})
    assert [c.args[0].text for c in llm.push_frame.await_args_list if isinstance(c.args[0], LLMTextFrame)] == ['future']

@pytest.mark.asyncio
async def test_reconnect_reset_closes_open_response_without_resubmission():
    cursors = []
    reset_seen = asyncio.Event()
    async def events(session, cursor):
        cursors.append(cursor)
        if len(cursors) == 1:
            yield 'ready-1', {'type': 'ready'}
            yield 'start-1', {'type': 'response.start', 'generation_id': 'native', 'kind': 'normal'}
        else:
            yield 'ready-2', {'type': 'ready'}
            yield 'reset-1', {'type': 'reset'}
            await asyncio.Event().wait()
    bridge = SimpleNamespace(voice_state=AsyncMock(), voice_events=events, voice_turn=AsyncMock())
    llm = service(bridge)
    llm._pipeline_started.set()
    async def error(**kwargs):
        assert kwargs == {'error_msg': 'DSH voice event history unavailable'}
        reset_seen.set()
    llm.push_error = error
    await llm.start_listening()
    await asyncio.wait_for(reset_seen.wait(), 2)
    assert cursors == [None, 'start-1']
    assert llm._generation is None
    bridge.voice_turn.assert_not_awaited()
    await llm.close_listening()


@pytest.mark.asyncio
async def test_stop_before_delayed_start_mutes_only_already_admitted_request():
    bridge = SimpleNamespace(voice_turn=AsyncMock())
    llm = service(bridge)
    await llm.process_frame(LLMContextFrame(LLMContext(messages=[{'role':'user','content':'old'}])), FrameDirection.DOWNSTREAM)
    request_id = bridge.voice_turn.await_args.args[0]['dafeiyu']['request_id']
    await llm.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await llm._event({'type':'response.start','generation_id':'late','request_id':request_id,'kind':'normal'})
    await llm._event({'type':'response.text','generation_id':'late','text':'muted','kind':'normal'})
    await llm._event({'type':'response.end','generation_id':'late','kind':'normal'})
    await llm._event({'type':'turn.end','request_id':request_id})
    await llm._event({'type':'response.start','generation_id':'followup','kind':'normal'})
    await llm._event({'type':'response.text','generation_id':'followup','text':'later parent delivery','kind':'normal'})
    assert [c.args[0].text for c in llm.push_frame.await_args_list if isinstance(c.args[0],LLMTextFrame)] == ['later parent delivery']
    assert bridge.voice_turn.await_count == 1


@pytest.mark.asyncio
async def test_native_composer_input_updates_acoustic_context_once_without_resubmission(tmp_path):
    from server.dsh import ProjectionStore
    from server.storage import Store
    bridge = SimpleNamespace(voice_turn=AsyncMock())
    store = ProjectionStore(Store(tmp_path), 'session', [], bridge)
    notified = AsyncMock()
    llm = DSHLLMService(store,'session',store.settings(private=True),notify=notified)
    event = {'type':'conversation.user','message_id':'native-user','text':'来自原生输入框','request_id':'native-request'}
    await llm._event(event)
    await llm._event(event)
    assert [row['content'] for row in store.messages('session')] == ['来自原生输入框']
    notified.assert_awaited_once_with({'type':'voice.native.user','text':'来自原生输入框','message_id':'native-user'})
    bridge.voice_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_user_echo_reconciles_voice_turn_instead_of_duplicating_it(tmp_path):
    from server.dsh import ProjectionStore
    from server.storage import Store
    bridge = SimpleNamespace(voice_turn=AsyncMock())
    store = ProjectionStore(Store(tmp_path), 'session', [], bridge)
    local_id = store.add_message('session','user','我说的话')
    notified = AsyncMock()
    llm = DSHLLMService(store,'session',store.settings(private=True),notify=notified)
    llm.push_frame = AsyncMock()
    await llm.process_frame(LLMContextFrame(LLMContext(messages=[{'role':'user','content':'我说的话'}])), FrameDirection.DOWNSTREAM)
    request_id = bridge.voice_turn.await_args.args[0]['dafeiyu']['request_id']
    await llm._event({'type':'conversation.user','message_id':'native-user','text':'我说的话','request_id':request_id})
    assert [row['id'] for row in store.messages('session')] == [local_id]
    notified.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('request_id', [[], {}, 42, '', 'x' * 257])
async def test_invalid_native_event_request_id_cannot_kill_listener(request_id):
    llm = service(SimpleNamespace(voice_turn=AsyncMock()))
    for typ in ['conversation.user', 'turn.end', 'response.start']:
        await llm._event({'type':typ, 'request_id':request_id, 'message_id':'u', 'text':'ignored', 'generation_id':'g', 'kind':'normal'})
    assert llm._generation is None


@pytest.mark.asyncio
async def test_moss_context_and_observation_use_private_native_bridge():
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path.endswith('/context'):
            assert request.url.params['session_id'] == 'session'
            return httpx.Response(200, json={'persona':'native persona','messages':[]})
        return httpx.Response(200, json={'accepted':True})
    bridge = BridgeClient('http://127.0.0.1:1234', 'secret', transport=httpx.MockTransport(handler))
    assert (await bridge.voice_context('session'))['persona'] == 'native persona'
    assert (await bridge.voice_observation('session','event','user','hello',True))['accepted']
    assert calls[1].url.path == '/v1/voice/observations'
