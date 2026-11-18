import asyncio

import httpx
import pytest
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame

from speech import pipecat_services as local


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 429, 500, 503])
async def test_stream_http_error_never_retries_as_wav(monkeypatch, status):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(status, text="unavailable")
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    service = local.LocalSpeechTTS()
    try:
        frames = [frame async for frame in service.run_tts("你好", "ctx")]
        assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)
        assert paths == ["/v1/audio/speech/stream"]
    finally:
        client = service._http_client
        await service.cleanup()
        assert client.is_closed


@pytest.mark.asyncio
async def test_cancel_after_first_pcm_closes_stream_and_does_not_fallback(monkeypatch):
    started = asyncio.Event()
    closed = asyncio.Event()
    paths = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"\x01\x00" * 160
            started.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, stream=Stream(), headers={"X-Audio-Sample-Rate": "16000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"})

    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    service = local.LocalSpeechTTS()
    frames = []
    async def consume():
        async for frame in service.run_tts("你好", "ctx"):
            frames.append(frame)
    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(frames) == 1 and isinstance(frames[0], TTSAudioRawFrame)
        assert closed.is_set()
        assert paths == ["/v1/audio/speech/stream"]
    finally:
        client = service._http_client
        await service.cleanup()
        assert client.is_closed
