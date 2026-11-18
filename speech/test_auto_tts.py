import httpx
import asyncio
import json
import pytest
import websockets
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.tests.utils import run_test
from pipecat.tests.utils import SleepFrame

from speech.auto_tts import AutoTTSSelector, AutoSpeechTTS
from speech.test_pipecat_services import encoded_wav


@pytest.mark.asyncio
async def test_health_selects_once_per_response_and_failure_is_cpu(monkeypatch):
    cpu, gpu = object(), object()
    selector = AutoTTSSelector(cpu, gpu, "http://sidecar/health")
    sent = []
    async def push(frame, direction): sent.append(frame)
    selector.push_frame = push
    results = iter([httpx.Response(200, json={"gpu_eligible": True, "configured": True, "busy": False, "model_name": "IndexTTS-2.5"}), httpx.Response(503)])
    selector._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: next(results)))
    await selector.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await selector.process_frame(LLMTextFrame("你好"), FrameDirection.DOWNSTREAM)
    await selector.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    assert sent[0].service is gpu and sent[3].service is cpu
    await selector.cleanup()


@pytest.mark.asyncio
async def test_native_pipeline_cpu_fallback_uses_sentence_service(monkeypatch):
    native = httpx.AsyncClient
    def handler(request):
        if request.url.path == "/health": return httpx.Response(200, json={"gpu_eligible": False})
        if request.url.path.endswith("/stream"): return httpx.Response(501)
        return httpx.Response(200, content=encoded_wav())
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    tts = AutoSpeechTTS()
    downstream, _ = await run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("你好。"), LLMTextFrame("再见。"), LLMFullResponseEndFrame()])
    assert len([frame for frame in downstream if isinstance(frame, TTSAudioRawFrame)]) == 2


@pytest.mark.asyncio
async def test_gpu_failure_does_not_replay_and_next_turn_uses_cpu(monkeypatch):
    native = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append((request.url.port, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(200, json={"gpu_eligible": True, "configured": True, "busy": False, "model_name": "IndexTTS-2.5"})
        if request.url.port == 8770:
            return httpx.Response(503)
        if request.url.path.endswith("/stream"):
            return httpx.Response(501)
        return httpx.Response(200, content=encoded_wav())
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("hello."), LLMFullResponseEndFrame(), SleepFrame(sleep=.5),
              LLMFullResponseStartFrame(), LLMTextFrame("goodbye."), LLMFullResponseEndFrame()]
    downstream, _ = await asyncio.wait_for(run_test(AutoSpeechTTS(), frames_to_send=frames), 10)
    assert len([f for f in downstream if isinstance(f, TTSAudioRawFrame)]) == 1
    assert calls.count((8770, "/health")) == 1
    assert calls.count((8770, "/v1/audio/speech/stream")) == 1
    assert calls.count((8772, "/v1/audio/speech")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [{"gpu_eligible": True, "configured": False, "busy": False}, {"gpu_eligible": True, "configured": True, "busy": True}, {"gpu_eligible": 1, "configured": True, "busy": False}])
async def test_probe_rejects_unconfigured_busy_or_nonboolean(status):
    cpu, gpu = object(), object()
    selector = AutoTTSSelector(cpu, gpu, "http://sidecar/health")
    sent = []
    async def push(frame, direction): sent.append(frame)
    selector.push_frame = push
    selector._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=status)))
    await selector.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    assert sent[0].service is cpu
    await selector.cleanup()


@pytest.mark.asyncio
async def test_cancelled_probe_does_not_select_late():
    selector = AutoTTSSelector(object(), object(), "http://sidecar/health")
    started, closed = asyncio.Event(), asyncio.Event()
    async def handler(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    selector._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sent = []
    async def push(frame, direction): sent.append(frame)
    selector.push_frame = push
    task = asyncio.create_task(selector.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert closed.is_set() and not sent
    await selector.cleanup()


@pytest.mark.asyncio
async def test_native_pipeline_routes_cpu_gpu_cpu_across_turns(monkeypatch):
    native = httpx.AsyncClient
    states = iter([False, True, False])
    calls = []
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"gpu_eligible": next(states), "configured": True, "busy": False, "model_name": "IndexTTS-2.5"})
        calls.append(request.url.port)
        return httpx.Response(200, content=b"\x02\x00" * 80, headers={
            "X-Audio-Sample-Rate": "24000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    frames = []
    for text in ("one.", "two.", "three."):
        frames += [LLMFullResponseStartFrame(), LLMTextFrame(text), LLMFullResponseEndFrame(), SleepFrame(sleep=.3)]
    downstream, _ = await asyncio.wait_for(run_test(AutoSpeechTTS(), frames_to_send=frames), 10)
    assert len([f for f in downstream if isinstance(f, TTSAudioRawFrame)]) == 3
    assert calls == [8772, 8770, 8772]


@pytest.mark.asyncio
async def test_gpu_error_after_pcm_never_replays_on_cpu(monkeypatch):
    native = httpx.AsyncClient
    requests = []
    class BrokenAudio(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"\x02\x00" * 80
            raise httpx.ReadError("worker failed after first audio")
    def handler(request):
        requests.append((request.url.port, request.url.path))
        if request.url.path == "/health":
            return httpx.Response(200, json={"gpu_eligible": True, "configured": True, "busy": False, "model_name": "IndexTTS-2.5"})
        return httpx.Response(200, stream=BrokenAudio(), headers={
            "X-Audio-Sample-Rate": "24000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    downstream, _ = await asyncio.wait_for(run_test(AutoSpeechTTS(), frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("hello."), LLMFullResponseEndFrame()]), 10)
    assert len([f for f in downstream if isinstance(f, TTSAudioRawFrame)]) == 1
    assert requests == [(8770, "/health"), (8770, "/v1/audio/speech/stream")]
