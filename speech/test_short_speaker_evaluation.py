import io
import json
import wave

import numpy as np

from speech import short_speaker_evaluation as evaluation
from speech.speaker import SpeakerQuality, SpeakerService


def make_wav(value):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(np.full(32000, value, dtype="<i2").tobytes())
    return output.getvalue()


def test_experimental_gate_does_not_modify_production_gate(monkeypatch):
    service = SpeakerService()
    limits = []
    def embedding(audio, minimum_voiced_seconds):
        limits.append(minimum_voiced_seconds)
        raise SpeakerQuality(0.2)
    monkeypatch.setattr(service, "_embedding", embedding)
    for function in (lambda: service.embedding(np.ones(16000)), lambda: evaluation.experimental_embedding(service, np.ones(16000)), lambda: service.embedding(np.ones(16000))):
        try:
            function()
        except SpeakerQuality:
            pass
    assert limits == [2.0, 0.1, 2.0]


def test_window_helper_reports_short_recording_and_voice_duration():
    class Fake:
        def _embedding(self, audio, minimum_voiced_seconds):
            if len(audio) == 8000:
                raise SpeakerQuality(0.05)
            return np.array([1.0, 0.0]), len(audio) / 16000
    rows = evaluation.window_trials(Fake(), np.ones(20000), lambda vector: vector[0])
    assert [row["window_s"] for row in rows] == [0.5, 1.0, 1.5, 2.0]
    assert rows[0]["reason"] == "insufficient_speech" and rows[0]["voiced_seconds"] == 0.05
    assert rows[1]["score"] == 1.0
    assert rows[2]["reason"] == "insufficient_recording" and rows[2]["voiced_seconds"] == 1.25


def test_short_window_report_counts_uncertain_and_nonspeech(tmp_path):
    for index in range(5):
        (tmp_path / f"{index}.wav").write_bytes(make_wav(index + 1))
    manifest = {"enrollment": ["0.wav", "1.wav"], "cases": [{"id": "owner", "path": "2.wav", "expected_owner": True}, {"id": "other", "path": "3.wav", "expected_owner": False}, {"id": "noise", "path": "4.wav", "expected_owner": False, "kind": "noise"}]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    class Fake:
        def initialize(self): pass
        def embedding(self, audio): return np.array([1.0, 0.0]), 2.0
        def _embedding(self, audio, minimum_voiced_seconds):
            if len(audio) <= 8000:
                raise SpeakerQuality(0.05)
            return np.array([1.0, 0.0]), len(audio) / 16000
    report = evaluation.evaluate(path, Fake())
    assert report["production_gate_changed"] is False
    assert len(report["results"]) == 12
    first, second = report["summary"][:2]
    assert (first["owner_trials"], first["other_speech_trials"], first["nonspeech_trials"]) == (1, 1, 1)
    assert first["effective_frr"] == 1 and first["far"] == 0 and first["uncertain"] == 3
    assert second["effective_frr"] == 0 and second["far"] == 1 and second["nonspeech_false_accepts"] == 1
