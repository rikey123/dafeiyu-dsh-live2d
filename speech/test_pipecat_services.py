import asyncio
import io
import json
import time
import wave

import httpx
import pytest
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, ErrorFrame, InputAudioRawFrame, InterimTranscriptionFrame, InterruptionFrame, LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, OutputTransportMessageUrgentFrame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, TranscriptionFrame, UserBackchannelFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.tests.utils import run_test

from speech import pipecat_services as local
from speech.pipecat_turns import ChineseBackchannelFilter, ChineseTurnStartStrategy, is_backchannel


def encoded_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b"\x01\x00" * 1600)
    return output.getvalue()


@pytest.mark.asyncio
async def test_preview_requires_meaningful_intent_before_interruption():
    strategy = ChineseTurnStartStrategy()
    starts = []
    async def report(**kwargs):
        starts.append(kwargs)
    strategy.report_user_turn_started = report
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(VADUserStartedSpeakingFrame())
    await strategy.process_frame(InterimTranscriptionFrame(text="好的", user_id="local", timestamp="now"))
    await strategy.process_frame(InterimTranscriptionFrame(text="啊", user_id="local", timestamp="now"))
    assert not starts
    await strategy.process_frame(InterimTranscriptionFrame(text="等一下", user_id="local", timestamp="now"))
    await strategy.process_frame(InterimTranscriptionFrame(text="等一下", user_id="local", timestamp="now"))
    assert len(starts) == 1
    await strategy.process_frame(TranscriptionFrame(text="等一下，我换个问题", user_id="local", timestamp="now"))
    assert len(starts) == 1


def test_owner_mode_never_opens_unverified_preview():
    service = local.LocalSpeechSTT(owner_only=True, streaming_preview=True)
    assert service.streaming_preview is False


@pytest.mark.asyncio
async def test_online_preview_emits_only_stable_text_and_token_metadata(monkeypatch):
    import websockets
    class Socket:
        count = 0
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def send(self, data):
            assert data == b"\0\0"
        async def recv(self):
            self.count += 1
            if self.count == 1:
                return json.dumps({"type": "ready"})
            return json.dumps({"type": "preview", "text": "等一下", "tokens": ["等"], "timestamps": [0.1], "endpoint": False})
    monkeypatch.setattr(websockets, "connect", lambda *args, **kwargs: Socket())
    service = local.LocalSpeechSTT(streaming_preview=True)
    frames = []
    async def push(frame, *args):
        frames.append(frame)
    service.push_frame = push
    queue = asyncio.Queue()
    task = asyncio.create_task(service._preview(queue))
    await queue.put(b"\0\0")
    await queue.put(b"\0\0")
    for _ in range(50):
        if frames:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(frames) == 1 and isinstance(frames[0], InterimTranscriptionFrame)
    assert frames[0].metadata["online_asr"]["timestamps"] == [0.1]


@pytest.mark.asyncio
async def test_pipeline_preview_does_not_commit_interim_and_final_once(monkeypatch):
    import websockets
    from pipecat.tests.utils import SleepFrame
    class Socket:
        calls = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def send(self, data): pass
        async def recv(self):
            self.calls += 1
            return json.dumps({"type": "ready"} if self.calls == 1 else {"type": "preview", "text": "等一下", "tokens": [], "timestamps": []})
    monkeypatch.setattr(websockets, "connect", lambda *args, **kwargs: Socket())
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"text": "等一下，我换个问题"})), **kwargs))
    stt = local.LocalSpeechSTT(streaming_preview=True, trailing_silence_secs=0)
    context = LLMContext(messages=[])
    user, _ = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(user_turn_strategies=UserTurnStrategies(start=[ChineseTurnStartStrategy()])))
    pcm = b"\0\0" * 1600
    frames = [BotStartedSpeakingFrame(), VADUserStartedSpeakingFrame(), InputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1), InputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1), SleepFrame(sleep=0.3), VADUserStoppedSpeakingFrame(), SleepFrame(sleep=1.0)]
    downstream, upstream = await run_test(Pipeline([stt, ChineseBackchannelFilter(), user]), frames_to_send=frames)
    assert sum(isinstance(frame, InterruptionFrame) for frame in upstream) == 1
    assert sum("等一下，我换个问题" in str(item) for item in context.messages) == 1
    assert all("等一下" not in str(item) or "我换个问题" in str(item) for item in context.messages)


@pytest.mark.asyncio
async def test_stale_preview_after_stop_and_new_start_never_interrupts():
    from pipecat.processors.frame_processor import FrameProcessor
    class Invalidate(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, InterimTranscriptionFrame):
                frame.metadata["_preview_guard"]["active"] = False
            await self.push_frame(frame, direction)
    guard = {"generation": 1, "active": True}
    old = InterimTranscriptionFrame(text="等一下", user_id="local", timestamp="now")
    old.metadata.update({"preview_generation": 1, "_preview_guard": guard})
    context = LLMContext(messages=[])
    user, _ = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(user_turn_strategies=UserTurnStrategies(start=[ChineseTurnStartStrategy()])))
    frames = [BotStartedSpeakingFrame(), VADUserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(), VADUserStartedSpeakingFrame(), old]
    downstream, upstream = await run_test(Pipeline([Invalidate(), ChineseBackchannelFilter(), user]), frames_to_send=frames)
    assert not any(isinstance(frame, InterruptionFrame) for frame in upstream)
    assert not any(isinstance(frame, InterimTranscriptionFrame) for frame in downstream)
    assert not context.messages


@pytest.mark.asyncio
async def test_strategy_rechecks_guard_invalidated_after_filter():
    strategy = ChineseTurnStartStrategy()
    starts = []
    async def report(**kwargs): starts.append(kwargs)
    strategy.report_user_turn_started = report
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(VADUserStartedSpeakingFrame())
    old = InterimTranscriptionFrame(text="等一下", user_id="local", timestamp="now")
    old.metadata.update({"preview_generation": 1, "_preview_guard": {"generation": 1, "active": False}})
    await strategy.process_frame(old)
    assert not starts


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 503])
async def test_stream_http_errors_do_not_retry_as_wav(monkeypatch, status):
    requests = []
    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(status)
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    service = local.LocalSpeechTTS()
    frames = [frame async for frame in service.run_tts("你好", "ctx")]
    assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)
    assert requests == ["/v1/audio/speech/stream"]
    await service.cleanup()


@pytest.mark.asyncio
async def test_stream_interruption_after_pcm_does_not_replay_wav(monkeypatch):
    requests = []
    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"\x01\x00"
            raise httpx.ReadError("stream interrupted")
    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, headers={"X-Audio-Sample-Rate": "16000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"}, stream=Interrupted())
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    service = local.LocalSpeechTTS()
    frames = [frame async for frame in service.run_tts("你好", "ctx")]
    assert isinstance(frames[0], TTSAudioRawFrame) and frames[0].audio == b"\x01\x00"
    assert isinstance(frames[1], ErrorFrame)
    assert frames[1].metadata["tts_context_id"] == "ctx"
    assert requests == ["/v1/audio/speech/stream"]
    await service.cleanup()


@pytest.mark.asyncio
async def test_tts_failure_identifies_each_context(monkeypatch):
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(lambda request: httpx.Response(503)), **kwargs))
    service = local.LocalSpeechTTS()
    for context in ("sentence-1", "sentence-2"):
        frames = [frame async for frame in service.run_tts("你好", context)]
        assert isinstance(frames[0], ErrorFrame)
        assert frames[0].metadata["tts_context_id"] == context
    await service.cleanup()


@pytest.mark.asyncio
async def test_http_speech_adapters_return_standard_pipecat_frames(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/stream"):
            return httpx.Response(501)
        if request.url.path.endswith("transcriptions"):
            assert b"RIFF" in request.content
            return httpx.Response(200, json={"text": "你好"})
        return httpx.Response(200, content=encoded_wav(), headers={"content-type": "audio/wav"})
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    stt = local.LocalSpeechSTT(); stt._sample_rate = 16000
    frames = [frame async for frame in stt.run_stt(b"\0\0" * 1600)]
    assert len(frames) == 1 and isinstance(frames[0], TranscriptionFrame) and frames[0].text == "你好"
    tts = local.LocalSpeechTTS()
    frames = [frame async for frame in tts.run_tts("你好", "ctx")]
    assert isinstance(frames[0], TTSAudioRawFrame) and frames[0].sample_rate == 16000 and len(frames[0].audio) == 3200
    assert len(frames) == 1


@pytest.mark.asyncio
async def test_multi_sentence_uses_single_framework_managed_audio_context(monkeypatch):
    def handler(_request):
        if _request.url.path.endswith("/stream"):
            return httpx.Response(501)
        return httpx.Response(200, content=encoded_wav(), headers={"content-type": "audio/wav"})
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    tts = local.LocalSpeechTTS()
    downstream, _ = await run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("你好。"), LLMTextFrame("再见。"), LLMFullResponseEndFrame()])
    audio = [frame for frame in downstream if isinstance(frame, TTSAudioRawFrame)]
    starts = [frame for frame in downstream if isinstance(frame, TTSStartedFrame)]
    stops = [frame for frame in downstream if isinstance(frame, TTSStoppedFrame)]
    assert len(audio) == 2
    assert len(starts) == len(stops) == 1
    assert starts[0].context_id == stops[0].context_id == audio[0].context_id == audio[1].context_id


@pytest.mark.asyncio
async def test_per_sentence_contexts_flush_immediately_after_audio_and_text(monkeypatch):
    from pipecat.frames.frames import TTSTextFrame
    def handler(request):
        if request.url.path.endswith("/stream"):
            return httpx.Response(501)
        return httpx.Response(200, content=encoded_wav())
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    tts = local.LocalSpeechTTS(reuse_context_id_within_turn=False)
    started = time.monotonic()
    downstream, _ = await run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("你好。"), LLMTextFrame("再见。"), LLMFullResponseEndFrame()])
    assert time.monotonic() - started < 2.5
    ordered = [f for f in downstream if isinstance(f, (TTSAudioRawFrame, TTSTextFrame, TTSStoppedFrame))]
    assert [type(f) for f in ordered] == [TTSAudioRawFrame, TTSTextFrame, TTSStoppedFrame, TTSAudioRawFrame, TTSTextFrame, TTSStoppedFrame]
    assert ordered[0].context_id == ordered[1].context_id == ordered[2].context_id
    assert ordered[3].context_id == ordered[4].context_id == ordered[5].context_id
    assert ordered[0].context_id != ordered[3].context_id


@pytest.mark.asyncio
async def test_real_segmented_stt_pipeline_wraps_pcm_exactly_once(monkeypatch):
    original_pcm = b"\x12\x34\xab\xcd" * 800
    received = []
    def handler(request):
        body = request.content
        marker = body.index(b"RIFF")
        with wave.open(io.BytesIO(body[marker:]), "rb") as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
            received.append(wav.readframes(wav.getnframes()))
        return httpx.Response(200, json={"text": "测试"})
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    stt = local.LocalSpeechSTT(trailing_silence_secs=0)
    await run_test(stt, frames_to_send=[VADUserStartedSpeakingFrame(), InputAudioRawFrame(audio=original_pcm, sample_rate=16000, num_channels=1), VADUserStoppedSpeakingFrame()])
    assert received == [original_pcm]


@pytest.mark.asyncio
async def test_owner_gate_rejects_then_accepts_without_rejected_context(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.content)
        if len(calls) == 1:
            return httpx.Response(200, json={"text": "unsafe text", "speaker": {"accepted": False, "reason": "mismatch", "score": 0.1}})
        return httpx.Response(200, json={"text": "有效发言", "speaker": {"accepted": True}})
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    stt = local.LocalSpeechSTT(owner_only=True, trailing_silence_secs=0)
    context = LLMContext(messages=[])
    user, _ = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(user_turn_strategies=UserTurnStrategies(start=[ChineseTurnStartStrategy()])))
    pipeline = Pipeline([stt, ChineseBackchannelFilter(), user])
    from pipecat.tests.utils import SleepFrame
    pcm = b"\x12\x34" * 1600
    frames = [VADUserStartedSpeakingFrame(), InputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1), VADUserStoppedSpeakingFrame(), SleepFrame(sleep=0.5), VADUserStartedSpeakingFrame(), InputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1), VADUserStoppedSpeakingFrame(), SleepFrame(sleep=1.5)]
    downstream, upstream = await run_test(pipeline, frames_to_send=frames)
    assert len(calls) == 2 and all(b'owner_only' in body and b'true' in body for body in calls)
    notices = [frame.message for frame in downstream if isinstance(frame, OutputTransportMessageUrgentFrame)]
    assert len(notices) == 1 and notices[0]["data"] == {"type": "voice.speaker", "accepted": False, "reason": "mismatch"}
    assert "unsafe text" not in str(context.messages)
    assert sum(isinstance(frame, InterruptionFrame) for frame in upstream) == 1
    assert any("有效发言" in str(item) for item in context.messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"text": "unsafe"}, {"text": "unsafe", "speaker": {"accepted": 1}}, {"text": "unsafe", "speaker": {"accepted": None, "reason": "insufficient_speech"}}])
async def test_owner_gate_fails_closed_on_missing_or_uncertain_decision(monkeypatch, payload):
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), **kwargs))
    stt = local.LocalSpeechSTT(owner_only=True); stt._sample_rate = 16000
    frames = [frame async for frame in stt.run_stt(b"\0\0" * 1600)]
    assert not any(isinstance(frame, TranscriptionFrame) for frame in frames)
    assert isinstance(frames[0], OutputTransportMessageUrgentFrame)


@pytest.mark.asyncio
async def test_cancelled_http_synthesis_closes_without_audio(monkeypatch):
    started, released = asyncio.Event(), asyncio.Event()
    async def handler(_request):
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            released.set()
        return httpx.Response(200, content=encoded_wav())
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    service = local.LocalSpeechTTS()
    async def consume():
        return [frame async for frame in service.run_tts("你好", "ctx")]
    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released.is_set()
    await service.cleanup()


@pytest.mark.asyncio
async def test_http_client_reused_across_requests_and_closed_on_cleanup(monkeypatch):
    instances = []
    native = httpx.AsyncClient
    def create(**kwargs):
        client = native(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=encoded_wav())), **kwargs)
        instances.append(client)
        return client
    monkeypatch.setattr(local.httpx, "AsyncClient", create)
    service = local.LocalSpeechTTS()
    for text in ("你好", "再见"):
        assert [frame async for frame in service.run_tts(text, "ctx")]
    assert len(instances) == 1 and not instances[0].is_closed
    await service.cleanup()
    assert instances[0].is_closed and service._http_client is None


@pytest.mark.asyncio
async def test_chinese_backchannel_policy_uses_pipecat_strategy():
    strategy = ChineseTurnStartStrategy()
    starts = []
    async def report(**kwargs):
        starts.append(kwargs)
    strategy.report_user_turn_started = report
    assert is_backchannel("对，好的。")
    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(VADUserStartedSpeakingFrame())
    await strategy.process_frame(TranscriptionFrame(text="对，好的。", user_id="local", timestamp="now"))
    assert not starts
    await strategy.process_frame(VADUserStartedSpeakingFrame())
    await strategy.process_frame(TranscriptionFrame(text="等一下，我换个问题。", user_id="local", timestamp="now"))
    assert len(starts) == 1
    await strategy.process_frame(BotStoppedSpeakingFrame())
    await strategy.process_frame(TranscriptionFrame(text="好的", user_id="local", timestamp="now"))
    assert len(starts) == 2


@pytest.mark.asyncio
async def test_overlap_backchannel_filtered_before_context_aggregator():
    processor = ChineseBackchannelFilter()
    frames = []
    async def push(frame, direction):
        frames.append(frame)
    processor.push_frame = push
    await processor.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(TranscriptionFrame(text="对，好的", user_id="local", timestamp="now"), FrameDirection.DOWNSTREAM)
    await processor.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await processor.process_frame(TranscriptionFrame(text="等一下，我换个问题", user_id="local", timestamp="now"), FrameDirection.DOWNSTREAM)
    texts = [frame.text for frame in frames if isinstance(frame, TranscriptionFrame)]
    assert texts == ["等一下，我换个问题"]
    backchannels = [frame.text for frame in frames if isinstance(frame, UserBackchannelFrame)]
    assert backchannels == ["对，好的"]
