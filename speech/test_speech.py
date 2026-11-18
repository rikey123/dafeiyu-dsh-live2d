import io
import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace
import wave

import pytest

from speech import server


def wav(rate=16000, channels=1, width=2, frames=160):
    output = io.BytesIO()
    with wave.open(output, "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(width)
        f.setframerate(rate)
        f.writeframes(b"\0" * frames * channels * width)
    return output.getvalue()


@pytest.mark.asyncio
async def test_cancelled_waiter_never_runs_and_active_lock_survives_cancellation():
    admission = server.Admission(max_pending=3)
    request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False))
    started = threading.Event()
    release = threading.Event()
    calls = []
    def work(name, cancelled):
        calls.append(name)
        if name == "active":
            started.set()
            release.wait(5)
            assert cancelled.is_set()
        return name
    first = asyncio.create_task(admission.run(request, work, "active"))
    assert await asyncio.to_thread(started.wait, 2)
    second = asyncio.create_task(admission.run(request, work, "queued"))
    await asyncio.sleep(.05)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    third = asyncio.create_task(admission.run(request, work, "next"))
    await asyncio.sleep(.15)
    assert calls == ["active"]
    assert admission.lock.locked()
    release.set()
    assert await asyncio.wait_for(third, 2) == "next"
    assert calls == ["active", "next"]
    assert admission.pending == 0


@pytest.mark.asyncio
async def test_disconnected_queued_request_and_bounded_admission():
    admission = server.Admission(max_pending=2)
    live = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False))
    disconnected = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=True))
    started, release = threading.Event(), threading.Event()
    calls = []
    def work(name, cancelled):
        calls.append(name)
        if name == "active":
            started.set(); release.wait(5)
        return name
    active = asyncio.create_task(admission.run(live, work, "active"))
    assert await asyncio.to_thread(started.wait, 2)
    queued = asyncio.create_task(admission.run(disconnected, work, "dropped"))
    await asyncio.sleep(.02)
    with pytest.raises(server.HTTPException) as busy:
        await admission.run(live, work, "overflow")
    assert busy.value.status_code == 503
    with pytest.raises(asyncio.CancelledError):
        await queued
    release.set()
    assert await active == "active"
    assert calls == ["active"]
    assert admission.pending == 0


def test_wav_input_rejects_wrong_sample_rate_and_truncation():
    assert len(server.read_wav(wav())) == 160
    with pytest.raises(ValueError):
        server.read_wav(wav(rate=22050))
    with pytest.raises(ValueError):
        server.read_wav(wav()[:-20])


def test_failed_npu_probe_falls_back_and_caches_failure(tmp_path, monkeypatch):
    model = tmp_path / "models" / "whisper-base-openvino"
    model.mkdir(parents=True)
    (model / "openvino_decoder_model.xml").write_text("test")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setenv("DAFEIYU_ASR_DEVICE", "AUTO")
    monkeypatch.delenv("DAFEIYU_ASR_RETRY", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "openvino", SimpleNamespace(Core=lambda: SimpleNamespace(available_devices=["CPU", "NPU"]), __version__="test"))
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *args, **kwargs: object()))
    calls = []
    def bad_probe(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(returncode=1, stdout=b"!!!!", stderr=b"")
    monkeypatch.setattr(server.subprocess, "run", bad_probe)
    engine = server.Engine()
    engine.tts_state = {"ready": True, "device": "CPU", "detail": "test"}
    monkeypatch.setattr(engine, "synthesize", lambda *args: wav())
    engine._init_asr()
    assert engine.asr_state["ready"] is True
    assert engine.asr_state["device"] == "CPU"
    assert "自检失败" in engine.asr_state["detail"]
    second = server.Engine()
    second._init_asr()
    assert second.asr_state["device"] == "CPU"
    assert "24 小时" in second.asr_state["detail"]
    assert len(calls) == 1


def test_sensevoice_selected_on_cpu_when_model_is_present(tmp_path, monkeypatch):
    model = tmp_path / "models" / "sensevoice"
    model.mkdir(parents=True)
    (model / "model.int8.onnx").write_bytes(b"model")
    (model / "tokens.txt").write_text("tokens")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setenv("DAFEIYU_ASR_DEVICE", "CPU")
    monkeypatch.delenv("DAFEIYU_ASR_BACKEND", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "openvino", SimpleNamespace(Core=lambda: SimpleNamespace(available_devices=["CPU"])))
    recognizer = object()
    monkeypatch.setitem(__import__("sys").modules, "sherpa_onnx", SimpleNamespace(OfflineRecognizer=SimpleNamespace(from_sense_voice=lambda **kw: recognizer)))
    engine = server.Engine()
    engine._init_asr()
    assert engine.asr is recognizer
    assert engine.asr_kind == "sensevoice"
    assert engine.asr_state["device"] == "CPU"
