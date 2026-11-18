import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame

from speech.api_tts import APISpeechTTS


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, block=False):
        self.chunks = chunks
        self.block = block
        self.started = asyncio.Event()
        self.closed = False
    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.block:
            self.started.set()
            await asyncio.Event().wait()
    async def aclose(self):
        self.closed = True


def make_service(handler, **kwargs):
    service = APISpeechTTS(base_url="https://tts.test/v1", api_key="private-secret", model="custom-model", voice="custom-voice", **kwargs)
    service._api_client = AsyncOpenAI(api_key="private-secret", base_url="https://tts.test/v1", max_retries=0,
                                    http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False))
    return service


@pytest.mark.asyncio
async def test_real_sdk_streams_pcm_with_context_and_custom_provider_voice():
    requests = []
    stream = Stream([b"\x01", b"\x02\x03", b"\x04"])
    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, stream=stream)
    service = make_service(handler, speed=1.25)
    frames = [frame async for frame in service.run_tts("你好", "ctx")]
    assert frames and all(isinstance(frame, TTSAudioRawFrame) for frame in frames)
    assert b"".join(frame.audio for frame in frames) == b"\x01\x02\x03\x04"
    assert all(frame.sample_rate == 24000 and frame.num_channels == 1 and frame.context_id == "ctx" for frame in frames)
    assert requests[0].url.path == "/v1/audio/speech"
    assert json.loads(requests[0].content) == {"input": "你好", "model": "custom-model", "voice": "custom-voice", "response_format": "pcm", "speed": 1.25}
    assert stream.closed
    await service.cleanup()
    assert service._api_client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 404, 429, 500])
async def test_api_failures_are_sanitized_and_never_retried(code):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(code, json={"error": {"message": "private-secret provider response"}})
    service = make_service(handler)
    frames = [frame async for frame in service.run_tts("text", "ctx")]
    assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)
    assert str(code) in frames[0].error and "private-secret" not in frames[0].error
    assert frames[0].metadata["tts_context_id"] == "ctx"
    assert len(requests) == 1
    await service.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type,pcm", [("audio/wav", b"RIFF"), ("application/json", b"{}"), ("audio/l16", b"ab"), ("audio/pcm", b"a"), ("audio/pcm", b""), ("audio/pcm", b"RIFFabcdefgh")])
async def test_invalid_or_empty_audio_never_plays(content_type, pcm):
    service = make_service(lambda request: httpx.Response(200, headers={"content-type": content_type}, stream=Stream([pcm])))
    frames = [frame async for frame in service.run_tts("text", "ctx")]
    assert frames and all(isinstance(frame, ErrorFrame) for frame in frames)
    await service.cleanup()


@pytest.mark.asyncio
async def test_interruption_closes_http_stream_without_error_or_retry():
    stream = Stream([], block=True)
    service = make_service(lambda request: httpx.Response(200, headers={"content-type": "audio/pcm"}, stream=stream))
    async def consume():
        return [frame async for frame in service.run_tts("text", "ctx")]
    task = asyncio.create_task(consume())
    await asyncio.wait_for(stream.started.wait(), 2)
    await service.on_audio_context_interrupted("ctx")
    assert await asyncio.wait_for(task, 2) == []
    assert stream.closed
    await service.cleanup()


@pytest.mark.asyncio
async def test_total_deadline_closes_stalled_stream():
    stream = Stream([], block=True)
    service = make_service(lambda request: httpx.Response(200, headers={"content-type": "audio/pcm"}, stream=stream), timeout=0.05)
    frames = [frame async for frame in service.run_tts("text", "ctx")]
    assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)
    assert stream.closed
    await service.cleanup()


@pytest.mark.asyncio
async def test_api_uses_native_playback_context_and_completion_boundary():
    from pipecat.frames.frames import LLMFullResponseStartFrame, LLMFullResponseEndFrame, LLMTextFrame, OutputTransportMessageFrame, TTSStoppedFrame, TTSTextFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.tests.utils import run_test
    from server.playback import PlaybackLedger, PlaybackStart
    service = make_service(lambda request: httpx.Response(200, headers={"content-type": "audio/pcm"}, content=b"\x01\x00" * 240))
    ledger = PlaybackLedger(lambda *_args: None)
    pipeline = Pipeline([service, PlaybackStart(ledger)])
    downstream, _ = await asyncio.wait_for(run_test(pipeline, frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("第一句。"), LLMTextFrame("第二句。"), LLMFullResponseEndFrame()]), 10)
    audio = [frame for frame in downstream if isinstance(frame, TTSAudioRawFrame)]
    starts = [frame for frame in downstream if isinstance(frame, OutputTransportMessageFrame) and frame.message.get("data", {}).get("type") == "voice.playback.start"]
    assert len(audio) == len(starts) == 2
    assert len({frame.context_id for frame in audio}) == 2
    assert [frame.context_id for frame in audio] == [frame.message["data"]["epoch"] for frame in starts]
    assert sum(isinstance(frame, TTSStoppedFrame) for frame in downstream) == 2
    assert sum(isinstance(frame, TTSTextFrame) for frame in downstream) == 2


@pytest.mark.asyncio
async def test_partial_audio_failure_stops_without_retry_or_replaying_text():
    class BrokenStream(Stream):
        async def __aiter__(self):
            yield b"\x01\x00" * 2400
            raise httpx.ReadError("private-secret in upstream exception")
    stream = BrokenStream([])
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "audio/pcm"}, stream=stream)
    service = make_service(handler)
    frames = [frame async for frame in service.run_tts("text", "ctx")]
    assert isinstance(frames[0], TTSAudioRawFrame) and isinstance(frames[-1], ErrorFrame)
    assert len(requests) == 1 and stream.closed
    assert "private-secret" not in frames[-1].error
    await service.cleanup()


@pytest.mark.asyncio
async def test_total_deadline_remains_effective_after_first_pcm_across_tasks():
    stream = Stream([b"\x01\x00" * 2400], block=True)
    service = make_service(lambda request: httpx.Response(200, headers={"content-type": "audio/pcm"}, stream=stream), timeout=0.05)
    frames = [frame async for frame in service.run_tts("text", "ctx")]
    assert isinstance(frames[0], TTSAudioRawFrame)
    assert isinstance(frames[-1], ErrorFrame) and "超时" in frames[-1].error
    assert stream.closed
    await service.cleanup()


@pytest.mark.asyncio
async def test_redirect_is_not_followed_with_credentials():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://other.test/audio/speech"})
    service = make_service(handler)
    frames = [frame async for frame in service.run_tts("text", "ctx")]
    assert len(calls) == 1 and calls[0].url.host == "tts.test"
    assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)
    await service.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["api", "cpu"])
async def test_native_pipeline_finishes_after_error_only_final_sentence(provider, monkeypatch):
    from pipecat.frames.frames import LLMFullResponseStartFrame, LLMFullResponseEndFrame, LLMTextFrame, TTSStoppedFrame
    from pipecat.tests.utils import run_test
    from speech.pipecat_services import LocalSpeechTTS
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, content=b"\x01\x00" * 240, headers={
            "content-type": "audio/pcm", "X-Audio-Sample-Rate": "24000",
            "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"})
    if provider == "api":
        service = make_service(handler)
    else:
        service = LocalSpeechTTS()  # legacy shared context must also close
        service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    downstream, upstream = await asyncio.wait_for(run_test(service, frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("第一句。"), LLMTextFrame("第二句。"), LLMFullResponseEndFrame()]), 5)
    assert any(isinstance(frame, TTSAudioRawFrame) for frame in downstream)
    assert any(isinstance(frame, ErrorFrame) for frame in upstream)
    assert any(isinstance(frame, TTSStoppedFrame) for frame in downstream)
    assert len(calls) == 2
