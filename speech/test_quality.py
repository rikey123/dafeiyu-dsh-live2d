import io
import wave

import pytest
from fastapi.testclient import TestClient

from speech import server


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setparams((1, 2, 16000, 1600, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 1600)
    return out.getvalue()


@pytest.mark.parametrize("detected", [False, True])
def test_transcription_quality_and_alignment_contract(monkeypatch, detected):
    monkeypatch.setattr(server.engine, "start", lambda: None)
    monkeypatch.setattr(server, "speech_activity", lambda audio: {"speech_detected": detected, "vad_segments": [{"start_s": 0.0, "end_s": 0.1}] if detected else [], "vad_model": "silero_vad_v5", "vad_device": "CPU"})
    calls = []
    monkeypatch.setattr(server.engine, "transcribe", lambda audio, cancelled: calls.append(True) or "你好")
    with TestClient(server.app) as client:
        response = client.post("/v1/audio/transcriptions", files={"file": ("input.wav", wav_bytes(), "audio/wav")})
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == ("你好" if detected else "")
    assert data["audio"]["duration_s"] == 0.1
    assert data["alignment"]["tokens"] is None and data["alignment"]["words"] is None
    assert len(calls) == int(detected)
    if not detected:
        assert data["reason"] == "no_speech"
