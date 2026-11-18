import asyncio
import importlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from server import main
from server.storage import Store
from server.tts_policy import resolve_tts_mode


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)
    with TestClient(main.app) as client:
        yield client
    store.db.close()


@pytest.mark.parametrize("mode", ["auto", "cpu", "gpu", "api"])
def test_saved_mode_overrides_environment_and_survives_restart(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("DAFEIYU_VOICE_MODE", "gpu")
    store = Store(tmp_path)
    store.update_settings({"tts_mode": mode})
    store.db.close()
    reopened = Store(tmp_path)
    assert resolve_tts_mode(reopened.settings(private=True)) == mode
    reopened.db.close()


def test_legacy_settings_keep_deployment_policy():
    assert resolve_tts_mode({"tts_engine": "cosyvoice"}, {}) == "gpu"
    assert resolve_tts_mode({"tts_engine": "local"}, {}) == "cpu"
    assert resolve_tts_mode({"tts_engine": "cosyvoice"}, {"DAFEIYU_VOICE_MODE": "cpu"}) == "cpu"
    with pytest.raises(ValueError):
        resolve_tts_mode({}, {"DAFEIYU_VOICE_MODE": "invalid"})


def test_clean_api_installation_starts_without_optional_local_models(launch):
    env = {"DAFEIYU_VOICE_MODE": "api"}
    assert resolve_tts_mode({}, env) == "api"
    mode, services = launch.desired_voice_services({}, env)
    assert mode == "api" and services == set()
    assert env["DAFEIYU_GPU_PRELOAD"] == "0"


def test_api_key_is_independent_redacted_preserved_and_explicitly_clearable(client):
    result = client.put("/api/settings", json={"tts_mode": "api", "tts_api_key": "tts-secret", "llm_api_key": "llm-secret"})
    assert result.status_code == 200
    assert result.json()["tts_api_key_set"] is True
    assert "tts-secret" not in result.text and "llm-secret" not in result.text
    assert "tts_api_key" not in client.get("/api/settings").json()
    client.put("/api/settings", json={"tts_api_key": ""})
    assert main.store.settings(private=True)["tts_api_key"] == "tts-secret"
    assert client.put("/api/settings", json={"clear_tts_api_key": True, "tts_api_key": "new"}).status_code == 422
    result = client.put("/api/settings", json={"clear_tts_api_key": True}).json()
    assert result["tts_api_key_set"] is False
    assert main.store.settings(private=True)["llm_api_key"] == "llm-secret"


def test_endpoint_change_cannot_forward_existing_secret_to_another_provider(client):
    client.put("/api/settings", json={"tts_api_key": "original-secret"})
    assert client.put("/api/settings", json={"tts_api_base_url": "https://different.test/v1", "tts_api_key": ""}).status_code == 409
    assert client.put("/api/settings", json={"tts_api_base_url": "https://different.test/v1", "tts_api_key": "new-secret"}).status_code == 200


@pytest.mark.parametrize("values", [
    {"tts_mode": "other"}, {"tts_api_speed": 4.1}, {"tts_api_timeout": 0},
    {"tts_api_model": "  "}, {"tts_api_voice": ""}, {"tts_api_key": "private-secret\n"},
    {"tts_api_base_url": "http://remote.test/v1"},
    {"tts_api_base_url": "https://user:private-secret@remote.test/v1"},
    {"tts_api_base_url": "https://remote.test/v1?key=private-secret"},
])
def test_invalid_configuration_is_rejected_without_echoing_secrets(client, values):
    response = client.put("/api/settings", json=values)
    assert response.status_code == 422
    assert "private-secret" not in response.text


def test_saving_provider_changes_retires_active_voice_connections(client, monkeypatch):
    closed = []
    async def close():
        closed.append(True)
    monkeypatch.setattr(main, "close_old_voice_sessions", close)
    client.put("/api/settings", json={"tts_mode": "api", "tts_api_key": "secret"})
    assert len(closed) == 1
    client.put("/api/settings", json={"tts_api_key": ""})
    assert len(closed) == 1
    client.put("/api/settings", json={"tts_api_voice": "tide"})
    assert len(closed) == 2


def test_api_status_is_config_only_and_never_probes_or_bills_tts(client, monkeypatch):
    client.put("/api/settings", json={"tts_mode": "api", "tts_api_base_url": "https://billable.test/v1", "tts_api_key": "secret"})
    native = httpx.AsyncClient
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host != "billable.test"
        assert "secret" not in str(request.headers)
        return httpx.Response(200, json={})
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kw: native(transport=httpx.MockTransport(handler), **kw))
    status = client.get("/api/status").json()
    assert status["tts"]["configured"] is True
    assert status["tts"]["ready"] is False
    assert status["tts"]["verification"] == "not_probed"
    assert status["voice_policy"]["predicted"] == "api"
    assert calls






@pytest.fixture
def launch(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("voice_services")


@pytest.mark.parametrize("mode,kinds", [("auto", {"index_tts", "moss_tts"}), ("gpu", {"index_tts"}), ("cpu", {"moss_tts"}), ("api", set())])
def test_launcher_and_backend_share_mode_precedence(launch, mode, kinds):
    env = {"DAFEIYU_VOICE_MODE": "gpu"}
    selected, services = launch.desired_voice_services({"tts_mode": mode}, env)
    assert selected == mode and services == kinds
    assert resolve_tts_mode({"tts_mode": mode}, env) == mode
    assert launch.desired_voice_services({"tts_mode": mode}, env, external=True)[1] == set()




def test_launcher_reads_custom_data_directory_without_creating_databases(launch, tmp_path):
    assert launch.saved_voice_settings(tmp_path, {}) == {}
    store = Store(tmp_path / "alternate")
    store.update_settings({"tts_mode": "api", "tts_api_key": "never-pass-to-sidecars"})
    store.db.close()
    settings = launch.saved_voice_settings(tmp_path, {"DAFEIYU_DATA_DIR": str(tmp_path / "alternate")})
    assert settings["tts_mode"] == "api" and "tts_api_key" not in settings


def test_manager_stops_only_owned_process_on_gpu_to_cpu_transition(launch, tmp_path, monkeypatch):
    class Process:
        stopped = False
        def poll(self): return None
        def wait(self, timeout):
            assert list((tmp_path / ".runtime").glob("voice-stop-*"))
            self.stopped = True
    process = Process()
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **kw: process)
    def specs(root, env, token, kinds):
        runtime = root / ".runtime"
        runtime.mkdir(exist_ok=True)
        config, stop = runtime / f"voice-{token}.json", runtime / f"voice-stop-{token}"
        config.write_text("{}")
        return [(8770, "/health", ["fake-python"])], config, stop
    monkeypatch.setattr(launch, "optional_specs", specs)
    manager = launch.VoiceServiceManager(tmp_path, lambda *args: False)
    manager.sync({}, {"cosyvoice"})
    manager.sync({}, {"cosyvoice"})
    assert len(manager.services) == 1 and not process.stopped
    manager.sync({}, set())
    assert process.stopped and not manager.services
    assert not list((tmp_path / ".runtime").iterdir())
    borrowed = launch.VoiceServiceManager(tmp_path, lambda *args: True)
    borrowed.sync({}, {"cosyvoice"})
    borrowed.sync({}, set())  # No owned process to terminate.
    assert not borrowed.services


def test_native_cloud_mode_releases_local_services_without_changing_tts_selection(launch):
    settings = {"conversation_mode": "moss_live", "tts_mode": "gpu"}
    assert launch.desired_voice_services(settings, {}, forced=("index_tts",)) == ("moss_live", set())
    assert settings["tts_mode"] == "gpu"


def test_conflicting_external_service_is_not_borrowed_or_terminated(launch, tmp_path, monkeypatch):
    from io import BytesIO
    manager = launch.VoiceServiceManager(tmp_path, lambda *args: True)
    monkeypatch.setattr(launch, "urlopen", lambda *args, **kwargs: BytesIO(b'{"model_name":"Fun-CosyVoice3"}'))
    manager.sync({}, {"index_tts"})
    assert not manager.services and manager.failed_until["index_tts"] > 0
    manager.failed_until.clear()
    monkeypatch.setattr(launch, "urlopen", lambda *args, **kwargs: BytesIO(b'{"model_name":"IndexTTS-2.5"}'))
    manager.sync({}, {"index_tts"})
    assert manager.services["index_tts"][0] is None
    manager.close()


def test_gpu_model_selection_is_saved_and_retires_voice_connection(client, monkeypatch):
    closed = []
    async def close():
        closed.append(True)
    monkeypatch.setattr(main, "close_old_voice_sessions", close)
    response = client.put("/api/settings", json={"tts_mode": "gpu", "gpu_tts_model": "gpt_sovits"})
    assert response.status_code == 200 and response.json()["gpu_tts_model"] == "gpt_sovits"
    assert len(closed) == 1
    client.put("/api/settings", json={"gpu_tts_model": "gpt_sovits"})
    assert len(closed) == 1
    assert client.put("/api/settings", json={"gpu_tts_model": "v5dev"}).status_code == 422


def test_launcher_propagates_gpu_model_without_forwarding_credentials(launch):
    env = {"LLM_API_KEY": "private"}
    mode, kinds = launch.desired_voice_services({"tts_mode": "gpu", "gpu_tts_model": "gpt_sovits"}, env)
    assert mode == "gpu" and kinds == {"index_tts"}
    assert env["DAFEIYU_GPU_TTS_MODEL"] == "gpt_sovits"


def test_launcher_does_not_borrow_the_wrong_gpu_model(launch, tmp_path, monkeypatch):
    from io import BytesIO
    manager = launch.VoiceServiceManager(tmp_path, lambda *args: True)
    env = {"DAFEIYU_GPU_TTS_MODEL": "gpt_sovits"}
    monkeypatch.setattr(launch, "urlopen", lambda *a, **kw: BytesIO(b'{"model_name":"IndexTTS-2.5"}'))
    manager.sync(env, {"index_tts"})
    assert not manager.services
    manager.failed_until.clear()
    monkeypatch.setattr(launch, "urlopen", lambda *a, **kw: BytesIO(b'{"model_name":"GPT-SoVITS-v5-turbo"}'))
    manager.sync(env, {"index_tts"})
    assert manager.services["index_tts"][0] is None
    manager.close()


@pytest.mark.parametrize("reported,expected", [("GPT-SoVITS-v5-turbo", True), ("IndexTTS-2.5", False)])
def test_status_requires_the_selected_gpu_model(client, monkeypatch, reported, expected):
    client.put("/api/settings", json={"tts_mode": "gpu", "gpu_tts_model": "gpt_sovits"})
    native = httpx.AsyncClient
    def handler(request):
        if request.url.port == 8770:
            return httpx.Response(200, json={"model_name": reported, "ready": True,
                "configured": True, "device": "cuda", "busy": False, "gpu_eligible": True})
        return httpx.Response(200, json={})
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kw: native(transport=httpx.MockTransport(handler), **kw))
    result = client.get("/api/status").json()["tts"]
    assert result["provider"] == "GPT-SoVITS-v5-turbo"
    assert result["ready"] is expected and result["configured"] is expected
