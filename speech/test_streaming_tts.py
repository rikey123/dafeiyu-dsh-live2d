import asyncio
import io
import wave

import httpx
import pytest
from pipecat.frames.frames import ErrorFrame, InterruptionFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, TTSAudioRawFrame
from pipecat.tests.utils import run_test, SleepFrame

from speech import pipecat_services as local


@pytest.mark.asyncio
async def test_first_pcm_is_yielded_before_the_server_finishes_the_sentence(monkeypatch):
    finish = asyncio.Event()
    paths = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"\x01\x00" * 800
            await finish.wait()
            yield b"\x02\x00" * 800
    def handler(request):
        paths.append(request.url.path)
        assert request.url.path == "/v1/audio/speech/stream"
        return httpx.Response(200, headers={"X-Audio-Sample-Rate": "24000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"}, stream=Stream())
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kw: native(transport=httpx.MockTransport(handler), **kw))
    tts = local.LocalSpeechTTS()
    generator = tts.run_tts("你好", "ctx")
    try:
        frame = await asyncio.wait_for(anext(generator), 1)
        assert isinstance(frame, TTSAudioRawFrame) and frame.audio == b"\x01\x00" * 800
        assert not finish.is_set() and not frame.metadata.get("alignment")
        finish.set()
        assert len([frame async for frame in generator]) == 1
        assert paths == ["/v1/audio/speech/stream"]
    finally:
        await generator.aclose()
        await tts.cleanup()


def wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 1600)
    return output.getvalue()






@pytest.mark.asyncio
async def test_pipeline_interruption_closes_stream_and_next_turn_succeeds(monkeypatch):
    started, closed = asyncio.Event(), asyncio.Event()
    calls = 0
    class BlockedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
            yield b"\0\0"
    async def handler(request):
        nonlocal calls
        calls += 1
        headers = {"X-Audio-Sample-Rate": "16000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"}
        if calls == 1:
            return httpx.Response(200, headers=headers, stream=BlockedStream())
        return httpx.Response(200, headers=headers, content=b"\x01\x00" * 1600)
    native = httpx.AsyncClient
    monkeypatch.setattr(local.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    tts = local.LocalSpeechTTS()
    frames = [LLMFullResponseStartFrame(), LLMTextFrame("第一句。"), LLMFullResponseEndFrame(), SleepFrame(sleep=0.3), InterruptionFrame(), SleepFrame(sleep=0.3), LLMFullResponseStartFrame(), LLMTextFrame("第二句。"), LLMFullResponseEndFrame()]
    downstream, _ = await asyncio.wait_for(run_test(tts, frames_to_send=frames), 8)
    assert started.is_set() and closed.is_set() and calls == 2
    audio = [frame for frame in downstream if isinstance(frame, TTSAudioRawFrame)]
    assert len(audio) == 1 and audio[0].audio == b"\x01\x00" * 1600
    assert not tts._tts_requests


