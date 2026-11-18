"""Speech paths must separate installed code from writable user state."""
import importlib
import sys
from types import SimpleNamespace

from speech import prepare, server, streaming_asr


def test_relocated_preparation_and_failure_cache(tmp_path, monkeypatch):
    code = tmp_path / "installed"
    home = tmp_path / "home"
    code.mkdir()
    monkeypatch.setenv("DAFEIYU_HOME", str(home))
    monkeypatch.delenv("DAFEIYU_DATA_DIR", raising=False)
    monkeypatch.setattr(prepare, "ROOT", code)
    monkeypatch.setattr(server, "ROOT", code)
    downloads = []
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=lambda **kw: downloads.append(kw)))
    monkeypatch.setattr(sys, "argv", ["prepare", "tts"])
    prepare.main()
    assert downloads[0]["local_dir"] == home / "models/sherpa-onnx-vits-zh-ll"
    engine = server.Engine()
    monkeypatch.setattr(engine, "_fingerprint", lambda path: "fingerprint")
    engine._save_failure(home / "models/whisper", "failure")
    assert engine._cached_failure(home / "models/whisper") == "failure"
    assert (home / "data/npu-asr-failure.json").is_file()
    assert list(code.iterdir()) == []


def test_streaming_default_and_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DAFEIYU_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DAFEIYU_DATA_DIR", raising=False)
    monkeypatch.delenv("DAFEIYU_STREAM_ASR_MODEL", raising=False)
    assert streaming_asr.model_path() == tmp_path / "home/models/streaming-zipformer-zh-en"
    monkeypatch.setenv("DAFEIYU_STREAM_ASR_MODEL", str(tmp_path / "custom"))
    assert streaming_asr.model_path() == tmp_path / "custom"


def test_speaker_and_mfa_defaults(tmp_path, monkeypatch):
    import speech.speaker as speaker
    import speech.mfa_alignment as mfa
    monkeypatch.setenv("DAFEIYU_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DAFEIYU_DATA_DIR", raising=False)
    monkeypatch.delenv("DAFEIYU_SPEAKER_MODEL", raising=False)
    monkeypatch.delenv("DAFEIYU_SPEAKER_PROFILE", raising=False)
    try:
        importlib.reload(speaker)
        assert speaker.MODEL == tmp_path / "home/models/speaker-eres2net/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
        assert speaker.PROFILE == tmp_path / "home/data/speaker-owner.json"
        assert speaker.VAD == tmp_path / "home/public/vad/silero_vad_v5.onnx"
        assert mfa.cache_dir() == tmp_path / "home/cache"
    finally:
        monkeypatch.delenv("DAFEIYU_HOME", raising=False)
        importlib.reload(speaker)


def test_vad_preparation_is_external_verified_and_repeatable(tmp_path, monkeypatch):
    import hashlib
    import io
    payload = b"mock VAD model, never inference"
    calls = []
    monkeypatch.setenv("DAFEIYU_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(prepare, "VAD_SHA256", hashlib.sha256(payload).hexdigest())
    def fetch(url, **_):
        calls.append(url)
        return io.BytesIO(payload)
    monkeypatch.setattr(prepare.urllib.request, "urlopen", fetch)
    target = prepare.prepare_vad()
    assert target == tmp_path / "home/public/vad/silero_vad_v5.onnx"
    assert target.read_bytes() == payload
    assert target.with_suffix(".source.json").is_file()
    assert prepare.prepare_vad() == target
    assert len(calls) == 1
    target.write_bytes(b"corrupt")
    import pytest
    with pytest.raises(ValueError, match="SHA-256"):
        prepare.prepare_vad()
