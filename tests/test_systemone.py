import asyncio
import base64
import io
import json
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from server import main
from server.storage import Store
from server.systemone import (AFFECT_QUESTIONS, TURN_QUESTIONS, Admission, SystemOneClient, TurnDecision)


def response(questions, *, confidence=.9):
    answers = {}
    for key, item in questions.items():
        if item["type"] == "noul":
            answers[key] = {"type": "noul", "noul": .95 if key == "interrupt" else .03}
        else:
            criteria = item["criteria"]
            values = list(criteria) if item["type"] == "choice" else [str(i) for i in range(len(criteria))]
            answers[key] = {"type": item["type"], "confidence": confidence, "probabilities": {v: 1 if i == 0 else 0 for i, v in enumerate(values)}}
            answers[key][item["type"]] = values[0] if item["type"] == "choice" else 0
    return {"model": "clef-omni", "answers": answers, "usage": {"input_tokens": 42, "output_tokens": 0}}


def client(handler, **settings):
    return SystemOneClient({"systemone_api_key": "fixture-key", **settings}, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_audio_contract_bounds_and_fixed_endpoint():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=response(TURN_QUESTIONS))
    service = client(handle)
    try:
        result = await service.turn("等一下", bytes(32000 * 12), [], True)
        assert result.interrupt == .95
        request = seen[0]
        assert str(request.url) == "https://api.tokentosea.com/v1/systemone"
        assert request.headers["Idempotency-Key"]
        payload = json.loads(request.content)
        assert payload["model"] == "clef-omni" and "stream" not in payload
        with wave.open(io.BytesIO(base64.b64decode(payload["audio"][0]["base64"]))) as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()) == (16000, 1, 2, 64000)
        service.audio_enabled = False
        await service.turn("文字", b"\0\0" * 100, [], True)
        assert "audio" not in json.loads(seen[-1].content)
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_status", [202, 409])
async def test_pending_polls_original_key_without_second_post(first_status):
    requests = []
    def handle(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(first_status, json={"status": "upstream_pending"})
        return httpx.Response(200, json={"status": "succeeded", "output": response(AFFECT_QUESTIONS)})
    service = client(handle)
    try:
        assert await service.affect("你好", [])
        assert [r.method for r in requests] == ["POST", "GET"]
        assert requests[1].url.path.endswith(requests[0].headers["Idempotency-Key"])
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_bad_auth_breaker_does_not_leak_provider_body_or_resubmit():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(401, json={"error": "fixture-key private transcript"})
    service = client(handle)
    try:
        for _ in range(4):
            assert await service.affect("私密", []) is None
        assert len(requests) == 3 and service.last_reason == "circuit_open"
        assert Admission.active == 0
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["nan", "unknown", "missing", "model", "sum", "oversize", "nonstring"])
async def test_untrusted_result_is_rejected(damage):
    payload = response(AFFECT_QUESTIONS)
    if damage == "nan": payload["answers"]["energy"]["score"] = float("nan")
    if damage == "unknown": payload["answers"]["gesture"]["choice"] = "execute_command"
    if damage == "nonstring": payload["answers"]["gesture"]["choice"] = {"unexpected": True}
    if damage == "missing": del payload["answers"]["emotion"]
    if damage == "model": payload["model"] = "unknown"
    if damage == "sum": payload["answers"]["gesture"]["probabilities"]["none"] = .2
    raw = json.dumps(payload).encode() if damage != "oversize" else b"x" * 65537
    service = client(lambda _: httpx.Response(200, content=raw))
    try:
        assert await service.affect("你好", []) is None
        assert service.last_reason == "invalid_response"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_timeout_and_cancel_release_admission():
    async def slow(_):
        await asyncio.sleep(10)
        return httpx.Response(200, json=response(AFFECT_QUESTIONS))
    service = client(slow, systemone_timeout_ms=25)
    try:
        assert await service.affect("你好", []) is None
        assert service.last_reason == "timeout" and Admission.active == 0
        task = asyncio.create_task(service.affect("你好", []))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert Admission.active == 0
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_low_confidence_does_not_force_visuals():
    service = client(lambda _: httpx.Response(200, json=response(AFFECT_QUESTIONS, confidence=.2)))
    try:
        assert await service.affect("不开心", []) is None
        assert service.last_reason == "low_confidence"
    finally:
        await service.close()


def test_settings_key_redaction_clear_mode_conflict_and_no_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path))
    with TestClient(main.app) as browser:
        assert browser.get("/api/settings").json()["systemone_enabled"] is False
        assert browser.put("/api/settings", json={"systemone_enabled": True}).status_code == 409
        saved = browser.put("/api/settings", json={"systemone_provider": "tokentosea", "systemone_enabled": True, "systemone_api_key": "private-key"})
        assert saved.status_code == 200 and saved.json()["systemone_api_key_set"]
        assert "private-key" not in saved.text and "systemone_api_key" not in saved.json()
        assert browser.put("/api/settings", json={"systemone_api_key": ""}).status_code == 200
        assert main.store.settings(private=True)["systemone_api_key"] == "private-key"
        assert browser.put("/api/settings", json={"conversation_mode": "moss_live"}).status_code == 409
        assert browser.put("/api/settings", json={"clear_systemone_api_key": True}).status_code == 409
        bad = browser.put("/api/settings", json={"systemone_api_key": "private-key\nsecret"})
        assert bad.status_code == 422 and "private-key" not in bad.text
        assert browser.put("/api/settings", json={"systemone_timeout_ms": 9000}).status_code == 422
        result = browser.put("/api/settings", json={"systemone_enabled": False, "clear_systemone_api_key": True})
        assert result.status_code == 200 and not result.json()["systemone_api_key_set"]
        assert browser.post("/api/systemone/test").status_code == 409


class FakeDecision:
    threshold = .75
    audio_enabled = True
    user_emotion = None
    def __init__(self, result=None, wait=None):
        self.result = result
        self.wait = wait
        self.calls = []
    async def turn(self, *args):
        self.calls.append(args)
        if self.wait: await self.wait.wait()
        return self.result


@pytest.mark.asyncio
async def test_live_audio_interrupt_has_no_fake_transcript_and_late_decision_drops():
    from server.systemone_pipeline import SystemOneInput
    from pipecat.frames.frames import BotStartedSpeakingFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame, InputAudioRawFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from speech.pipecat_turns import ModelInterruptFrame
    model = FakeDecision(TurnDecision(.96, .02, "neutral"))
    gate = SystemOneInput(model, lambda: [])
    emitted = []
    async def push(frame, *_): emitted.append(frame)
    gate.push_frame = push
    async def send(frame): await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
    try:
        await send(BotStartedSpeakingFrame())
        start = VADUserStartedSpeakingFrame(); start.metadata["systemone_segment"] = 1
        await send(start)
        await send(InputAudioRawFrame(audio=bytes(22000), sample_rate=16000, num_channels=1))
        await asyncio.sleep(.01)
        assert any(isinstance(f, ModelInterruptFrame) for f in emitted)
        assert not any(isinstance(f, TranscriptionFrame) for f in emitted)
        model.wait = asyncio.Event()
        await send(start)
        await send(InputAudioRawFrame(audio=bytes(22000), sample_rate=16000, num_channels=1))
        await asyncio.sleep(0)
        await send(VADUserStoppedSpeakingFrame())
        model.wait.set(); await asyncio.sleep(.01)
        assert sum(isinstance(f, ModelInterruptFrame) for f in emitted) == 1
    finally:
        await gate.cleanup()


@pytest.mark.asyncio
async def test_owner_policy_does_not_send_live_audio_and_final_audio_not_forwarded():
    from server.systemone_pipeline import SystemOneInput
    from pipecat.frames.frames import BotStartedSpeakingFrame, VADUserStartedSpeakingFrame, InputAudioRawFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    model = FakeDecision(TurnDecision(.02, .96, "neutral"))
    gate = SystemOneInput(model, lambda: [], owner_only=True)
    emitted = []
    async def push(frame, *_): emitted.append(frame)
    gate.push_frame = push
    async def send(frame): await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
    try:
        await send(BotStartedSpeakingFrame())
        start = VADUserStartedSpeakingFrame()
        await send(start)
        # Native VAD is travelling upstream; STT stamps it AFTER this gate.
        start.metadata["systemone_segment"] = 1
        await send(InputAudioRawFrame(audio=bytes(22000), sample_rate=16000, num_channels=1))
        assert not model.calls
        final = TranscriptionFrame(text="嗯", user_id="local", timestamp="now")
        final.metadata.update(systemone_segment=1, systemone_pcm=bytes(100))
        await send(final)
        assert len(model.calls) == 1 and final.metadata["systemone_backchannel"] is True
        assert "systemone_pcm" not in final.metadata
    finally:
        await gate.cleanup()


@pytest.mark.asyncio
async def test_model_system_frame_starts_native_interruption_without_running_llm():
    from pipecat.frames.frames import BotStartedSpeakingFrame, InterruptionFrame, LLMContextFrame, VADUserStartedSpeakingFrame
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
    from pipecat.turns.user_turn_strategies import UserTurnStrategies
    from pipecat.tests.utils import run_test, SleepFrame
    from speech.pipecat_turns import ChineseTurnStartStrategy, ModelInterruptFrame
    user, _ = LLMContextAggregatorPair(LLMContext(messages=[]), user_params=LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(start=[ChineseTurnStartStrategy()]), empty_user_turn=None))
    down, up = await run_test(user, frames_to_send=[BotStartedSpeakingFrame(), VADUserStartedSpeakingFrame(), ModelInterruptFrame(guard={"active": True}), SleepFrame(sleep=.1)])
    assert any(isinstance(frame, InterruptionFrame) for frame in up)
    assert not any(isinstance(frame, LLMContextFrame) for frame in down)


@pytest.mark.asyncio
async def test_failed_preview_restores_rules_and_does_not_starve_later_interims():
    from server.systemone_pipeline import SystemOneInput
    from pipecat.frames.frames import BotStartedSpeakingFrame, VADUserStartedSpeakingFrame, InterimTranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    model = FakeDecision()
    gate = SystemOneInput(model, lambda: [])
    emitted = []
    async def push(frame, *_): emitted.append(frame)
    gate.push_frame = push
    async def send(frame): await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
    try:
        await send(BotStartedSpeakingFrame())
        start = VADUserStartedSpeakingFrame(); start.metadata["systemone_segment"] = 1
        await send(start)
        for _ in range(3):
            await send(InterimTranscriptionFrame(text="等一下", user_id="local", timestamp="now"))
            await asyncio.sleep(.01)
        interims = [f for f in emitted if isinstance(f, InterimTranscriptionFrame)]
        assert len(model.calls) == 2
        assert len([f for f in interims if "systemone_interrupt" not in f.metadata]) == 3
    finally:
        await gate.cleanup()


@pytest.mark.asyncio
async def test_nonoverlap_emotion_does_not_delay_user_text_and_new_turn_cancels_it():
    from server.systemone_pipeline import SystemOneInput
    from pipecat.frames.frames import VADUserStartedSpeakingFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    model = FakeDecision(TurnDecision(.02, .01, "sad"), wait=asyncio.Event())
    gate = SystemOneInput(model, lambda: [])
    emitted = []
    async def push(frame, *_): emitted.append(frame)
    gate.push_frame = push
    try:
        start = VADUserStartedSpeakingFrame(); start.metadata["systemone_segment"] = 1
        await gate.process_frame(start, FrameDirection.DOWNSTREAM)
        text = TranscriptionFrame(text="我今天不开心", user_id="local", timestamp="now")
        text.metadata["systemone_segment"] = 1
        await asyncio.wait_for(gate.process_frame(text, FrameDirection.DOWNSTREAM), .1)
        assert text in emitted
        await asyncio.sleep(0)
        newer = VADUserStartedSpeakingFrame(); newer.metadata["systemone_segment"] = 2
        await gate.process_frame(newer, FrameDirection.DOWNSTREAM)
        model.wait.set(); await asyncio.sleep(.01)
        assert model.user_emotion is None
    finally:
        await gate.cleanup()


@pytest.mark.asyncio
async def test_outgoing_judgment_does_not_block_tts_and_cancels_on_interrupt():
    from server.systemone_pipeline import SystemOneAffect
    from pipecat.frames.frames import AggregatedTextFrame, InterruptionFrame, OutputTransportMessageUrgentFrame
    from pipecat.tests.utils import run_test, SleepFrame
    class Model:
        last_reason = "ok"
        source = "clef-omni"
        model = "clef-omni"
        closed = False
        async def affect(self, text, *_):
            if text == "不开心": await asyncio.sleep(10)
            return {"emotion": "sad", "gesture": "chest"}
        async def close(self): self.closed = True
    model = Model()
    processor = SystemOneAffect(model, lambda: [])
    first = AggregatedTextFrame(text="不开心", text_type="sentence", context_id="old"); first.will_be_spoken = True
    second = AggregatedTextFrame(text="新的回答", text_type="sentence", context_id="new"); second.will_be_spoken = True
    output, _ = await run_test(processor, frames_to_send=[first, SleepFrame(sleep=.05), InterruptionFrame(), SleepFrame(sleep=.05), second, SleepFrame(sleep=.1)])
    assert first in output
    messages = [f.message["data"] for f in output if isinstance(f, OutputTransportMessageUrgentFrame)]
    assert len(messages) == 1 and messages[0]["epoch"] == "new"
    assert model.closed
