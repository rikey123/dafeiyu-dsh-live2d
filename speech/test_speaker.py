import json
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from speech import speaker as module
from speech.server import app


def test_enrollment_rejects_mixed_speakers_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "PROFILE", tmp_path / "owner.json")
    service = module.SpeakerService()
    original = {"version": 1, "model": module.MODEL.name, "embedding": [1, 0], "samples": 2}
    module.PROFILE.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(service, "embedding", lambda audio: (audio, 3.0))
    with pytest.raises(ValueError):
        service.enroll([np.array([1., 0.]), np.array([0., 1.])])
    assert json.loads(module.PROFILE.read_text(encoding="utf-8")) == original


def test_missing_profile_fails_closed_and_short_voice_uncertain(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "PROFILE", tmp_path / "owner.json")
    service = module.SpeakerService()
    service.extractor = SimpleNamespace(dim=2)
    with pytest.raises(module.SpeakerUnavailable):
        service.verify(np.zeros(100))
    module.PROFILE.write_text(json.dumps({"version": 1, "model": module.MODEL.name, "embedding": [1, 0]}), encoding="utf-8")
    def short(_audio):
        raise module.SpeakerQuality(0.3)
    monkeypatch.setattr(service, "embedding", short)
    assert service.verify(np.zeros(100))["accepted"] is None


def test_real_silero_silence_and_noise_are_not_voiced(tmp_path, monkeypatch):
    root = module.ROOT
    model = root / "models/speaker-eres2net/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
    vad = root / "web/public/vad/silero_vad_v5.onnx"
    if not model.is_file() or not vad.is_file():
        pytest.skip("optional local speaker model and Silero not installed")
    monkeypatch.setattr(module, "MODEL", model)
    monkeypatch.setattr(module, "VAD", vad)
    service = module.SpeakerService(); service.initialize()
    for audio in (np.zeros(16000 * 3, dtype=np.float32), np.random.default_rng(7).normal(0, .003, 16000 * 3).astype(np.float32)):
        with pytest.raises(module.SpeakerQuality):
            service.embedding(audio)
