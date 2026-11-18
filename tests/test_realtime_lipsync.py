"""Retired alignment must not gate or resurrect a realtime speech session."""
import json
from pathlib import Path

import httpx
import pytest

from server import main
from server.storage import Store


def test_old_mfa_settings_are_deleted_idempotently_without_touching_secrets_or_history(tmp_path):
    store = Store(tmp_path)
    store.update_settings({"tts_mode": "cpu", "tts_api_key": "tts-secret", "llm_api_key": "llm-secret"})
    session = store.session()
    store.add_message(session, "user", "保留聊天记录")
    for key, value in (("tts_alignment", "mfa"), ("mfa_url", "http://127.0.0.1:18771")):
        store.db.execute("INSERT INTO settings VALUES (?, ?)", (key, json.dumps(value)))
    store.db.commit()
    store.db.close()
    for _ in range(2):
        store = Store(tmp_path)
        settings = store.settings(private=True)
        assert "tts_alignment" not in settings and "mfa_url" not in settings
        assert settings["tts_mode"] == "cpu" and settings["tts_api_key"] == "tts-secret" and settings["llm_api_key"] == "llm-secret"
        assert store.messages(session)[0]["content"] == "保留聊天记录"
        assert not store.db.execute("SELECT key FROM settings WHERE key IN ('tts_alignment','mfa_url')").fetchall()
        store.db.close()


@pytest.mark.parametrize("key,value", [("tts_alignment", "mfa"), ("tts_alignment", "off"), ("mfa_url", "http://127.0.0.1:8771")])
def test_retired_fields_are_not_accepted_by_settings_api(tmp_path, monkeypatch, key, value):
    from fastapi.testclient import TestClient
    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)
    try:
        with TestClient(main.app) as client:
            assert client.put("/api/settings", json={key: value}).status_code == 422
            assert key not in client.get("/api/settings").json()
    finally:
        store.db.close()


def test_status_does_not_probe_or_wait_for_retired_alignment_service(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    store = Store(tmp_path)
    store.update_settings({"tts_mode": "gpu", "gpu_tts_model": "gpt_sovits"})
    monkeypatch.setattr(main, "store", store)
    addresses = []
    def handler(request):
        addresses.append(str(request.url))
        assert request.url.port != 8771
        state = {"configured": True, "ready": True, "device": "cuda", "model_name": "GPT-SoVITS-v5-turbo"} if request.url.port == 8770 else {}
        return httpx.Response(200, json=state)
    native = httpx.AsyncClient
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kw: native(transport=httpx.MockTransport(handler), **kw))
    try:
        with TestClient(main.app) as client:
            state = client.get("/api/status").json()
        assert addresses and state["tts"]["ready"] is True
        assert "mfa" not in state["optional"] and "alignment" not in state["tts"]
    finally:
        store.db.close()


@pytest.mark.parametrize("mode", ["gpu", "cpu", "api", "auto"])
def test_factory_ignores_stale_alignment_keys(mode, monkeypatch):
    from server import pipecat_voice
    calls = []
    monkeypatch.setattr(pipecat_voice, "LocalSpeechTTS", lambda **kw: calls.append(kw))
    settings = main.store.settings(private=True) | {"tts_mode": mode, "tts_alignment": "mfa", "mfa_url": "http://127.0.0.1:8771"}
    service = pipecat_voice.create_tts(settings)
    assert not hasattr(service, "alignment_url")
    assert all("alignment_url" not in call for call in calls)


def test_launcher_never_reenables_alignment_from_stale_store_or_force_flag(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from voice_services import desired_voice_services
    for mode, expected in (("cpu", {"moss_tts"}), ("gpu", {"index_tts"}), ("api", set())):
        _, kinds = desired_voice_services({"tts_mode": mode, "tts_alignment": "mfa"}, {}, forced={"mfa"})
        assert kinds == expected


def test_removed_sidecar_cannot_be_launched(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from optional_voice import optional_specs
    with pytest.raises(ValueError, match="Unknown voice service"):
        optional_specs(tmp_path, {}, "retired", ["mfa"])
