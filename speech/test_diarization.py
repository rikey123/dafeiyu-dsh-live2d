import io
import wave

import pytest

from speech.diarization import diarize


def test_diarization_rejects_missing_models(tmp_path):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 1600)
    path = tmp_path / "sample.wav"
    path.write_bytes(output.getvalue())
    pytest.importorskip("sherpa_onnx")
    with pytest.raises(ValueError, match="model missing"):
        diarize(path, tmp_path / "missing", tmp_path / "missing")
