import threading
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

from speech import server


@pytest.mark.asyncio
async def test_zipvoice_stream_passes_reference_speed_and_callback(monkeypatch):
    from speech import zipvoice
    seen = []
    class Model:
        sample_rate = 24000
    def generate(tts, text, ref_text, ref_audio, ref_rate, speed, callback):
        seen.append((text, ref_text, ref_rate, speed))
        callback(np.array([0.5, -0.5]), 0.5)
        return SimpleNamespace(samples=[0.5, -0.5], sample_rate=24000)
    monkeypatch.setattr(zipvoice, "generate_zipvoice", generate)
    monkeypatch.setattr(server.engine, "tts", Model())
    monkeypatch.setattr(server.engine, "tts_kind", "zipvoice")
    monkeypatch.setattr(server.engine, "tts_state", {"ready": True})
    monkeypatch.setattr(server.engine, "zip_reference_text", "参考", raising=False)
    monkeypatch.setattr(server.engine, "zip_reference_samples", np.array([0.1]), raising=False)
    monkeypatch.setattr(server.engine, "zip_reference_rate", 24000, raising=False)
    monkeypatch.setattr(server, "stream_admission", threading.BoundedSemaphore(1))
    response = await server.speech_stream(server.SpeechRequest(input="你好", speed=1.2, response_format="pcm"))
    assert len(b"".join([chunk async for chunk in response.body_iterator])) == 4
    assert seen == [("你好", "参考", 24000, 1.2)]
    with pytest.raises(HTTPException):
        await server.speech_stream(server.SpeechRequest(input="你好", voice="1", response_format="pcm"))


def test_zipvoice_missing_reference_fails_closed(monkeypatch, tmp_path):
    from speech.zipvoice import load_zipvoice
    monkeypatch.setenv("DAFEIYU_ZIPVOICE_REFERENCE", str(tmp_path / "missing.wav"))
    monkeypatch.setenv("DAFEIYU_ZIPVOICE_REFERENCE_TEXT", "参考")
    with pytest.raises(ValueError):
        load_zipvoice()
