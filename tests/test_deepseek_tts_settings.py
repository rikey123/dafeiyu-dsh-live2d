import json

import pytest
from fastapi.testclient import TestClient

from server import main
from server.storage import Store
from server.tts_policy import api_configured


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)
    with TestClient(main.app) as client:
        yield client
    store.db.close()


def test_fresh_defaults_use_native_deepseek_not_generic_endpoint(client):
    settings = client.get("/api/settings").json()
    assert settings["tts_api_provider"] == "deepseek"
    assert settings["tts_api_base_url"] == "https://api.deepseek.com/v1"
    assert settings["tts_api_voice"] == "stella"
    assert settings["tts_api_filter_markdown"] is True
    assert settings["tts_api_key_set"] is False


@pytest.mark.parametrize("provider,voice,status", [("deepseek", "stella", 200), ("deepseek", "tide", 200), ("deepseek", "alloy", 422), ("other", "stella", 422), ("openai_compatible", "custom", 200)])
def test_provider_specific_voice_validation(client, provider, voice, status):
    assert client.put("/api/settings", json={"tts_api_provider": provider, "tts_api_voice": voice}).status_code == status


def test_voice_or_filter_changes_retire_connection(client, monkeypatch):
    calls = []
    async def close():
        calls.append(1)
    monkeypatch.setattr(main, "close_old_voice_sessions", close)
    assert client.put("/api/settings", json={"tts_api_voice": "tide"}).status_code == 200
    assert client.put("/api/settings", json={"tts_api_filter_markdown": False}).status_code == 200
    assert len(calls) == 2
    assert client.put("/api/settings", json={"tts_api_filter_markdown": False}).status_code == 200
    assert len(calls) == 2


def test_api_readiness_does_not_require_unsupported_model_or_speed():
    assert api_configured({"tts_api_provider": "deepseek", "tts_api_base_url": "https://api.deepseek.com/v1", "tts_api_voice": "stella", "tts_api_key": "independent"})
    assert not api_configured({"tts_api_provider": "deepseek", "tts_api_base_url": "https://api.deepseek.com/v1", "tts_api_voice": "alloy", "tts_api_key": "independent"})


@pytest.mark.parametrize("legacy,provider", [
    ({}, "deepseek"),
    ({"tts_api_base_url": "https://api.openai.com/v1", "tts_api_voice": "alloy", "tts_api_model": "tts-1"}, "deepseek"),
    ({"tts_api_key": "original-secret"}, "openai_compatible"),
    ({"tts_api_base_url": "https://custom.test/v1"}, "openai_compatible"),
    ({"tts_api_voice": "other"}, "openai_compatible"),
    ({"tts_api_speed": 1.2}, "openai_compatible"),
])
def test_one_time_migration_never_forwards_an_existing_secret(tmp_path, legacy, provider):
    store = Store(tmp_path)
    store.db.execute("DELETE FROM settings WHERE key LIKE 'tts_api_%'")
    for key, value in legacy.items():
        store.db.execute("INSERT INTO settings VALUES (?, ?)", (key, json.dumps(value)))
    store.db.commit(); store.db.close()
    store = Store(tmp_path)
    settings = store.settings(private=True)
    assert settings["tts_api_provider"] == provider
    if provider == "openai_compatible":
        assert settings["tts_api_base_url"] == legacy.get("tts_api_base_url", "https://api.openai.com/v1")
        assert settings["tts_api_voice"] == legacy.get("tts_api_voice", "alloy")
    for key in ["tts_api_key", "tts_api_speed"]:
        if key in legacy:
            assert settings[key] == legacy[key]
    store.update_settings({"clear_tts_api_key": True})
    store.db.close()
    store = Store(tmp_path)
    assert store.settings()["tts_api_provider"] == provider
    store.db.close()


def test_changing_legacy_host_requires_explicit_new_key_or_clear(client):
    assert client.put("/api/settings", json={"tts_api_provider": "openai_compatible", "tts_api_base_url": "https://old.test/v1", "tts_api_voice": "old", "tts_api_key": "old-key"}).status_code == 200
    new = {"tts_api_provider": "deepseek", "tts_api_base_url": "https://api.deepseek.com/v1", "tts_api_voice": "stella"}
    assert client.put("/api/settings", json=new).status_code == 409
    assert main.store.settings(private=True)["tts_api_key"] == "old-key"
    assert client.put("/api/settings", json={**new, "clear_tts_api_key": True}).status_code == 200


def test_factory_uses_native_adapter_without_reusing_model_or_speed():
    from server.pipecat_voice import create_tts
    from server.storage import DEFAULTS
    from speech.deepseek_tts import DeepSeekSpeechTTS
    from speech.api_tts import APISpeechTTS
    settings = {**DEFAULTS, "tts_mode": "api", "tts_api_model": "not-a-deepseek-model", "tts_api_speed": 4}
    native = create_tts(settings)
    assert isinstance(native, DeepSeekSpeechTTS)
    assert native.voice == "stella" and not hasattr(native, "speed")
    assert isinstance(create_tts({**settings, "tts_api_provider": "openai_compatible"}), APISpeechTTS)
