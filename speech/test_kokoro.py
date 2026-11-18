import threading

import numpy as np
import pytest

from speech import server


@pytest.mark.asyncio
async def test_kokoro_default_chinese_voice_and_metadata(monkeypatch):
    seen = []
    class Model:
        sample_rate = 24000
        num_speakers = 54
        def generate(self, text, sid, speed, callback):
            seen.append((sid, speed))
            callback(np.array([0.25, -0.25]), 1.0)
    monkeypatch.setattr(server.engine, "tts", Model())
    monkeypatch.setattr(server.engine, "tts_kind", "kokoro")
    monkeypatch.setattr(server.engine, "tts_state", {"ready": True})
    monkeypatch.setattr(server, "stream_admission", threading.BoundedSemaphore(1))
    response = await server.speech_stream(server.SpeechRequest(input="你好", response_format="pcm", speed=1.2))
    assert len(b"".join([chunk async for chunk in response.body_iterator])) == 4
    assert seen == [(45, 1.2)]
    assert response.headers["x-audio-phonemes"] == "unavailable"
    assert response.headers["x-audio-phoneme-timestamps"] == "unavailable"
