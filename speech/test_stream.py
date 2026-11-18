import asyncio
import threading

import numpy as np
import pytest
from fastapi import HTTPException

from speech import server


@pytest.mark.asyncio
async def test_stream_pcm_and_busy_admission(monkeypatch):
    class FakeTTS:
        sample_rate = 16000
        num_speakers = 1

        def generate(self, text, sid, speed, callback):
            callback(np.array([0.5, -0.5]), 0.5)
            callback(np.array([0.25]), 1.0)

    monkeypatch.setattr(server.engine, "tts", FakeTTS())
    monkeypatch.setattr(server.engine, "tts_kind", "sherpa")
    monkeypatch.setattr(server.engine, "tts_state", {"ready": True})
    monkeypatch.setattr(server, "stream_admission", threading.BoundedSemaphore(1))
    payload = server.SpeechRequest(input="hello", response_format="pcm")
    response = await server.speech_stream(payload)
    with pytest.raises(HTTPException) as busy:
        await server.speech_stream(payload)
    assert busy.value.status_code == 503
    chunks = [chunk async for chunk in response.body_iterator]
    assert [len(chunk) for chunk in chunks] == [4, 2]
    assert response.headers["x-audio-format"] == "pcm_s16le"
    with pytest.raises(HTTPException) as invalid:
        await server.speech_stream(server.SpeechRequest(input="hello", voice="1", response_format="pcm"))
    assert invalid.value.status_code == 400


@pytest.mark.asyncio
async def test_stream_cancellation_waits_for_native_worker(monkeypatch):
    started, release = threading.Event(), threading.Event()
    class FakeTTS:
        sample_rate = 16000
        num_speakers = 1

        def generate(self, text, sid, speed, callback):
            started.set()
            callback(np.array([0.5]), 0.5)
            release.wait(2)

    monkeypatch.setattr(server.engine, "tts", FakeTTS())
    monkeypatch.setattr(server.engine, "tts_kind", "sherpa")
    monkeypatch.setattr(server.engine, "tts_state", {"ready": True})
    monkeypatch.setattr(server, "stream_admission", threading.BoundedSemaphore(1))
    payload = server.SpeechRequest(input="hello", response_format="pcm")
    response = await server.speech_stream(payload)
    assert await response.body_iterator.__anext__()
    assert started.is_set()
    await response.body_iterator.aclose()
    assert server.engine.tts_lock.locked()
    with pytest.raises(HTTPException):
        await server.speech_stream(payload)
    release.set()
    for _ in range(100):
        if server.stream_admission.acquire(blocking=False):
            server.stream_admission.release()
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("native worker did not release admission")
    assert not server.engine.tts_lock.locked()
