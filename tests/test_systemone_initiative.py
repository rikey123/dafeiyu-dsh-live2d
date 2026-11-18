"""Local protocol/lifecycle fixtures, not live-model or microphone benchmarks."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import (BotStartedSpeakingFrame, InputAudioRawFrame,
    CancelFrame, EndFrame, InterruptionFrame, InterimTranscriptionFrame, LLMContextFrame, LLMFullResponseEndFrame,
    LLMTextFrame, TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.frameworks.rtvi.frames import RTVISendTextFrame

from server import main
from server.storage import Store
from server.systemone import INITIATIVE_QUESTIONS, InitiativeDecision, SystemOneClient
from server.systemone_initiative import (InitiativeReplyGate, InitiativeRequestFrame,
    InitiativeSpeechLimit, SystemOneInitiative)
from server.voice_metrics import SessionMetrics

SETTINGS = {"systemone_enabled": True, "systemone_initiative_enabled": True, "conversation_mode": "duplex"}
STRONG = InitiativeDecision(.98, .01, "empathize")


class DecisionFixture:
    source = "doubao-systemone"
    model = "doubao-seed-2-1-lite-260915"
    last_reason = "ok"
    def __init__(self, result=STRONG):
        self.result, self.calls = result, []
        self.metrics = SessionMetrics()
    async def initiative(self, *args):
        self.calls.append(args)
        return self.result


def fixture(*, result=STRONG, settings=None, clock=lambda: 100):
    model = DecisionFixture(result)
    snapshots = []
    async def transcribe(pcm):
        snapshots.append(pcm)
        return "这件事情让我很难过，我还想跟你讲讲"
    controller = SystemOneInitiative(model, lambda: [], transcribe, {**SETTINGS, **(settings or {})}, clock=clock)
    controller.capture_active = True  # Explicit synthetic capture; no microphone.
    output = []
    async def push(frame, *_): output.append(frame)
    controller.push_frame = push
    return controller, model, snapshots, output


async def send(processor, frame):
    await processor.process_frame(frame, FrameDirection.DOWNSTREAM)


async def audio(processor, samples=48000):
    await send(processor, InputAudioRawFrame(audio=bytes(samples * 2), sample_rate=16000, num_channels=1))
    if processor.task:
        await asyncio.gather(processor.task, return_exceptions=True)
    await asyncio.sleep(0)  # run the task-set discard callback


@pytest.mark.asyncio
async def test_initiative_has_distinct_questions_and_strict_ark_contract():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"model": "doubao-seed-2-1-lite-260915", "answers": {
            "speak_now": {"type": "noul", "noul": .98}, "must_wait": {"type": "noul", "noul": .01},
            "intent": {"type": "choice", "choice": "empathize", "confidence": .92,
                "probabilities": {key: 1 if key == "empathize" else 0 for key in INITIATIVE_QUESTIONS["intent"]["criteria"]}},
        }})
    client = SystemOneClient({"systemone_provider": "ark", "systemone_ark_api_key": "fixture-only"}, transport=httpx.MockTransport(handler))
    try:
        assert await client.initiative("我很难过", bytes(16000), []) == STRONG
        body = json.loads(requests[0].content)
        assert set(body["questions"]) == {"speak_now", "must_wait", "intent"}
        assert body["state"][0]["text"]["user_still_speaking"] is True
        assert requests[0].headers["ark-beta-systemone-api"] == "true"
        client.audio_enabled = False
        await client.initiative("我很难过", bytes(16000), [])
        assert isinstance(json.loads(requests[-1].content)["state"], dict)
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [
    {"systemone_initiative_enabled": False}, {"systemone_enabled": False},
    {"owner_voice_only": True}, {"conversation_mode": "pipeline"}, {"conversation_mode": "moss_live"},
])
async def test_disabled_and_incompatible_modes_never_probe(settings):
    control, model, snapshots, output = fixture(settings=settings)
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control, 160000)
        assert not model.calls and not snapshots
        assert not any(isinstance(frame, InitiativeRequestFrame) for frame in output)
    finally:
        await control.cleanup()


@pytest.mark.asyncio
async def test_strong_desire_is_transient_context_not_a_fake_final_or_history_mutation():
    now = [100]
    control, model, snapshots, output = fixture(clock=lambda: now[0])
    messages = [{"role": "system", "content": "你是大肥鱼"}]
    limit = InitiativeSpeechLimit()
    gate = InitiativeReplyGate(control, lambda: messages, limit)
    generated = []
    async def push(frame, *_): generated.append(frame)
    gate.push_frame = push
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control, 47999)
        assert not snapshots
        await audio(control, 1)
        requests = [frame for frame in output if isinstance(frame, InitiativeRequestFrame)]
        assert len(requests) == 1 and not any(isinstance(frame, TranscriptionFrame) for frame in output)
        assert len(model.calls) == 1
        await send(gate, requests[0])
        assert len(generated) == 1 and isinstance(generated[0], LLMContextFrame)
        assert generated[0].context.messages[-1]["content"] == model.calls[0][0]
        assert len(messages) == 1 and limit.armed
        assert control.current.used
        await send(gate, requests[0])
        assert len(generated) == 1  # No duplicate reply to the same decision.
        control.pending_generation = False
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert len(model.calls) == 1  # Global cooldown, even across utterances.
        now[0] += 21
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert len(model.calls) == 2
    finally:
        await control.cleanup()
        await gate.cleanup()
        await limit.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, InitiativeDecision(.89, .01, "empathize"),
    InitiativeDecision(.99, .21, "clarify"), InitiativeDecision(.99, .01, "wait"), InitiativeDecision(.99, .01, None)])
async def test_unavailable_low_desire_wait_and_uncertain_intent_only_listen(result):
    control, _, _, output = fixture(result=result)
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert not any(isinstance(frame, InitiativeRequestFrame) for frame in output)
    finally:
        await control.cleanup()


@pytest.mark.asyncio
async def test_three_bounded_probes_per_utterance_and_current_audio_only():
    control, model, snapshots, _ = fixture(result=InitiativeDecision(.2, .9, "wait"))
    try:
        await send(control, VADUserStartedSpeakingFrame())
        for _ in range(8):
            await audio(control)
        assert len(model.calls) == len(snapshots) == 3
        assert model.metrics.snapshot()["counts"]["systemone_initiative_probes"] == 3
        assert model.metrics.snapshot()["counts"]["systemone_initiative_wait"] == 3
        assert max(map(len, snapshots)) <= 128000 and len(control.current.pcm) <= 128000
    finally:
        await control.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold,expected", [(.1, False), (.2, False), (.21, True), (.4, True)])
async def test_configured_wait_threshold_changes_decision_including_boundary(threshold, expected):
    control, _, _, output = fixture(result=InitiativeDecision(.98, .21, "clarify"),
        settings={"systemone_initiative_wait_threshold": threshold})
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert any(isinstance(frame, InitiativeRequestFrame) for frame in output) is expected
        if not expected:
            diagnostic = next(frame for frame in output if hasattr(frame, "message"))
            assert diagnostic.message["data"]["reason"] == "respect_floor"
    finally:
        await control.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("max_probes", [1, 5])
async def test_configured_initial_listen_probe_interval_and_attempt_budget(max_probes):
    control, model, _, _ = fixture(result=InitiativeDecision(.1, .9, "wait"), settings={
        "systemone_initiative_min_speech_ms": 2000, "systemone_initiative_probe_interval_ms": 1500,
        "systemone_initiative_max_probes": max_probes})
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control, 31999)
        assert not model.calls
        await audio(control, 1)
        assert len(model.calls) == 1
        for attempt in range(1, max_probes):
            await audio(control, 23999)
            assert len(model.calls) == attempt
            await audio(control, 1)
            assert len(model.calls) == attempt + 1
        await audio(control, 160000)
        assert len(model.calls) == max_probes
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control, 32000)
        assert len(model.calls) == max_probes + 1
    finally:
        await control.cleanup()


@pytest.mark.asyncio
async def test_configured_desire_and_cooldown_apply_across_utterances():
    now = [100]
    control, model, _, output = fixture(result=InitiativeDecision(.93, .01, "empathize"),
        settings={"systemone_initiative_threshold": .94, "systemone_initiative_cooldown_s": 45}, clock=lambda: now[0])
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert not any(isinstance(frame, InitiativeRequestFrame) for frame in output)
        model.result = STRONG
        control.last_spoke = 100
        now[0] += 44
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert len(model.calls) == 1
        now[0] += 1
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert len(model.calls) == 2
        assert any(isinstance(frame, InitiativeRequestFrame) for frame in output)
    finally:
        await control.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("max_chars", [8, 24, 80])
async def test_configured_reply_length_guides_prompt_without_truncating_text(max_chars):
    control, _, _, output = fixture(settings={"systemone_initiative_max_reply_chars": max_chars})
    limiter = InitiativeSpeechLimit(max_chars=control.max_reply_chars)
    gate = InitiativeReplyGate(control, lambda: [], limiter)
    generated, spoken = [], []
    async def prompt(frame, *_): generated.append(frame)
    async def text(frame, *_): spoken.append(frame)
    gate.push_frame, limiter.push_frame = prompt, text
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        request = next(frame for frame in output if isinstance(frame, InitiativeRequestFrame))
        await send(gate, request)
        assert f"约{max_chars}字，并保持意思完整" in generated[0].context.messages[0]["content"]
        for _ in range(2):
            limiter.arm()
            spoken.clear()
            for chunk in ["长" * 5, "长" * 100, "还要说"]:
                await send(limiter, LLMTextFrame(chunk))
            assert "".join(frame.text for frame in spoken) == "长" * 105 + "还要说"
        await send(limiter, LLMFullResponseEndFrame())
        spoken.clear()
        await send(limiter, LLMTextFrame("普通回答" * 30))
        assert spoken[0].text == "普通回答" * 30
    finally:
        await control.cleanup(); await gate.cleanup(); await limiter.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidator", [VADUserStoppedSpeakingFrame, VADUserStartedSpeakingFrame, InterruptionFrame,
    lambda: TranscriptionFrame(text="完整发言", user_id="local", timestamp="now"),
    lambda: RTVISendTextFrame(text="改成文字", msg_id="fixture-text")])
async def test_late_decision_cannot_speak_after_stop_new_turn_or_text(invalidator):
    control, model, _, output = fixture()
    pending = asyncio.Event()
    async def late(*_):
        pending.set()
        try: await asyncio.Event().wait()
        except asyncio.CancelledError: return STRONG  # Simulate a late remote completion.
    model.initiative = late
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await send(control, InputAudioRawFrame(audio=bytes(96000), sample_rate=16000, num_channels=1))
        await pending.wait()
        await send(control, invalidator())
        await asyncio.gather(control.task, return_exceptions=True)
        assert not any(isinstance(frame, InitiativeRequestFrame) for frame in output)
    finally:
        await control.cleanup()


@pytest.mark.asyncio
async def test_respects_explicit_request_and_reuses_only_valid_online_preview():
    control, model, snapshots, output = fixture()
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await send(control, InterimTranscriptionFrame(text="先听我说完，不要打断我", user_id="local", timestamp="now"))
        await audio(control)
        assert not model.calls and not snapshots
        await send(control, VADUserStartedSpeakingFrame())
        stale = InterimTranscriptionFrame(text="不要打断我", user_id="local", timestamp="now")
        stale.metadata.update(_preview_guard={"active": False, "generation": 1}, preview_generation=1)
        await send(control, stale)
        preview = InterimTranscriptionFrame(text="我今天真的有点难过", user_id="local", timestamp="now")
        await send(control, preview)
        await audio(control)
        assert not snapshots and model.calls[0][0] == preview.text
        assert any(isinstance(frame, InitiativeRequestFrame) for frame in output)
    finally:
        await control.cleanup()


@pytest.mark.asyncio
async def test_busy_assistant_and_expired_queued_decision_cannot_start_interjection():
    now = [100]
    control, model, _, output = fixture(clock=lambda: now[0])
    limiter = InitiativeSpeechLimit()
    gate = InitiativeReplyGate(control, lambda: [], limiter)
    generated = []
    async def push(frame, *_): generated.append(frame)
    gate.push_frame = push
    try:
        control.observe(BotStartedSpeakingFrame())
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert not model.calls
        control.bot_speaking = False
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        request = next(frame for frame in output if isinstance(frame, InitiativeRequestFrame))
        now[0] += 5
        await send(gate, request)
        assert not generated
        now[0] -= 5
        control.playback_busy = lambda: True
        await send(gate, request)
        assert not generated
    finally:
        await control.cleanup(); await gate.cleanup(); await limiter.cleanup()


@pytest.mark.asyncio
async def test_stopped_user_cancels_unheard_speculative_generation_but_forwards_real_final():
    control, _, _, output = fixture()
    interruptions = []
    async def interrupt(): interruptions.append(True)
    control.broadcast_interruption = interrupt
    try:
        await send(control, VADUserStartedSpeakingFrame())
        control.initiative_reply = control.pending_generation = True
        await send(control, VADUserStoppedSpeakingFrame())
        final = TranscriptionFrame(text="这是完整发言，不能被短快照替代", user_id="local", timestamp="now")
        await send(control, final)
        assert interruptions == [True] and final in output
    finally:
        await control.cleanup()


@pytest.mark.asyncio
async def test_stop_during_acceptance_diagnostic_cannot_resurrect_a_queued_reply():
    control, _, _, output = fixture()
    limiter = InitiativeSpeechLimit()
    gate = InitiativeReplyGate(control, lambda: [], limiter)
    generated = []
    async def push(frame, *_): generated.append(frame)
    gate.push_frame = push
    try:
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        request = next(frame for frame in output if isinstance(frame, InitiativeRequestFrame))
        async def notify(*_): await control.set_capture_active(False)
        control.notify = notify
        async def interrupt(): control.observe(InterruptionFrame())
        control.broadcast_interruption = interrupt
        await send(gate, request)
        assert not generated and not control.pending_generation and not limiter.armed
    finally:
        await control.cleanup(); await gate.cleanup(); await limiter.cleanup()


@pytest.mark.asyncio
async def test_initiative_text_is_unchanged_and_lifecycle_disarms():
    limiter = InitiativeSpeechLimit()
    output = []
    async def push(frame, *_): output.append(frame)
    limiter.push_frame = push
    try:
        limiter.arm()
        parts = ["First", " sentence. Another sentence!", "long" * 100]
        for part in parts:
            await send(limiter, LLMTextFrame(part))
        assert [frame.text for frame in output] == parts
        for ending in (LLMFullResponseEndFrame, InterruptionFrame, EndFrame, CancelFrame):
            limiter.arm()
            await send(limiter, ending())
            assert not limiter.armed
        output.clear()
        await send(limiter, LLMTextFrame("Normal reply. Complete."))
        assert output[0].text == "Normal reply. Complete."
    finally:
        await limiter.cleanup()


@pytest.mark.asyncio
async def test_snapshot_uses_local_asr_and_never_emits_a_transcript():
    from speech.pipecat_services import LocalSpeechSTT
    stt = LocalSpeechSTT()
    requests, output = [], []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"text": "这是一个尚未说完的片段"})
    stt._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async def push(frame, *_): output.append(frame)
    stt.push_frame = push
    try:
        assert await stt.transcribe_snapshot(bytes(200000)) == "这是一个尚未说完的片段"
        assert str(requests[0].url) == "http://127.0.0.1:8766/v1/audio/transcriptions"
        assert not output
        stt.owner_only = True
        assert await stt.transcribe_snapshot(bytes(1000)) is None
        assert len(requests) == 1
    finally:
        await stt.cleanup()


@pytest.mark.asyncio
async def test_loopback_speech_bypasses_system_proxy_and_remote_api_retains_it(monkeypatch):
    from speech.pipecat_services import LocalSpeechSTT, LocalSpeechTTS
    from speech.api_tts import APISpeechTTS
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    services = [LocalSpeechSTT(), LocalSpeechTTS(), APISpeechTTS(base_url="http://127.0.0.1:8874/v1", api_key="fixture", model="test", voice="test")]
    remote = APISpeechTTS(base_url="https://example.invalid/v1", api_key="fixture", model="test", voice="test")
    try:
        for service in services:
            client = service._sdk()._client if isinstance(service, APISpeechTTS) else service._client()
            assert client._trust_env is False
        assert remote._sdk()._client._trust_env is True
    finally:
        await asyncio.gather(*(service.cleanup() for service in [*services, remote]))


@pytest.mark.asyncio
async def test_capture_off_invalidates_decisions_without_opening_a_new_turn():
    control, model, _, output = fixture()
    try:
        await control.set_capture_active(False)
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        assert not model.calls
        await control.set_capture_active(True)
        await send(control, VADUserStartedSpeakingFrame())
        await audio(control)
        request = next(frame for frame in output if isinstance(frame, InitiativeRequestFrame))
        await control.set_capture_active(False)
        assert not control.valid(request.speech, request.deadline)
        assert not any(isinstance(frame, TranscriptionFrame) for frame in output)
    finally:
        await control.cleanup()


def test_settings_defaults_validation_and_voice_reconnect(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)
    reconnects = []
    async def close(): reconnects.append(True)
    monkeypatch.setattr(main, "close_old_voice_sessions", close)
    try:
        with TestClient(main.app) as browser:
            defaults = browser.get("/api/settings").json()
            assert not defaults["systemone_initiative_enabled"] and defaults["systemone_initiative_threshold"] == .9
            patch = {"systemone_initiative_enabled": True, "systemone_initiative_threshold": .95,
                     "systemone_initiative_cooldown_s": 30, "systemone_initiative_min_speech_ms": 4000,
                     "systemone_initiative_wait_threshold": .1, "systemone_initiative_max_reply_chars": 24,
                     "systemone_initiative_probe_interval_ms": 2000, "systemone_initiative_max_probes": 5}
            saved = browser.put("/api/settings", json=patch)
            assert saved.status_code == 200 and all(saved.json()[key] == value for key, value in patch.items())
            assert all(browser.get("/api/settings").json()[key] == value for key, value in patch.items())
            assert len(reconnects) == 1
            assert browser.put("/api/settings", json=patch).status_code == 200
            assert len(reconnects) == 1  # Saving unchanged values needn't interrupt voice.
            for invalid in [{"systemone_initiative_threshold": .5}, {"systemone_initiative_min_speech_ms": 100},
                            {"systemone_initiative_cooldown_s": 0}, {"systemone_initiative_threshold": float("inf")}]:
                if any(value == float("inf") for value in invalid.values()):
                    response = browser.put("/api/settings", content='{"systemone_initiative_threshold":Infinity}', headers={"content-type": "application/json"})
                else:
                    response = browser.put("/api/settings", json=invalid)
                assert response.status_code == 422
            bounds = {"systemone_initiative_wait_threshold": (0, .5),
                "systemone_initiative_max_reply_chars": (8, 80),
                "systemone_initiative_probe_interval_ms": (1500, 10000),
                "systemone_initiative_max_probes": (1, 6)}
            for key, (low, high) in bounds.items():
                for value in (low - 1, high + 1, "not-a-number"):
                    assert browser.put("/api/settings", json={key: value}).status_code == 422
                if key != "systemone_initiative_wait_threshold":
                    assert browser.put("/api/settings", json={key: low + .5}).status_code == 422
                assert browser.put("/api/settings", content=json.dumps({key: float("inf")}),
                    headers={"content-type": "application/json"}).status_code == 422
            assert all(browser.get("/api/settings").json()[key] == value for key, value in patch.items())
            assert len(reconnects) == 1
            # Each newly exposed field must independently reconnect, not merely persist.
            for key, (low, high) in bounds.items():
                for value in (low, high):
                    previous = len(reconnects)
                    response = browser.put("/api/settings", json={key: value})
                    assert response.status_code == 200 and response.json()[key] == value
                    assert len(reconnects) == previous + 1
    finally:
        store.db.close()


def test_older_saved_settings_receive_new_defaults_without_losing_preferences(tmp_path):
    store = Store(tmp_path)
    try:
        store.update_settings({"systemone_initiative_threshold": .93, "systemone_initiative_enabled": True})
    finally:
        store.db.close()
    reopened = Store(tmp_path)
    try:
        values = reopened.settings()
        assert values["systemone_initiative_threshold"] == .93 and values["systemone_initiative_enabled"]
        assert values["systemone_initiative_max_reply_chars"] == 48
        assert values["systemone_initiative_wait_threshold"] == .2
        assert values["systemone_initiative_probe_interval_ms"] == 3000
        assert values["systemone_initiative_max_probes"] == 3
    finally:
        reopened.db.close()


@pytest.mark.asyncio
async def test_real_pipecat_turn_lifecycle_keeps_full_user_message_and_runs_short_then_normal_reply():
    """Real framework scheduling; ASR/decision/LLM remain explicit local fixtures."""
    from pipecat.frames.frames import LLMFullResponseStartFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
    from pipecat.tests.utils import run_test, SleepFrame
    from pipecat.turns.user_turn_strategies import UserTurnStrategies
    from speech.pipecat_turns import ChineseTurnStartStrategy
    from server.pipecat_voice import DuckObserver
    from server.playback import ConfirmedContext, PlaybackLedger

    model = DecisionFixture()
    partial = "这件事让我很难过，我还想跟你说说"
    complete = partial + "，但后来我的朋友来安慰我，现在已经好多了。"
    async def transcribe(_): return partial
    control = SystemOneInitiative(model, lambda: [], transcribe, SETTINGS)
    control.capture_active = True
    context = LLMContext(messages=[])
    user, _ = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(start=[ChineseTurnStartStrategy()]),
        user_turn_stop_timeout=.2, empty_user_turn=None))
    history, prompts = [], []
    @user.event_handler("on_user_turn_message_added")
    async def save(_aggregator, message): history.append({"role": "user", "content": message.content})

    class LLMFixture(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, LLMContextFrame):
                prompts.append(frame.context.messages)
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(LLMTextFrame("我明白你的难过。多余的长篇回应。" if len(prompts) == 1 else "这是完整回答。不能被主动接话的长度限制截断。"))
                await self.push_frame(LLMFullResponseEndFrame())
            else:
                await self.push_frame(frame, direction)

    limiter = InitiativeSpeechLimit()
    ledger = PlaybackLedger(lambda *_: None)
    pipeline = Pipeline([control, user, ConfirmedContext(ledger, context.messages, snapshot=lambda: history),
        InitiativeReplyGate(control, lambda: history, limiter), LLMFixture(), limiter])
    duck = DuckObserver(model.metrics, initiative=control)
    output, _ = await run_test(pipeline, observers=[duck], frames_to_send=[
        VADUserStartedSpeakingFrame(), InputAudioRawFrame(audio=bytes(96000), sample_rate=16000, num_channels=1),
        SleepFrame(sleep=.25), VADUserStoppedSpeakingFrame(),
        TranscriptionFrame(text=complete, user_id="local", timestamp="now", finalized=True), SleepFrame(sleep=1.1)])
    assert len(prompts) == 2
    assert prompts[0][-1]["content"] == partial
    assert history == [{"role": "user", "content": complete}]
    assert prompts[1] == history
    text = [frame.text for frame in output if isinstance(frame, LLMTextFrame)]
    assert text == ["我明白你的难过。多余的长篇回应。", "这是完整回答。不能被主动接话的长度限制截断。"]
