import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from server.model_tts_sidecar import create_app
from server.storage import Store


def test_missing_assets_never_claim_inference(tmp_path):
    app = create_app("moss_tts", {"source": str(tmp_path), "model": str(tmp_path)})
    with TestClient(app) as client:
        state = client.get("/health").json()
        assert not state["configured"] and not state["ready"]
        assert state["device"] is None and state["backend"] == "onnx"
        assert client.post("/v1/audio/speech/stream", json={"input": "你好"}).status_code == 503
        assert app.state.host.process is None


def test_local_model_urls_and_conversation_validation():
    from server.main import SettingsUpdate
    from pydantic import ValidationError
    assert SettingsUpdate(conversation_mode="duplex").conversation_mode == "duplex"
    for patch in ({"index_tts_url": "https://remote.invalid"}, {"moss_tts_url": "http://user:secret@127.0.0.1"},
                  {"conversation_mode": "moss-live"}):
        with pytest.raises(ValidationError):
            SettingsUpdate(**patch)


def test_tts_factory_routes_only_supported_models(tmp_path):
    from server.pipecat_voice import create_tts
    settings = Store(tmp_path).settings(private=True)
    for mode, url, voice in (("gpu", settings["index_tts_url"], "default"),
                             ("cpu", settings["moss_tts_url"], "my-moss-voice")):
        service = create_tts(settings | {"tts_mode": mode, "voice": "my-moss-voice"})
        assert service.base_url == url and service.voice == voice
        assert not hasattr(service, "alignment_url")


@pytest.mark.asyncio
async def test_pipeline_and_duplex_handle_playback_differently():
    from server.conversation import ConversationInputGate
    from pipecat.frames.frames import InputAudioRawFrame, BotStartedSpeakingFrame, BotStoppedSpeakingFrame, InterruptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    for mode in ("pipeline", "duplex"):
        gate = ConversationInputGate(mode)
        sent = []
        async def push(frame, direction):
            sent.append(frame)
        gate.push_frame = push
        gate.observe(BotStartedSpeakingFrame())
        frame = InputAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=16000, num_channels=1)
        await gate.process_frame(frame, FrameDirection.DOWNSTREAM)
        assert sent[-1].audio == (bytes(320) if mode == "pipeline" else b"\x01\x00" * 160)
        gate.observe(InterruptionFrame())
        assert not gate.speaking
        gate.observe(BotStoppedSpeakingFrame())
        await gate.cleanup()


def test_first_audio_failure_releases_worker_and_reports_503(monkeypatch, tmp_path):
    import server.model_tts_sidecar as module
    monkeypatch.setattr(module, "check_assets", lambda *args: (True, "ok"))
    app = create_app("moss_tts", {"source": str(tmp_path), "model": str(tmp_path)})
    host = app.state.host
    released = []
    async def failure(*args):
        try:
            raise RuntimeError("not loaded")
            yield b""
        finally:
            released.append(True)
            host.busy = False
    monkeypatch.setattr(host, "stream", failure)
    with TestClient(app) as client:
        result = client.post("/v1/audio/speech/stream", json={"input": "test"})
        assert result.status_code == 503 and not host.busy and released


@pytest.mark.asyncio
async def test_cancelling_inference_terminates_child(monkeypatch):
    from server.model_tts_sidecar import ModelHost
    host = ModelHost("moss_tts", {})
    class Process:
        alive = True
        terminated = False
        def is_alive(self): return self.alive
        def terminate(self): self.terminated = True; self.alive = False
        def join(self, timeout): pass
        def close(self): pass
    class Pipe:
        def send(self, value): pass
        def close(self): pass
    process = host.process = Process()
    host.pipe = Pipe()
    host.busy = True
    started = asyncio.Event()
    async def receive(*args):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(host, "receive", receive)
    generator = host.stream("hello", "default")
    task = asyncio.create_task(anext(generator))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.terminated and host.process is None and not host.busy


def test_model_service_launch_config_never_contains_secrets(tmp_path, monkeypatch):
    import importlib
    import json
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    launch = importlib.import_module("optional_voice")
    monkeypatch.setattr(launch.os, "name", "nt")
    interpreter = tmp_path / "python.exe"
    interpreter.touch()
    env = {"LLM_API_KEY": "must-not-appear", "TTS_API_KEY": "nor-this",
           "DAFEIYU_INDEX_PYTHON": str(interpreter), "DAFEIYU_MOSS_PYTHON": str(interpreter),
           "DAFEIYU_INDEX_MODEL": "E:/models/index", "DAFEIYU_MOSS_MODEL": "E:/models/moss"}
    specs, config, _ = launch.optional_specs(tmp_path, env, "local-models", ["index_tts", "moss_tts"])
    text = config.read_text(encoding="utf-8")
    assert "must-not-appear" not in text and "nor-this" not in text
    assert [spec[0] for spec in specs] == [8770, 8772]
    assert all("--kind" in spec[2] for spec in specs)
    value = json.loads(text)
    assert Path(value["moss_tts"]["env"]["HF_HOME"]) == tmp_path / "cache/huggingface"
    assert value["index_tts"]["env"]["DAFEIYU_INDEX_MODEL"] == "E:/models/index"


def test_duplex_setting_does_not_change_the_llm_provider(tmp_path):
    store = Store(tmp_path)
    before = store.settings(private=True)
    store.update_settings({"conversation_mode": "duplex", "tts_mode": "cpu"})
    after = store.settings(private=True)
    assert after["llm_base_url"] == before["llm_base_url"]
    assert after["llm_model"] == before["llm_model"]
    assert after["llm_api_key"] == before["llm_api_key"]
    store.db.close()


def test_gpt_sovits_runtime_config_isolated_from_index_and_secrets(tmp_path, monkeypatch):
    import importlib, json
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    launch = importlib.import_module("optional_voice")
    interpreter = tmp_path / "python.exe"
    interpreter.touch()
    values = {"DAFEIYU_GPU_TTS_MODEL": "gpt_sovits", "DAFEIYU_GSV_PYTHON": str(interpreter),
              "DAFEIYU_GSV_PROMPT_TEXT": "参考录音内容", "LLM_API_KEY": "private",
              "DAFEIYU_INDEX_MODEL": "must-not-use", "DAFEIYU_GSV_IDLE_SECONDS": "900"}
    specs, path, _ = launch.optional_specs(tmp_path, values, "gsv", ["index_tts"])
    text = path.read_text(encoding="utf-8")
    env = json.loads(text)["index_tts"]["env"]
    assert specs[0][0] == 8770 and specs[0][2][0] == str(interpreter)
    assert env["DAFEIYU_MODEL_SERVICE"] == "gpt_sovits"
    assert env["DAFEIYU_GSV_PROMPT_TEXT"] == "参考录音内容"
    assert env["DAFEIYU_GSV_IDLE_SECONDS"] == "900"
    assert "private" not in text and "must-not-use" not in text


def test_gpt_sovits_missing_assets_never_loads_a_worker(tmp_path):
    app = create_app("gpt_sovits", {"source": str(tmp_path), "model": str(tmp_path)})
    with TestClient(app) as client:
        state = client.get("/health").json()
        assert state["model_name"] == "GPT-SoVITS-v5-turbo"
        assert not state["ready"] and not state["configured"] and state["device"] is None
        assert client.post("/v1/audio/speech/stream", json={"input": "你好"}).status_code == 503
        assert app.state.host.process is None
