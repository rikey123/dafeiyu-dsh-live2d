import hashlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import wave

import pytest

from speech import mfa_alignment as mfa
from speech.mfa_alignment import intervals


def test_phone_intervals_preserve_native_times_and_labels():
    source = [SimpleNamespace(label="ɲ", start=0.03, end=0.06), SimpleNamespace(label="i˨˩˦", start=0.06, end=0.14)]
    result = intervals(source, 1.0, "phoneme")
    assert result == [{"text": "ɲ", "start_s": 0.03, "end_s": 0.06, "unit": "phoneme"}, {"text": "i˨˩˦", "start_s": 0.06, "end_s": 0.14, "unit": "phoneme"}]


def test_phone_intervals_reject_overlap_or_out_of_bounds():
    source = [SimpleNamespace(label="a", start=0.1, end=0.3), SimpleNamespace(label="b", start=0.2, end=1.1)]
    with pytest.raises(ValueError):
        intervals(source, 1.0, "phoneme")


def test_phone_interval_clamps_small_end_tolerance():
    source = [SimpleNamespace(label="a", start=0.8, end=1.01)]
    assert intervals(source, 1.0, "phoneme")[0]["end_s"] == 1.0


@pytest.mark.parametrize("start,end", [(0.4, 0.4), (1.0, 1.01), (1.01, 1.02), (0.8, 1.03)])
def test_phone_interval_rejects_zero_length_or_large_overrun(start, end):
    with pytest.raises(ValueError):
        intervals([SimpleNamespace(label="a", start=start, end=end)], 1.0, "phoneme")


@pytest.fixture
def alignment_runtime(tmp_path, monkeypatch):
    """Only the external MFA CLI/parser are doubles; exercise file isolation."""
    audio, dictionary, model = (tmp_path / name for name in ("source.wav", "mandarin.dict", "acoustic.zip"))
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "NONE"))
        stream.writeframes(b"\x01\x00" * 1600)
    dictionary.write_bytes(b"dictionary-v1")
    model.write_bytes(b"acoustic-v1")
    monkeypatch.setattr(mfa, "version", lambda name: "3.4.3")
    monkeypatch.setenv("DAFEIYU_MFA_SINGLE_FILE", "1")
    monkeypatch.setenv("DAFEIYU_MFA_CACHE", str(tmp_path / "cache"))
    state = SimpleNamespace(audio=audio, dictionary=dictionary, model=model, calls=[], failure=None)

    def open_grid(path, includeEmptyIntervals):
        assert Path(path).is_file() and includeEmptyIntervals is False
        def tier(name):
            end = 1.0 if state.failure == "invalid_tier" else 0.1
            return SimpleNamespace(entries=[SimpleNamespace(label="a" if name == "phones" else "你好", start=0, end=end)])
        return SimpleNamespace(getTier=tier)
    monkeypatch.setitem(sys.modules, "praatio", SimpleNamespace(textgrid=SimpleNamespace(openTextgrid=open_grid)))

    def run(command, *, env, check, timeout, stdout):
        assert check is True and timeout == 300 and stdout == subprocess.DEVNULL
        work = Path(env["MFA_ROOT_DIR"])
        artifact = work / "extracted_models/dictionary/L.fst"
        reused = artifact.is_file()
        state.calls.append({"command": command, "work": work, "reused": reused})
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"private-update" if reused else b"compiled-model")
        # Request-local data must never be published in the shared model cache.
        (work / "input.lab").write_text("private transcript", encoding="utf-8")
        if state.failure == "command":
            raise subprocess.CalledProcessError(1, command)
        if state.failure == "interrupt":
            raise KeyboardInterrupt()
        grid = Path(command[6]) if command[1] == "align_one" else Path(command[5]) / "input.TextGrid"
        grid.parent.mkdir(parents=True, exist_ok=True)
        grid.write_text("test grid", encoding="utf-8")
    monkeypatch.setattr(mfa.subprocess, "run", run)
    return state


@pytest.mark.parametrize("changed", ["dictionary", "model", "version"])
def test_compiled_cache_key_invalidates_changed_models_or_mfa(alignment_runtime, monkeypatch, changed):
    state = alignment_runtime
    first = mfa.model_cache_key(state.dictionary, state.model)
    assert first == mfa.model_cache_key(state.dictionary, state.model)
    if changed == "version":
        monkeypatch.setattr(mfa, "version", lambda name: "3.4.4")
    else:
        getattr(state, changed).write_bytes(b"replacement")
    assert mfa.model_cache_key(state.dictionary, state.model) != first


def test_align_one_reuses_only_models_in_private_workspace(alignment_runtime, tmp_path):
    state = alignment_runtime
    grid = tmp_path / "saved.TextGrid"
    first = mfa.align(state.audio, "你好", state.dictionary, state.model, grid)
    assert first["method"] == "align_one" and first["device"] == "CPU"
    assert first["audio_sha256"] == hashlib.sha256(state.audio.read_bytes()).hexdigest()
    assert grid.is_file() and first["phones"] and first["words"]
    command = state.calls[0]["command"]
    assert command[:2] == ["mfa", "align_one"]
    assert command[-3:] == ["--num_jobs", "1", "--no_use_mp"]
    cache = tmp_path / "cache/compiled" / mfa.model_cache_key(state.dictionary, state.model)
    artifacts = [p for p in cache.rglob("*") if p.is_file()]
    assert [p.relative_to(cache).as_posix() for p in artifacts] == ["extracted_models/dictionary/L.fst"]
    mfa.align(state.audio, "另一句话", state.dictionary, state.model)
    assert [call["reused"] for call in state.calls] == [False, True]
    assert state.calls[0]["work"] != state.calls[1]["work"]
    assert all(not call["work"].exists() for call in state.calls)
    assert artifacts[0].read_bytes() == b"compiled-model"  # A request cannot modify the shared copy.


@pytest.mark.parametrize("failure,exception", [("command", subprocess.CalledProcessError), ("interrupt", KeyboardInterrupt), ("invalid_tier", ValueError)])
def test_failed_or_interrupted_alignment_does_not_publish_cache(alignment_runtime, tmp_path, failure, exception):
    state = alignment_runtime
    state.failure = failure
    with pytest.raises(exception):
        mfa.align(state.audio, "你好", state.dictionary, state.model)
    assert list((tmp_path / "cache/compiled").iterdir()) == []
    assert not state.calls[0]["work"].exists()


def test_legacy_corpus_path_remains_explicitly_available(alignment_runtime, tmp_path, monkeypatch):
    state = alignment_runtime
    monkeypatch.delenv("DAFEIYU_MFA_SINGLE_FILE")
    result = mfa.align(state.audio, "你好", state.dictionary, state.model)
    assert result["method"] == "corpus"
    assert state.calls[0]["command"][:2] == ["mfa", "align"]
    assert "--single_speaker" in state.calls[0]["command"]
    assert not (tmp_path / "cache").exists()
