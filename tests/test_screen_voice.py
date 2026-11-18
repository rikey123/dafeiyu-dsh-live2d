"""Screen-to-existing-voice integration. Models and speech HTTP are fixtures.

The websocket, protobuf framing, Pipecat processors, native bridge protocol,
TTS service and playback ACK are real; no microphone, GPU or paid API is used.
"""
import asyncio
import base64
import io
import json
import threading
import uuid
from unittest.mock import AsyncMock

import httpx
import anyio
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pipecat.frames.frames import LLMContextFrame, VADUserStartedSpeakingFrame
from pipecat.frames.protobufs import frames_pb2
from pipecat.processors.frame_processor import FrameDirection

from server import main, pipecat_voice, screen_voice
from server.dsh import BridgeClient, ProjectionStore
from server.dsh_llm import DSHLLMService
from server.screen_voice import ScreenVoice, ScreenReplyGate
from server.storage import Store
from server.systemone import InitiativeDecision, SystemOneClient
from speech.pipecat_services import LocalSpeechTTS

REAL_SCREEN_DECIDE = SystemOneClient.decide


def install_idle_clock(monkeypatch, store):
    import server.idle_companion as module
    original = module.IdleCompanion
    clock = [100.0]
    class ControlledIdle(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, clock=lambda: clock[0], jitter=lambda: 0)
            store.fixture_idle = self
    monkeypatch.setattr(module, 'IdleCompanion', ControlledIdle)
    return clock


def picture(stream, seq=1):
    out = io.BytesIO()
    Image.new('RGB', (40, 30), 'blue').save(out, 'JPEG')
    return dict(stream_id=stream, seq=seq, mime_type='image/jpeg', width=40,
                height=30, data=base64.b64encode(out.getvalue()).decode())


def send(ws, kind, data):
    frame = frames_pb2.Frame()
    message = ({'label': 'rtvi-ai', 'type': 'client-ready', 'id': uuid.uuid4().hex, 'data': {}}
        if kind == 'ready' else {'label': 'rtvi-ai', 'type': 'client-message',
        'id': uuid.uuid4().hex, 'data': {'t': kind, 'd': data}})
    frame.message.data = json.dumps(message)
    ws.send_bytes(frame.SerializeToString())


def until(ws, check):
    async def bounded():
        with anyio.fail_after(12):
            for _ in range(200):
                message = await ws._send_rx.receive()
                ws._raise_on_close(message)
                frame = frames_pb2.Frame.FromString(message['bytes'])
                if frame.WhichOneof('frame') == 'message':
                    message = json.loads(frame.message.data)
                    if check(message):
                        return message
            raise AssertionError('expected voice event not received')
    return ws.portal.call(bounded)


@pytest.fixture
def screen_plugin(tmp_path, monkeypatch):
    for key, value in {'DAFEIYU_HARNESS': 'dsh', 'DAFEIYU_PLUGIN_TOKEN': 'plugin-secret',
        'DAFEIYU_DSH_BRIDGE_TOKEN': 'bridge-secret',
        'DAFEIYU_DSH_BRIDGE_URL': 'http://127.0.0.1:1234'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(screen_voice, '_shared_budget', None)
    store = Store(tmp_path)
    store.update_settings({'systemone_enabled': True, 'screen_companion_enabled': True,
        'systemone_initiative_enabled': False, 'tts_mode': 'cpu'})
    monkeypatch.setattr(main, 'store', store)
    bodies, played, synthesized, decisions = [], [], [], []
    event_queue = asyncio.Queue()
    states = []
    store.fixture_events = event_queue
    store.fixture_states = states
    store.fixture_auto_reply = True
    store.fixture_stream_closed = threading.Event()
    store.fixture_inactive = threading.Event()
    store.fixture_generations = []
    store.fixture_native_generation = None
    store.fixture_empty_preview = False
    store.fixture_preview_seen = threading.Event()
    store.fixture_busy = False
    original_begin = pipecat_voice.PlaybackLedger.begin_generation
    def capture_generation(ledger, generation):
        store.fixture_generations.append(generation)
        return original_begin(ledger, generation)
    monkeypatch.setattr(pipecat_voice.PlaybackLedger, 'begin_generation', capture_generation)
    class EventStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'id: ready-1\ndata: {"type":"ready"}\n\n'
            while True:
                event = await event_queue.get()
                yield ('id: ' + uuid.uuid4().hex + '\ndata: ' + json.dumps(event) + '\n\n').encode()
        async def aclose(self):
            store.fixture_stream_closed.set()
    async def handle(request):
        if request.url.path.endswith('/messages'):
            return httpx.Response(200, json=[])
        if request.url.path == '/v1/voice/state':
            states.append(json.loads(request.content))
            if not states[-1]['active']:
                store.fixture_inactive.set()
            return httpx.Response(200, json={'accepted': True})
        if request.url.path == '/v1/voice/events':
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=EventStream())
        if request.url.path == '/v1/voice/context':
            return httpx.Response(200, json={'persona': 'native persona', 'environment': '',
                                             'busy': store.fixture_busy, 'messages': []})
        if request.url.path == '/v1/voice/turns':
            body = json.loads(request.content)
            bodies.append(body)
            if store.fixture_auto_reply:
                generation = uuid.uuid4().hex
                store.fixture_native_generation = generation
                for event in (
                    {'type': 'response.start', 'generation_id': generation, 'kind': 'normal'},
                    {'type': 'response.text', 'generation_id': generation, 'kind': 'normal', 'text': 'Nice game!'},
                    {'type': 'response.end', 'generation_id': generation, 'kind': 'normal'},
                ):
                    event_queue.put_nowait(event)
            return httpx.Response(200, json={'accepted': True, 'request_id': body['dafeiyu']['request_id']})
        if request.url.path == '/v1/chat/completions':
            bodies.append(json.loads(request.content))
            store.fixture_preview_seen.set()
            if store.fixture_empty_preview:
                return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text='data: [DONE]\n\n')
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                text='data: {"choices":[{"delta":{"content":"Nice game!"}}]}\n\ndata: [DONE]\n\n')
        if request.url.path == '/v1/playback':
            played.append(json.loads(request.content))
            return httpx.Response(200, json={'accepted': True})
        return httpx.Response(200, json={'ready': True, 'configured': True,
            'provider': 'dsh', 'model': 'fixture-image', 'screen_ready': True})
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(main.dsh, 'BridgeClient', lambda: BridgeClient(
        'http://127.0.0.1:1234', 'bridge-secret', transport=transport))
    async def speech(request):
        assert request.url.path == '/v1/audio/speech/stream'
        synthesized.append(json.loads(request.content))
        return httpx.Response(200, content=b'\x01\x00' * 2400, headers={
            'X-Audio-Sample-Rate': '24000', 'X-Audio-Channels': '1', 'X-Audio-Format': 'pcm_s16le'})
    def tts(settings):
        service = LocalSpeechTTS(base_url='http://fixture', sample_rate=24000,
                                 reuse_context_id_within_turn=False)
        service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(speech))
        return service
    monkeypatch.setattr(pipecat_voice, 'create_tts', tts)
    async def affect(*args): return None
    monkeypatch.setattr(SystemOneClient, 'affect', affect)
    async def decide(self, image, context, timeout, style="balanced"):
        decisions.append(image)
        return self.fixture_decision
    monkeypatch.setattr(SystemOneClient, 'decide', decide)
    monkeypatch.setattr(SystemOneClient, 'fixture_decision', InitiativeDecision(.98, .01, 'comment'), raising=False)
    async def request_screen(self, text, context): return .98
    monkeypatch.setattr(SystemOneClient, 'screen_request', request_screen)
    with TestClient(main.app) as client:
        yield client, store, bodies, played, synthesized, decisions


def connect(client):
    return client.websocket_connect('/ws/voice?session_id=s1',
        headers={'X-Dafeiyu-Plugin-Token': 'plugin-secret'})


@pytest.mark.parametrize('silent', [False, True])
@pytest.mark.parametrize('initiative', [False, True])
def test_idle_uses_real_preview_pipeline_and_empty_is_silent(screen_plugin, monkeypatch, silent, initiative):
    client, store, bodies, played, speech, decisions = screen_plugin
    store.update_settings({'systemone_enabled': initiative, 'systemone_initiative_enabled': initiative,
                           'screen_companion_enabled': False,
                           'idle_companion_enabled': True, 'idle_companion_after_s': 30,
                           'idle_companion_include_screen': False})
    store.fixture_empty_preview = silent
    clock = install_idle_clock(monkeypatch, store)
    with connect(client) as ws:
        send(ws, 'ready', {})
        until(ws, lambda m: m.get('type') == 'bot-ready')
        clock[0] += 30
        assert ws.portal.call(store.fixture_idle.tick)
        until(ws, lambda m: m.get('data', {}).get('type') == 'voice.idle' and m['data']['status'] == 'accepted')
        assert store.fixture_preview_seen.wait(5)
        if not silent:
            boundary = until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary')['data']
            send(ws, 'voice.playback', {'epoch': boundary['epoch'], 'consumed_samples': boundary['samples'],
                                        'sample_rate': 24000, 'completed': True})
            until(ws, lambda m: m.get('type') == 'server-response' and m.get('data', {}).get('t') == 'voice.playback')
        else:
            # A priority response confirms the pipeline has had a chance to consume the preview.
            send(ws, 'voice.capture', {'active': False})
            until(ws, lambda m: m.get('type') == 'server-response' and m.get('data', {}).get('t') == 'voice.capture')
    assert len(bodies) == 1 and bodies[0]['dafeiyu']['kind'] == 'idle'
    assert 'images' not in bodies[0]['dafeiyu'] and 'screen_mode' not in bodies[0]['dafeiyu']
    assert '不要先概述画面' not in bodies[0]['messages'][-1]['content']
    assert len(speech) == (0 if silent else 1)
    assert len(played) == (0 if silent else 1)
    assert not decisions


def test_direct_preview_bypasses_jev_and_allows_empty(screen_plugin):
    client, store, bodies, played, speech, decisions = screen_plugin
    store.update_settings({'systemone_enabled': False, 'screen_companion_mode': 'direct'})
    store.fixture_empty_preview = True
    with connect(client) as ws:
        start(ws)
        until(ws, lambda m: m.get('data', {}).get('reason') == 'direct')
        assert store.fixture_preview_seen.wait(5)
        send(ws, 'voice.capture', {'active': False})
        until(ws, lambda m: m.get('type') == 'server-response' and m.get('data', {}).get('t') == 'voice.capture')
    assert len(bodies) == 1 and bodies[0]['dafeiyu']['screen_mode'] == 'direct'
    assert 'max_reply_chars' not in bodies[0]['dafeiyu']
    assert bodies[0]['dafeiyu']['kind'] == 'screen' and not decisions and not speech and not played
    prompt = bodies[0]['messages'][-1]['content']
    assert '主动陪用户一起看屏幕' in prompt and '不要先概述画面' in prompt
    assert '看法、感受、吐槽或联想' in prompt and '保持安静' in prompt


@pytest.mark.parametrize('cancel', [False, True])
def test_idle_snapshot_is_fresh_and_new_text_invalidates(screen_plugin, monkeypatch, cancel):
    client, store, bodies, played, speech, decisions = screen_plugin
    store.update_settings({'systemone_enabled': False, 'screen_companion_mode': 'direct',
                           'idle_companion_enabled': True, 'idle_companion_after_s': 30})
    store.fixture_auto_reply = False
    clock = install_idle_clock(monkeypatch, store)
    with connect(client) as ws:
        stream = share_without_frame(ws)
        clock[0] += 30
        pending = ws.portal.start_task_soon(store.fixture_idle.tick)
        request = until(ws, lambda m: m.get('data', {}).get('type') == 'voice.screen.request')['data']
        assert request['purpose'] == 'idle' and request['stream_id'] == stream
        if cancel:
            question(ws, 'new user message')
            assert pending.result(timeout=5) is False
            send(ws, 'voice.screen.snapshot', {**picture(stream), 'request_id': request['request_id']})
        else:
            send(ws, 'voice.screen.snapshot', {**picture(stream), 'request_id': request['request_id']})
            assert pending.result(timeout=5) is True
            assert store.fixture_preview_seen.wait(5)
            boundary = until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary')['data']
            send(ws, 'voice.playback', {'epoch': boundary['epoch'], 'consumed_samples': boundary['samples'],
                                        'sample_rate': 24000, 'completed': True})
            until(ws, lambda m: m.get('type') == 'server-response' and m.get('data', {}).get('t') == 'voice.playback')
    previews = [body for body in bodies if body['dafeiyu']['kind'] == 'idle']
    assert len(previews) == (0 if cancel else 1)
    if previews:
        assert len(previews[0]['dafeiyu']['images']) == 1
        prompt = previews[0]['messages'][-1]['content']
        assert '若想聊附带的新画面' in prompt and '不要先概述画面' in prompt


def test_idle_respects_native_agent_busy(screen_plugin, monkeypatch):
    client, store, bodies, played, speech, decisions = screen_plugin
    store.update_settings({'systemone_enabled': False, 'screen_companion_enabled': False,
                           'idle_companion_enabled': True, 'idle_companion_after_s': 30})
    store.fixture_busy = True
    clock = install_idle_clock(monkeypatch, store)
    with connect(client) as ws:
        send(ws, 'ready', {})
        until(ws, lambda m: m.get('type') == 'bot-ready')
        clock[0] += 30
        assert not ws.portal.call(store.fixture_idle.tick)
        until(ws, lambda m: m.get('data', {}).get('type') == 'voice.idle' and m['data']['reason'] == 'busy')
    assert not bodies and not speech and not played and not decisions


def start(ws):
    send(ws, 'ready', {})
    until(ws, lambda m: m.get('type') == 'bot-ready')
    stream = str(uuid.uuid4())
    send(ws, 'voice.screen', {'active': True, 'stream_id': stream})
    until(ws, lambda m: m.get('data', {}).get('status') == 'active')
    send(ws, 'voice.screen.frame', picture(stream))
    return stream


def question(ws, text='能看到我当前屏幕吗？帮我看看上面的图表。'):
    proto = frames_pb2.Frame()
    proto.message.data = json.dumps({'label': 'rtvi-ai', 'type': 'send-text',
        'id': uuid.uuid4().hex, 'data': {'content': text}})
    ws.send_bytes(proto.SerializeToString())


def share_without_frame(ws):
    send(ws, 'ready', {})
    until(ws, lambda m: m.get('type') == 'bot-ready')
    stream = str(uuid.uuid4())
    send(ws, 'voice.screen', {'active': True, 'stream_id': stream})
    until(ws, lambda m: m.get('data', {}).get('status') == 'active')
    return stream


def test_user_screen_request_uses_fresh_priority_snapshot_and_one_normal_reply(screen_plugin):
    client, store, bodies, played, speech, decisions = screen_plugin
    with connect(client) as ws:
        stream = share_without_frame(ws)
        question(ws)
        request = until(ws, lambda m: m.get('data', {}).get('type') == 'voice.screen.request')['data']
        assert request['stream_id'] == stream
        send(ws, 'voice.screen.snapshot', {**picture(stream), 'request_id': request['request_id']})
        boundary = until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary')['data']
        send(ws, 'voice.playback', {'epoch': boundary['epoch'], 'consumed_samples': boundary['samples'],
            'sample_rate': 24000, 'completed': True})
        ack = until(ws, lambda m: m.get('type') == 'server-response' and m.get('data', {}).get('t') == 'voice.playback')
        assert ack['data']['d']['accepted'] is True
    assert len(bodies) == len(speech) == 1 and not decisions
    body = bodies[0]
    assert body['dafeiyu']['kind'] == 'normal' and body['dafeiyu']['screen_state'] == 'attached'
    assert body['messages'][-1]['content'] == '能看到我当前屏幕吗？帮我看看上面的图表。'
    assert len(body['dafeiyu']['images']) == 1
    assert store.fixture_native_generation in store.fixture_generations
    assert store.fixture_native_generation != body['dafeiyu']['request_id']
    assert played == []  # Ordinary native history is independent of playback ACK.
    assert store.sessions() == []


def test_no_screen_permission_still_answers_question_without_faking_visual_input(screen_plugin):
    client, _, bodies, _, speech, decisions = screen_plugin
    with connect(client) as ws:
        send(ws, 'ready', {}); until(ws, lambda m: m.get('type') == 'bot-ready')
        question(ws)
        until(ws, lambda m: m.get('data', {}).get('reason') == 'request_not_shared')
        until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary')
    assert len(bodies) == len(speech) == 1 and not decisions
    assert bodies[0]['dafeiyu']['screen_state'] == 'not_shared'
    assert 'images' not in bodies[0]['dafeiyu']


def test_screen_off_resolves_pending_snapshot_without_stalling_normal_question(screen_plugin):
    client, _, bodies, _, speech, _ = screen_plugin
    with connect(client) as ws:
        stream = share_without_frame(ws)
        question(ws)
        request = until(ws, lambda m: m.get('data', {}).get('type') == 'voice.screen.request')['data']
        send(ws, 'voice.screen', {'active': False, 'stream_id': stream})
        send(ws, 'voice.screen.snapshot', {**picture(stream), 'request_id': request['request_id']})
        until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary')
    assert len(bodies) == len(speech) == 1
    assert bodies[0]['dafeiyu']['screen_state'] == 'not_shared'
    assert 'images' not in bodies[0]['dafeiyu']


def test_low_desire_never_calls_dsh_or_tts(screen_plugin, monkeypatch):
    client, store, bodies, played, speech, decisions = screen_plugin
    monkeypatch.setattr(SystemOneClient, 'fixture_decision', InitiativeDecision(.1, .8, 'wait'))
    with connect(client) as ws:
        start(ws)
        until(ws, lambda m: m.get('data', {}).get('reason') == 'low_desire')
    assert len(decisions) == 1 and bodies == speech == []
    assert store.sessions() == []


def test_unknown_dsh_image_support_rejects_before_judgment_and_capture_upload(screen_plugin, monkeypatch):
    client, _, bodies, _, speech, decisions = screen_plugin
    monkeypatch.setattr(BridgeClient, 'status', AsyncMock(return_value={
        'model':'text-only', 'ready':True, 'configured':True, 'screen_ready':False}))
    settings = client.get('/api/settings', headers={'X-Dafeiyu-Plugin-Token':'plugin-secret'}).json()
    assert settings['screen_model_ready'] is False
    with connect(client) as ws:
        send(ws, 'ready', {})
        until(ws, lambda m: m.get('type') == 'bot-ready')
        send(ws, 'voice.screen', {'active':True, 'stream_id':str(uuid.uuid4())})
        until(ws, lambda m: m.get('data', {}).get('reason') == 'requires_image_capable_dsh_model')
    assert bodies == speech == decisions == []


def test_high_desire_uses_existing_tts_ack_and_no_fake_user_history(screen_plugin):
    client, store, bodies, played, speech, decisions = screen_plugin
    with connect(client) as ws:
        start(ws)
        event = until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary')
        boundary = event['data']
        # Native TTS/output processors may add a short trailing silence.
        assert 2400 <= boundary['samples'] <= 4800 and boundary['text'] == 'Nice game!'
        send(ws, 'voice.playback', {'epoch': boundary['epoch'],
            'consumed_samples': boundary['samples'], 'sample_rate': 24000, 'completed': True})
        until(ws, lambda m: m.get('type') == 'server-response')
    assert len(decisions) == len(bodies) == len(speech) == 1
    body = bodies[0]
    assert body['dafeiyu']['kind'] == 'screen'
    assert body['dafeiyu']['images'][0]['width'] == 40
    assert body['dafeiyu']['max_reply_chars'] == 64
    assert body['dafeiyu']['confirmed_messages'] == []
    assert body['dafeiyu']['request_id'] in store.fixture_generations
    assert played == [{'session_id':'s1','generation_id':bodies[0]['dafeiyu']['request_id'],
                       'text':'Nice game!','interrupted':False}]
    assert store.sessions() == []


def test_ambiguous_purpose_real_decision_reaches_dsh_tts_and_playback_ack(screen_plugin, monkeypatch):
    from server.systemone_providers import ARK_MODEL
    client, store, bodies, played, speech, decisions = screen_plugin
    store.update_settings({'systemone_ark_api_key': 'fixture-only'})
    original_init = SystemOneClient.__init__
    def respond(request):
        decisions.append(True)
        return httpx.Response(200, json={'model': ARK_MODEL, 'answers': {
            'speak_now': {'type': 'noul', 'noul': .9999785551},
            'must_wait': {'type': 'noul', 'noul': .0008040859},
            'intent': {'type': 'choice', 'choice': 'comment', 'confidence': .4709962195,
                'probabilities': {'wait': .00009, 'warn': .00066, 'cheer': .38576, 'comment': .56128, 'empathize': .05221}}}})
    def init(self, settings, **kwargs):
        original_init(self, settings, **{**kwargs, 'transport': httpx.MockTransport(respond)})
    monkeypatch.setattr(SystemOneClient, '__init__', init)
    monkeypatch.setattr(SystemOneClient, 'decide', REAL_SCREEN_DECIDE)
    with connect(client) as ws:
        start(ws)
        status = until(ws, lambda m: m.get('data', {}).get('reason') == 'strong_desire')['data']
        assert status['intent_confidence'] < status['intent_confidence_threshold']
        assert status['non_wait_probability'] > .99
        boundary = until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary')['data']
        send(ws, 'voice.playback', {'epoch': boundary['epoch'], 'consumed_samples': boundary['samples'],
            'sample_rate': 24000, 'completed': True})
        response = until(ws, lambda m: m.get('type') == 'server-response' and m.get('data', {}).get('t') == 'voice.playback')
        assert response['data']['d']['accepted'] is True
        metrics = client.get('/api/voice/metrics/s1', headers={'X-Dafeiyu-Plugin-Token': 'plugin-secret'}).json()
        assert metrics['screen']['decisions'][-1]['intent'] == 'comment'
        assert metrics['counts']['screen_replies'] == 1
    assert len(decisions) == len(bodies) == len(speech) == 1
    assert bodies[0]['dafeiyu']['request_id'] in store.fixture_generations
    assert played == [{'session_id':'s1','generation_id':bodies[0]['dafeiyu']['request_id'],
                       'text':'Nice game!','interrupted':False}]


def test_screen_off_priority_cancels_slow_decision(screen_plugin, monkeypatch):
    client, _, bodies, _, speech, _ = screen_plugin
    entered, cancelled = threading.Event(), threading.Event()
    async def slow(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(SystemOneClient, 'decide', slow)
    with connect(client) as ws:
        stream = start(ws)
        assert entered.wait(5)
        send(ws, 'voice.screen', {'active': False, 'stream_id': stream})
        assert cancelled.wait(3)
        until(ws, lambda m: m.get('data', {}).get('status') == 'inactive')
    assert bodies == speech == []


@pytest.mark.asyncio
async def test_queued_screen_reply_is_rechecked_before_bridge_and_budget_survives_reconnect(tmp_path, monkeypatch):
    monkeypatch.setattr(screen_voice, '_shared_budget', None)
    settings = {**Store(tmp_path).settings(private=True),
        'screen_companion_enabled': True, 'systemone_enabled': True}
    client = type('Client', (), {'source': 'fixture', 'model': 'fixture'})()
    one = ScreenVoice(client, settings, lambda: (), notify=AsyncMock())
    two = ScreenVoice(client, settings, lambda: (), notify=AsyncMock())
    assert one.control.budget is two.control.budget
    one.control.budget.judgments.append(100)
    assert list(two.control.budget.judgments) == [100]
    stream = str(uuid.uuid4())
    await one.control.activate({'active': True, 'stream_id': stream})
    one.control.deadline = float('inf')
    one.push_frame = AsyncMock()
    assert await one.offer_reply(picture(stream), 'comment', one.control.generation, 64)
    gate = ScreenReplyGate(one, lambda: [{'role': 'system', 'content': 'persona'}])
    gate.push_frame = AsyncMock()
    await gate.process_frame(one.push_frame.call_args.args[0], FrameDirection.DOWNSTREAM)
    context = gate.push_frame.call_args.args[0]
    assert isinstance(context, LLMContextFrame)
    prompt = context.context.messages[-1]['content']
    assert '主动陪用户一起看屏幕' in prompt and '不是用户要求描述画面' in prompt
    assert '看法、感受、吐槽或联想' in prompt and '不要先概述画面' in prompt
    assert '不必硬逗' in prompt and '约64字，保持句子完整' in prompt
    # User starts before the queued frame reaches LLM: zero HTTP and no error.
    one.observe(VADUserStartedSpeakingFrame())
    bridge = type('Bridge', (), {'voice_turn': AsyncMock()})()
    projection = ProjectionStore(Store(tmp_path / 'projection'), 's1', [], bridge)
    service = DSHLLMService(projection, 's1', settings)
    service.push_frame, service.push_error = AsyncMock(), AsyncMock()
    await service.process_frame(context, FrameDirection.DOWNSTREAM)
    bridge.voice_turn.assert_not_called()
    service.push_frame.assert_not_called()
    assert not one.pending_reply and not one.screen_reply
    await one.control.close()
    await two.control.close()

def test_native_stop_preserves_admission_and_later_child_reaches_tts(screen_plugin):
    client, store, bodies, played, speech, _ = screen_plugin
    store.fixture_auto_reply = False
    async def wait_for_admission():
        async with asyncio.timeout(5):
            while not bodies:
                await asyncio.sleep(.01)
    async def emit(event):
        await store.fixture_events.put(event)
    def event(ws, typ, generation, text=None):
        payload = {'type': typ, 'generation_id': generation, 'kind': 'normal'}
        if text is not None:
            payload['text'] = text
        ws.portal.call(emit, payload)
    with connect(client) as ws:
        send(ws, 'ready', {})
        until(ws, lambda m: m.get('type') == 'bot-ready')
        question(ws, 'A question')
        ws.portal.call(wait_for_admission)
        assert len(bodies) == 1
        event(ws, 'response.start', 'attempt-random')
        event(ws, 'response.text', 'attempt-random', 'First sentence! Another sentence')
        until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary')
        send(ws, 'voice.stop', {})
        until(ws, lambda m: m.get('type') == 'server-response' and m.get('data', {}).get('t') == 'voice.stop')
        assert not store.fixture_stream_closed.is_set()
        event(ws, 'response.text', 'attempt-random', 'Suppressed sentence!')
        event(ws, 'response.end', 'attempt-random')
        event(ws, 'response.start', 'later-child-attempt')
        event(ws, 'response.text', 'later-child-attempt', 'Child result!')
        event(ws, 'response.end', 'later-child-attempt')
        until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary' and m['data']['text'] == 'Child result!')
        assert len(bodies) == 1
        assert not store.fixture_stream_closed.is_set()
    assert store.fixture_stream_closed.wait(3)
    assert store.fixture_inactive.wait(3)
    assert [state['active'] for state in store.fixture_states] == [True, False]
    assert played == []
    assert any('Child result!' in item['input'] for item in speech)
    assert not any('Suppressed sentence!' in item['input'] for item in speech)


def test_native_stop_before_start_does_not_mute_future_attempt(screen_plugin):
    client, store, bodies, _, speech, _ = screen_plugin
    store.fixture_auto_reply = False
    async def wait_for_admission():
        async with asyncio.timeout(5):
            while not bodies:
                await asyncio.sleep(.01)
    async def emit(event):
        await store.fixture_events.put(event)
    with connect(client) as ws:
        send(ws, 'ready', {})
        until(ws, lambda m: m.get('type') == 'bot-ready')
        question(ws, 'A question')
        ws.portal.call(wait_for_admission)
        send(ws, 'voice.stop', {})
        until(ws, lambda m: m.get('type') == 'server-response' and m.get('data', {}).get('t') == 'voice.stop')
        for typ, text in [('response.start', None), ('response.text', 'Future attempt!'), ('response.end', None)]:
            payload = {'type': typ, 'generation_id': 'new-random-attempt', 'kind': 'normal'}
            if text:
                payload['text'] = text
            ws.portal.call(emit, payload)
        until(ws, lambda m: m.get('data', {}).get('type') == 'voice.playback.boundary' and m['data']['text'] == 'Future attempt!')
        assert len(bodies) == 1
    assert any('Future attempt!' in item['input'] for item in speech)
