"""Offline protocol tests: no paid connection and no local inference."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from server.storage import Store
from server.moss_live import MossLiveBridge, configuration_status
from server.playback import PlaybackLedger

class Socket:
    def __init__(self, events=()):
        self.sent = []
        self.events = iter(events)
    async def send(self, data):
        self.sent.append(json.loads(data) if isinstance(data, str) else data)
    async def recv(self):
        return json.dumps(next(self.events))

@pytest.fixture
def bridge(tmp_path):
    store = Store(tmp_path)
    session = store.session()
    value = MossLiveBridge(Socket(), store.settings(private=True), store, session, PlaybackLedger(lambda *_: None))
    value.push_frame = AsyncMock()
    value.rtvi = type("RTVI", (), {"interrupt_bot": AsyncMock()})()
    return value

@pytest.mark.asyncio
async def test_handshake_enforces_delegation_and_negotiated_audio(bridge):
    events = [{"action": "session_attached", "data": {"delegation": "client"}},
              {"action": "session.updated", "data": {"error": ""}},
              {"action": "media.configured", "data": {"input_audio": {"format": "pcm16", "sample_rate": 16000},
               "output_audio": {"format": "pcm16", "sample_rate": 24000}, "playback": "client", "error": ""}}]
    bridge.upstream = Socket(events)
    await bridge.initialize()
    assert bridge.upstream.sent[0]["delegation"] == {"type": "client"}
    assert bridge.upstream.sent[-1] == {"action": "mic_state", "enabled": True}
    for patch in ({"playback": "server"}, {"output_audio": {"format": "pcm16", "sample_rate": 48000}}):
        changed = [dict(e, data=dict(e["data"])) for e in events]
        changed[-1]["data"].update(patch)
        bridge.upstream = Socket(changed)
        with pytest.raises(RuntimeError):
            await bridge.initialize()
    bridge.upstream = Socket([{"action": "session_attached", "data": {"delegation": "none"}}])
    with pytest.raises(RuntimeError):
        await bridge.initialize()

async def chunk(bridge, chunk_id="c1", samples=2400):
    await bridge.event("response.audio.context", {"run_id": "r1", "turn_id": "t1", "chunk_id": chunk_id})
    await bridge.audio(bytes(samples * 2))
    reply = bridge.replies[("r1", "t1")]
    epoch = next(reversed(reply.pending))
    # Emulate the downstream transport's actual boundary, separately from generated PCM.
    turn = bridge.ledger.start(epoch)
    turn.samples, turn.boundary = samples, True
    return reply, epoch

def receipt(epoch, samples=2400):
    return {"epoch": epoch, "consumed_samples": samples, "sample_rate": 24000, "completed": True}

@pytest.mark.asyncio
async def test_history_waits_for_real_playback_and_late_final_transcript(bridge):
    reply, epoch = await chunk(bridge)
    await bridge.event("response.audio.done", {"run_id": "r1", "turn_id": "t1"})
    assert not bridge.upstream.sent
    assert not await bridge.acknowledge(receipt(epoch, 2300))
    assert not bridge.store.messages(bridge.session_id)
    assert await bridge.acknowledge(receipt(epoch))
    assert [e["action"] for e in bridge.upstream.sent] == ["playback.chunk.completed", "playback.completed"]
    assert not bridge.store.messages(bridge.session_id)
    await bridge.event("output.transcript.done", {"run_id": "r1", "turn_id": "t1", "text": "Confirmed"})
    assert bridge.store.messages(bridge.session_id)[0]["content"] == "Confirmed"
    assert not await bridge.acknowledge(receipt(epoch))
    await bridge.finish(reply)
    assert len(bridge.store.messages(bridge.session_id)) == 1

@pytest.mark.asyncio
async def test_out_of_order_receipt_does_not_consume_ledger(bridge):
    reply, first = await chunk(bridge)
    _, second = await chunk(bridge, "c2")
    assert not await bridge.acknowledge(receipt(second))
    assert not bridge.ledger.turns[second].confirmed
    assert await bridge.acknowledge(receipt(first))
    assert await bridge.acknowledge(receipt(second))

@pytest.mark.asyncio
async def test_stop_reports_only_unfinished_head_and_never_saves_interrupted_reply(bridge):
    reply, first = await chunk(bridge)
    _, second = await chunk(bridge, "c2")
    assert not await bridge.playback_stopped({"chunks": [{"epoch": first, "consumed_samples": 1200}]})
    assert await bridge.acknowledge(receipt(first))
    await bridge.stop(reply)
    assert await bridge.playback_stopped({"chunks": [{"epoch": second, "consumed_samples": 600}]})
    assert bridge.upstream.sent[-1]["played_audio_ms"] == 25
    assert not await bridge.playback_stopped({"chunks": []})
    await bridge.event("output.transcript.done", {"run_id": "r1", "turn_id": "t1", "text": "Unheard"})
    assert not bridge.store.messages(bridge.session_id)

@pytest.mark.asyncio
async def test_unstarted_audio_stop_acknowledges_zero(bridge):
    reply, epoch = await chunk(bridge)
    await bridge.stop(reply)
    assert await bridge.playback_stopped({"chunks": []})
    assert bridge.upstream.sent[-1]["played_audio_ms"] == 0

@pytest.mark.asyncio
async def test_transcript_missing_ids_requires_unique_active_reply(bridge):
    bridge.reply({"run_id": "r1", "turn_id": "t1"})
    await bridge.event("output.transcript.updated", {"text": "Hello"})
    bridge.reply({"run_id": "r2", "turn_id": "t2"})
    with pytest.raises(RuntimeError):
        await bridge.event("output.transcript.updated", {"text": "Ambiguous"})

@pytest.mark.asyncio
async def test_user_revision_is_scoped_to_session_and_role(bridge):
    await bridge.event("input.transcript.done", {"turn": 0, "text": "First"})
    await bridge.event("input.transcript.revised", {"turn": 0, "text": "Revised"})
    rows = bridge.store.messages(bridge.session_id)
    assert len(rows) == 1 and rows[0]["content"] == "Revised"
    assistant = bridge.store.add_message(bridge.session_id, "assistant", "Safe")
    assert not bridge.store.revise_user_message(assistant, bridge.session_id, "Changed")
    assert not bridge.store.revise_user_message(rows[0]["id"], "other-session", "Changed")

@pytest.mark.asyncio
async def test_delegation_duplicate_and_cancel_never_reissue_request(bridge):
    started = asyncio.Event()
    async def execute(*args):
        started.set()
        await asyncio.Event().wait()
    bridge.execute = AsyncMock(side_effect=execute)
    task = {"delegation": {"id": "d1", "type": "delegation", "target": "client"}, "objective": "Question", "timeout_ms": 5000}
    await bridge.delegate(task)
    await started.wait()
    await bridge.delegate(task)
    assert bridge.execute.call_count == 1
    await bridge.event("session.delegation.cancelled", {"delegation_id": "d1"})
    await asyncio.gather(bridge.delegations["d1"], return_exceptions=True)
    await bridge.delegate(task)
    assert bridge.execute.call_count == 1
    await bridge.cleanup()
    await bridge.cleanup()

@pytest.mark.asyncio
async def test_cleanup_from_reader_never_awaits_itself(bridge):
    async def read():
        bridge.reader = asyncio.current_task()
        await bridge.cleanup()
    await asyncio.wait_for(asyncio.create_task(read()), 2)

def test_keys_redacted_and_status_does_not_claim_remote_readiness(tmp_path):
    store = Store(tmp_path)
    store.update_settings({"moss_live_api_key": "moss-secret", "llm_api_key": "llm-secret"})
    assert "moss_live_api_key" not in store.settings()
    assert store.settings()["moss_live_api_key_set"]
    status = configuration_status(store.settings(private=True))
    assert status["configured"] and not status["ready"] and status["verification"] == "not_probed"
    store.update_settings({"moss_live_api_key": ""})
    assert store.settings()["moss_live_api_key_set"]
    store.update_settings({"clear_moss_live_api_key": True})
    assert not store.settings()["moss_live_api_key_set"]


def test_real_transport_with_fake_upstream_and_browser_receipt(tmp_path, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from pipecat.frames.protobufs import frames_pb2
    from server import main, moss_live

    class Realtime(Socket):
        def __init__(self):
            super().__init__([
                {"action": "session_attached", "data": {"delegation": "client"}},
                {"action": "session.updated", "data": {"error": ""}},
                {"action": "media.configured", "data": {"input_audio": {"format": "pcm16", "sample_rate": 16000},
                 "output_audio": {"format": "pcm16", "sample_rate": 24000}, "playback": "client", "error": ""}}])
            self.queue = asyncio.Queue()
            self.closed = False
            self.produced = False
        async def send(self, data):
            await super().send(data)
            if isinstance(data, bytes) and not self.produced:
                self.produced = True
                for event in [
                    {"action": "input.speech.started"},
                    {"action": "input.transcript.done", "data": {"text": "Test input", "turn": 1}},
                    {"action": "input.speech.stopped"},
                    {"action": "response.audio.started", "data": {"run_id": "r1", "turn_id": "t1"}},
                    {"action": "output.transcript.done", "data": {"run_id": "r1", "turn_id": "t1", "text": "Test answer"}},
                    {"action": "response.audio.context", "data": {"run_id": "r1", "turn_id": "t1", "chunk_id": "c1"}},
                    b"\x10\x00" * 2400,
                    {"action": "response.audio.done", "data": {"run_id": "r1", "turn_id": "t1"}},
                    {"action": "response.ended"},
                ]:
                    await self.queue.put(json.dumps(event) if isinstance(event, dict) else event)
        def __aiter__(self):
            return self
        async def __anext__(self):
            return await asyncio.wait_for(self.queue.get(), 5)
        async def close(self):
            self.closed = True

    upstream = None
    async def connect(url, **kwargs):
        nonlocal upstream
        assert url.startswith("wss://api.mosi.cn/v1/realtime?")
        upstream = Realtime()
        return upstream
    monkeypatch.setattr(moss_live, "connect", connect)
    store = Store(tmp_path)
    store.update_settings({"conversation_mode": "moss_live", "moss_live_api_key": "fake-only", "llm_api_key": "fake-only"})
    monkeypatch.setattr(main, "store", store)
    def message(ws, kind, data):
        frame = frames_pb2.Frame()
        frame.message.data = json.dumps({"label": "rtvi-ai", "type": kind, "id": kind, "data": data})
        ws.send_bytes(frame.SerializeToString())
    with TestClient(main.app) as client:
        session = client.post("/api/sessions").json()["id"]
        with client.websocket_connect(f"/ws/voice?session_id={session}") as ws:
            message(ws, "client-ready", {})
            while True:
                frame = frames_pb2.Frame.FromString(ws.receive_bytes())
                if frame.WhichOneof("frame") == "message" and json.loads(frame.message.data).get("type") == "bot-ready":
                    break
            audio = frames_pb2.Frame()
            audio.audio.audio = b"\x00\x00" * 320
            audio.audio.sample_rate = 16000
            audio.audio.num_channels = 1
            ws.send_bytes(audio.SerializeToString())
            while True:
                frame = frames_pb2.Frame.FromString(ws.receive_bytes())
                if frame.WhichOneof("frame") == "message":
                    data = json.loads(frame.message.data).get("data", {})
                    if data.get("type") == "voice.playback.boundary":
                        break
            assert not any(e.get("action") == "playback.completed" for e in upstream.sent if isinstance(e, dict))
            assert [row["role"] for row in store.messages(session)] == ["user"]
            message(ws, "client-message", {"t": "voice.playback", "d": receipt(data["epoch"], data["samples"])})
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and len(store.messages(session)) < 2:
                time.sleep(.01)
            assert [row["content"] for row in store.messages(session)] == ["Test input", "Test answer"]
        assert session not in main.active_sessions
        deadline = time.monotonic() + 2
        while not upstream.closed and time.monotonic() < deadline:
            time.sleep(.01)
        assert upstream.closed


def test_moss_settings_api_rejects_owner_filter_and_conflicting_key_actions(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server import main
    monkeypatch.setattr(main, "store", Store(tmp_path))
    with TestClient(main.app) as client:
        assert client.put("/api/settings", json={"conversation_mode": "moss_live", "owner_voice_only": True}).status_code == 409
        assert client.put("/api/settings", json={"clear_moss_live_api_key": True, "moss_live_api_key": "secret"}).status_code == 422
        response = client.put("/api/settings", json={"conversation_mode": "moss_live", "moss_live_api_key": "secret"})
        assert response.status_code == 200 and "secret" not in response.text
        assert client.get("/api/voice/config").json()["speech_to_speech_model"] == "moss-live-1.0"


@pytest.mark.asyncio
async def test_stop_clamps_transport_padding_to_original_provider_duration(bridge):
    reply, epoch = await chunk(bridge)
    bridge.ledger.turns[epoch].samples = 2880
    await bridge.stop(reply)
    assert await bridge.playback_stopped({"chunks": [{"epoch": epoch, "consumed_samples": 2600}]})
    assert bridge.upstream.sent[-1]["played_audio_ms"] == 100

@pytest.fixture
def native_moss(tmp_path):
    from types import SimpleNamespace
    from server.dsh import ProjectionStore
    local = Store(tmp_path)
    local.update_settings({'system_prompt': 'LOCAL MUST NOT APPEAR'})
    stream = asyncio.Queue()
    async def events(session, cursor):
        yield 'ready', {'type': 'ready'}
        while True:
            yield await stream.get()
    host = SimpleNamespace(
        voice_state=AsyncMock(return_value={'accepted': True}),
        voice_context=AsyncMock(return_value={'persona': 'NATIVE PERSONA', 'environment': 'LIVE VOICE ENVIRONMENT', 'messages': [
            {'id': 'prior', 'role': 'user', 'content': 'prior native question'},
            {'id': 'answer', 'role': 'assistant', 'content': 'prior native answer'}]}),
        voice_observation=AsyncMock(return_value={'accepted': True}), voice_events=events)
    store = ProjectionStore(local, 'native-session', [], host)
    value = MossLiveBridge(Socket(), local.settings(private=True), store, 'native-session', PlaybackLedger(lambda *_: None))
    value.push_frame = AsyncMock()
    value.rtvi = SimpleNamespace(interrupt_bot=AsyncMock(), send_error=AsyncMock())
    return value, host, stream


@pytest.mark.asyncio
async def test_native_moss_initialize_persona_history_capture_and_cleanup(native_moss):
    bridge, host, stream = native_moss
    bridge.upstream = Socket([
        {'action': 'session_attached', 'data': {'delegation': 'client'}},
        {'action': 'session.updated', 'data': {}},
        {'action': 'media.configured', 'data': {'input_audio': {'format': 'pcm16', 'sample_rate': 16000},
            'output_audio': {'format': 'pcm16', 'sample_rate': 24000}, 'playback': 'client'}},
        {'action': 'session.thinking.appended', 'data': {}}])
    await bridge.initialize()
    assert host.voice_state.await_args_list[0].args == ('native-session', bridge.connection_id, True, False)
    instructions = next(x['session']['instructions'] for x in bridge.upstream.sent if x['action'] == 'session.update')
    assert 'NATIVE PERSONA' in instructions and 'LOCAL MUST NOT APPEAR' not in instructions
    assert 'LIVE VOICE ENVIRONMENT' in instructions
    assert 'DSH' in instructions and 'DeepSeek' not in instructions
    history = next(x['content'] for x in bridge.upstream.sent if x['action'] == 'session.thinking.append')
    assert 'prior native question' in history and 'prior native answer' in history
    assert bridge.upstream.sent[-1] == {'action': 'mic_state', 'enabled': False}
    await bridge.set_capture(True)
    assert bridge.upstream.sent[-1] == {'action': 'mic_state', 'enabled': True}
    assert host.voice_state.await_args_list[-1].args == ('native-session', bridge.connection_id, True, True)
    await bridge.cleanup()
    assert host.voice_state.await_args_list[-1].args == ('native-session', bridge.connection_id, False, False)
    assert bridge.native_listener.done()


@pytest.mark.asyncio
async def test_native_moss_preserves_entire_upstream_persona_and_adds_environment(native_moss):
    bridge, host, _ = native_moss
    persona = (Path(__file__).resolve().parents[1] / "personas/blue-whale/persona.md").read_text(encoding="utf-8")
    host.voice_context.return_value["persona"] = persona
    bridge.upstream = Socket([
        {"action": "session_attached", "data": {"delegation": "client"}},
        {"action": "session.updated", "data": {}},
        {"action": "media.configured", "data": {"input_audio": {"format": "pcm16", "sample_rate": 16000},
            "output_audio": {"format": "pcm16", "sample_rate": 24000}, "playback": "client"}},
        {"action": "session.thinking.appended", "data": {}},
    ])
    await bridge.initialize()
    instructions = next(row["session"]["instructions"] for row in bridge.upstream.sent if row["action"] == "session.update")
    assert persona in instructions
    assert "LIVE VOICE ENVIRONMENT" in instructions
    assert "DeepSeek 的拟人化鲸鱼娘" in instructions
    assert "委派给后台 DSH" in instructions
    await bridge.cleanup()


@pytest.mark.asyncio
async def test_native_observations_revision_and_confirmed_audio_only(native_moss):
    bridge, host, _ = native_moss
    await bridge.event('input.transcript.done', {'turn': 0, 'text': 'first'})
    await bridge.event('input.transcript.done', {'turn': 0, 'text': 'first'})
    await bridge.event('input.transcript.revised', {'turn': 0, 'text': 'corrected'})
    calls = host.voice_observation.await_args_list
    assert calls[0].args[1] == calls[1].args[1] != calls[2].args[1]
    assert [c.args[2:] for c in calls] == [('user', 'first'), ('user', 'first'), ('user', 'corrected')]
    assert calls[2].kwargs == {'revised': True}
    reply, epoch = await chunk(bridge)
    await bridge.event('output.transcript.done', {'run_id': 'r1', 'turn_id': 't1', 'text': 'heard'})
    await bridge.event('response.audio.done', {'run_id': 'r1', 'turn_id': 't1'})
    assert host.voice_observation.await_count == 3
    assert await bridge.acknowledge(receipt(epoch))
    assert host.voice_observation.await_args.args[2:] == ('assistant', 'heard')
    await bridge.finish(reply)
    assert host.voice_observation.await_count == 4
    reply2 = bridge.reply({'run_id': 'r2', 'turn_id': 't2'})
    await bridge.stop(reply2)
    await bridge.event('output.transcript.done', {'run_id': 'r2', 'turn_id': 't2', 'text': 'unheard'})
    assert host.voice_observation.await_count == 4
    await bridge.cleanup()


@pytest.mark.asyncio
async def test_native_events_sync_public_text_and_exclude_delegation(native_moss):
    bridge, host, _ = native_moss
    bridge.delegation_requests['d1'] = 'delegated-request'
    bridge.delegations['d1'] = asyncio.create_task(asyncio.Event().wait())
    for event in [
        {'type': 'conversation.user', 'message_id': 'u1', 'text': 'external', 'request_id': 'editor'},
        {'type': 'conversation.user', 'message_id': 'u1', 'text': 'external', 'request_id': 'editor'},
        {'type': 'conversation.user', 'message_id': 'u2', 'text': 'delegated objective', 'request_id': 'delegated-request'},
        {'type': 'response.start', 'generation_id': 'g1', 'request_id': 'editor'},
        {'type': 'response.text', 'generation_id': 'g1', 'text': 'public '},
        {'type': 'response.text', 'generation_id': 'g1', 'text': 'answer'},
        {'type': 'response.end', 'generation_id': 'g1'},
        {'type': 'response.start', 'generation_id': 'g2', 'request_id': 'delegated-request'},
        {'type': 'response.text', 'generation_id': 'g2', 'text': 'delegation result'},
        {'type': 'response.end', 'generation_id': 'g2'},
        {'type': 'response.text', 'generation_id': 'unknown', 'text': 'secret'},
    ]:
        await bridge.native_event(event)
    assert [e['content'] for e in bridge.upstream.sent] == ['user: external', 'assistant: public answer']


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', [
    {'type': 'response.error', 'code': 'AGENT_ERROR'},
    {'type': 'response.end', 'outcome': 'error'},
])
async def test_native_task_failure_allows_later_public_explanation(native_moss, ending):
    bridge, host, _ = native_moss
    bridge.rtvi = SimpleNamespace(send_error=AsyncMock())
    await bridge.native_event({'type': 'response.start', 'generation_id': 'failed', 'request_id': 'task'})
    await bridge.native_event({**ending, 'generation_id': 'failed'})
    assert 'failed' not in bridge.native_attempts
    await bridge.native_event({'type': 'response.start', 'generation_id': 'parent', 'request_id': 'parent'})
    await bridge.native_event({'type': 'response.text', 'generation_id': 'parent', 'text': '任务失败了，我会继续处理。'})
    await bridge.native_event({'type': 'response.end', 'generation_id': 'parent'})
    assert [event['content'] for event in bridge.upstream.sent] == ['assistant: 任务失败了，我会继续处理。']
    bridge.rtvi.send_error.assert_not_awaited()
    host.voice_observation.assert_not_awaited()
    await bridge.cleanup()


@pytest.mark.asyncio
async def test_native_delegation_agent_error_does_not_create_canned_failure(native_moss, monkeypatch):
    from server import dsh
    bridge, _, _ = native_moss
    async def failed(*_):
        raise dsh.AgentTaskError("DSH agent task failed")
    monkeypatch.setattr(dsh, "completion_text", failed)
    await bridge.execute("d1", "objective", [])
    assert bridge.upstream.sent == []
    bridge.rtvi.send_error.assert_not_awaited()
    await bridge.cleanup()


@pytest.mark.asyncio
async def test_native_voice_stream_gap_reports_transport_error(native_moss):
    bridge, _, _ = native_moss
    await bridge.native_event({'type': 'response.start', 'generation_id': 'g'})
    await bridge.native_event({'type': 'response.error', 'generation_id': 'g', 'code': 'VOICE_STREAM_GAP'})
    bridge.rtvi.send_error.assert_awaited_once_with('DSH voice stream has missing or out-of-order text')
    assert 'g' not in bridge.native_attempts
    await bridge.cleanup()


@pytest.mark.asyncio
async def test_native_delivery_survives_canceled_moss_compat_reader(native_moss):
    bridge, host, _ = native_moss
    bridge.delegation_requests['d1'] = 'delegated-request'
    task = bridge.delegations['d1'] = asyncio.create_task(asyncio.Event().wait())
    await bridge.native_event({'type':'response.start','generation_id':'late','request_id':'delegated-request'})
    await bridge.native_event({'type':'response.text','generation_id':'late','text':'background result'})
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await bridge.native_event({'type':'response.end','generation_id':'late'})
    assert [event['content'] for event in bridge.upstream.sent] == ['assistant: background result']
    host.voice_observation.assert_not_awaited()
    host.voice_observation.assert_not_awaited()
    await bridge.cleanup()

@pytest.mark.asyncio
async def test_native_listener_delivers_later_events_without_reissuing_turn(native_moss):
    bridge, host, stream = native_moss
    bridge.upstream = Socket([
        {'action': 'session_attached', 'data': {'delegation': 'client'}},
        {'action': 'session.updated', 'data': {}},
        {'action': 'media.configured', 'data': {'input_audio': {'format': 'pcm16', 'sample_rate': 16000},
            'output_audio': {'format': 'pcm16', 'sample_rate': 24000}, 'playback': 'client'}},
        {'action': 'session.thinking.appended', 'data': {}}])
    await bridge.initialize()
    for cursor, event in [
        ('1', {'type': 'conversation.user', 'message_id': 'new-user', 'text': 'native input'}),
        ('2', {'type': 'response.start', 'generation_id': 'new-answer', 'request_id': 'editor'}),
        ('3', {'type': 'response.text', 'generation_id': 'new-answer', 'text': 'native output'}),
        ('4', {'type': 'response.end', 'generation_id': 'new-answer'}),
    ]:
        await stream.put((cursor, event))
    async with asyncio.timeout(2):
        while bridge.native_cursor != '4':
            await asyncio.sleep(.01)
    thinking = [e['content'] for e in bridge.upstream.sent if e['action'] == 'session.thinking.append']
    assert thinking[-2:] == ['user: native input', 'assistant: native output']
    host.voice_observation.assert_not_awaited()
    await bridge.cleanup()


@pytest.mark.asyncio
async def test_native_initialize_failure_still_deactivates_and_stops_listener(native_moss):
    bridge, host, _ = native_moss
    bridge.upstream = Socket([{'action': 'session_attached', 'data': {'delegation': 'client'}}])
    host.voice_context.return_value = {'persona': None, 'messages': []}
    with pytest.raises(RuntimeError, match='DSH voice context unavailable'):
        await bridge.initialize()
    await bridge.cleanup()
    assert host.voice_state.await_args_list[-1].args == ('native-session', bridge.connection_id, False, False)
    assert bridge.native_listener.done()
