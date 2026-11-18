import httpx
import pytest
from pipecat.frames.frames import ErrorFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, OutputTransportMessageFrame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, TTSTextFrame
from pipecat.tests.utils import run_test
from pipecat.pipeline.pipeline import Pipeline

from speech.pipecat_services import LocalSpeechTTS
from server.playback import PlaybackLedger, PlaybackStart


@pytest.mark.asyncio
async def test_native_separate_tts_contexts_probe(monkeypatch):
    native = httpx.AsyncClient
    monkeypatch.setattr("speech.pipecat_services.httpx.AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"\x01\x00" * 160, headers={"X-Audio-Sample-Rate": "24000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"})), **kwargs))
    tts = LocalSpeechTTS(reuse_context_id_within_turn=False)
    downstream, _ = await run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("第一句。"), LLMTextFrame("第二句。"), LLMFullResponseEndFrame()])
    relevant = [frame for frame in downstream if isinstance(frame, (TTSStartedFrame, TTSAudioRawFrame, TTSTextFrame, TTSStoppedFrame))]
    assert [type(frame) for frame in relevant] == [TTSStartedFrame, TTSAudioRawFrame, TTSTextFrame, TTSStoppedFrame, TTSStartedFrame, TTSAudioRawFrame, TTSTextFrame, TTSStoppedFrame]
    assert relevant[0].context_id != relevant[4].context_id


@pytest.mark.asyncio
async def test_sentence_error_carries_failed_context(monkeypatch):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.Response(500)
        return httpx.Response(200, content=b"\x01\x00" * 160, headers={"X-Audio-Sample-Rate": "24000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"})
    native = httpx.AsyncClient
    monkeypatch.setattr("speech.pipecat_services.httpx.AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    tts = LocalSpeechTTS(reuse_context_id_within_turn=False)
    downstream, upstream = await run_test(tts, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("第一句。"), LLMTextFrame("第二句。"), LLMFullResponseEndFrame()])
    first = next(frame.context_id for frame in downstream if isinstance(frame, TTSStartedFrame))
    error = next(frame for frame in upstream if isinstance(frame, ErrorFrame))
    assert error.metadata.get("tts_context_id") and error.metadata["tts_context_id"] != first


@pytest.mark.asyncio
async def test_native_sentence_text_precedes_matching_audio_start(monkeypatch):
    native = httpx.AsyncClient
    monkeypatch.setattr("speech.pipecat_services.httpx.AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"\x01\x00" * 160, headers={"X-Audio-Sample-Rate": "24000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"})), **kwargs))
    tts = LocalSpeechTTS(reuse_context_id_within_turn=False)
    pipeline = Pipeline([tts, PlaybackStart(PlaybackLedger(lambda _group, _text: None))])
    downstream, _ = await run_test(pipeline, frames_to_send=[LLMFullResponseStartFrame(), LLMTextFrame("第一句。"), LLMTextFrame("第二句。"), LLMFullResponseEndFrame()])
    starts = [(index, frame.message["data"]) for index, frame in enumerate(downstream) if isinstance(frame, OutputTransportMessageFrame) and frame.message.get("data", {}).get("type") == "voice.playback.start"]
    assert [data["text"] for _, data in starts] == ["第一句。", "第二句。"]
    for index, data in starts:
        audio = next(frame for frame in downstream[index + 1:] if isinstance(frame, TTSAudioRawFrame))
        assert audio.context_id == data["epoch"]
