import json
import time
import asyncio

from fastapi.testclient import TestClient

from server import main
from server.storage import Store


def test_tts_factory_respects_voice_mode(monkeypatch):
    from types import ModuleType
    import sys
    from server import pipecat_voice as voice
    settings = {"tts_engine": "cosyvoice", "speech_base_url": "http://local", "cosyvoice_url": "http://127.0.0.1:8770", "voice": "test"}
    monkeypatch.setattr(voice, "LocalSpeechTTS", lambda **kw: ("gpu" if kw["base_url"].endswith(":8770") else "cpu", kw))
    module = ModuleType("speech.auto_tts")
    module.AutoSpeechTTS = lambda **kw: ("auto", kw)
    monkeypatch.setitem(sys.modules, "speech.auto_tts", module)
    for mode, expected in (("manual", "gpu"), ("cpu", "cpu"), ("gpu", "gpu"), ("auto", "auto")):
        monkeypatch.setenv("DAFEIYU_VOICE_MODE", mode)
        assert voice.create_tts(settings)[0] == expected
    monkeypatch.delenv("DAFEIYU_VOICE_MODE")
    settings["tts_engine"] = "local"
    assert voice.create_tts(settings)[0] == "cpu"


@__import__("pytest").mark.asyncio
async def test_priority_stop_and_ack_bypass_blocked_message_queue():
    from types import SimpleNamespace
    from server.pipecat_voice import PriorityRTVIProcessor

    processor = PriorityRTVIProcessor()
    processor._message_queue = asyncio.Queue()
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async def blocked_http():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    http_task = asyncio.create_task(blocked_http())
    await started.wait()
    received = []
    async def handle(msg_id, data):
        received.append((msg_id, data.t, data.d))
        if data.t == "voice.stop":
            http_task.cancel()
    processor._handle_client_message = handle
    def frame(message_type, identifier, data):
        return SimpleNamespace(message={"label": "rtvi-ai", "type": message_type, "id": identifier, "data": data})
    await processor._handle_transport_message(frame("send-text", "slow", {"content": "hello"}))
    await processor._handle_transport_message(frame("client-message", "ack", {"t": "voice.playback", "d": {"epoch": "x"}}))
    await asyncio.wait_for(processor._handle_transport_message(frame("client-message", "stop", {"t": "voice.stop", "d": {}})), 1)
    await asyncio.wait_for(cancelled.wait(), 1)
    assert [item[1] for item in received] == ["voice.playback", "voice.stop"]
    assert processor._message_queue.qsize() == 1
    await processor._handle_transport_message(frame("send-text", "next", {"content": "next"}))
    assert processor._message_queue.qsize() == 2
    await asyncio.gather(http_task, return_exceptions=True)


@__import__("pytest").mark.asyncio
async def test_priority_stop_rejects_nonempty_payload():
    from types import SimpleNamespace
    from server.pipecat_voice import PriorityRTVIProcessor
    processor = PriorityRTVIProcessor()
    errors = []
    async def error(message):
        errors.append(message)
    processor.send_error = error
    processor._message_queue = asyncio.Queue()
    await processor._handle_transport_message(SimpleNamespace(message={"label": "rtvi-ai", "type": "client-message", "id": "stop", "data": {"t": "voice.stop", "d": {"unexpected": True}}}))
    assert errors and processor._message_queue.empty()


@__import__("pytest").mark.asyncio
async def test_capture_off_is_priority_and_requires_a_strict_boolean():
    from types import SimpleNamespace
    from server.pipecat_voice import PriorityRTVIProcessor
    processor = PriorityRTVIProcessor()
    processor._message_queue = asyncio.Queue()
    received, errors = [], []
    async def handle(identifier, payload): received.append((identifier, payload.d))
    async def error(message): errors.append(message)
    processor._handle_client_message, processor.send_error = handle, error
    def frame(data):
        return SimpleNamespace(message={"label": "rtvi-ai", "type": "client-message", "id": "capture", "data": {"t": "voice.capture", "d": data}})
    await processor._handle_transport_message(frame({"active": False}))
    for data in [{}, {"active": "false"}, {"active": 0}, {"active": False, "extra": 1}]:
        await processor._handle_transport_message(frame(data))
    assert received == [("capture", {"active": False})]
    assert len(errors) == 4 and processor._message_queue.empty()


def test_voice_rtvi_handshake_and_cleanup(tmp_path, monkeypatch):
    from pipecat.frames.protobufs import frames_pb2

    store = Store(tmp_path)
    store.update_settings({"llm_base_url": "http://127.0.0.1:9999/v1", "llm_model": "test"})
    monkeypatch.setattr(main, "store", store)
    with TestClient(main.app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with client.websocket_connect(f"/ws/voice?session_id={session_id}") as ws:
            frame = frames_pb2.Frame()
            frame.message.data = json.dumps({"label": "rtvi-ai", "type": "client-ready", "id": "test", "data": {}})
            ws.send_bytes(frame.SerializeToString())
            while True:
                received = frames_pb2.Frame.FromString(ws.receive_bytes())
                if received.WhichOneof("frame") == "message":
                    message = json.loads(received.message.data)
                    if message.get("type") == "bot-ready":
                        break
            frame = frames_pb2.Frame()
            frame.message.data = json.dumps({"label": "rtvi-ai", "type": "send-text", "id": "text-1", "data": {"content": "测试文本"}})
            ws.send_bytes(frame.SerializeToString())
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not store.messages(session_id):
                time.sleep(.05)
            assert [(row["role"], row["content"]) for row in store.messages(session_id)] == [("user", "测试文本")]
        assert session_id not in main.active_sessions


@__import__("pytest").mark.asyncio
async def test_duck_observer_only_ducks_during_bot_audio():
    from types import SimpleNamespace
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from server.pipecat_voice import DuckObserver
    from server.voice_metrics import SessionMetrics

    events = []
    class RTVI:
        async def send_server_message(self, value):
            events.append(value)

    observer = DuckObserver(SessionMetrics())
    observer.rtvi = RTVI()
    async def send(frame):
        await observer.on_push_frame(SimpleNamespace(frame=frame))
    await send(VADUserStartedSpeakingFrame())
    assert not events
    await send(BotStartedSpeakingFrame())
    await send(VADUserStartedSpeakingFrame())
    await send(VADUserStartedSpeakingFrame())
    await send(VADUserStoppedSpeakingFrame())
    await send(BotStoppedSpeakingFrame())
    assert events == [{"type": "voice.duck", "active": True}, {"type": "voice.duck", "active": False}]


@__import__("pytest").mark.asyncio
async def test_interim_interrupt_without_final_does_not_run_llm():
    from pipecat.frames.frames import BotStartedSpeakingFrame, InterimTranscriptionFrame, InterruptionFrame, LLMContextFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
    from pipecat.tests.utils import SleepFrame, run_test
    from pipecat.turns.user_turn_strategies import UserTurnStrategies
    from speech.pipecat_turns import ChineseTurnStartStrategy

    context = LLMContext(messages=[])
    user, _ = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(start=[ChineseTurnStartStrategy()]),
        user_turn_stop_timeout=.2, empty_user_turn=None))
    downstream, upstream = await run_test(user, frames_to_send=[
        BotStartedSpeakingFrame(), VADUserStartedSpeakingFrame(),
        InterimTranscriptionFrame(text="等一下", user_id="local", timestamp="now"),
        VADUserStoppedSpeakingFrame(), SleepFrame(sleep=1)])
    assert any(isinstance(frame, InterruptionFrame) for frame in upstream)
    assert not any(isinstance(frame, LLMContextFrame) for frame in downstream)
    assert context.messages == []
