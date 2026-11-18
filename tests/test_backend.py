import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server import main
from server.context import context_messages
from server.storage import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path))
    with TestClient(main.app) as test_client:
        yield test_client


def test_settings_secret_redaction_and_validation(client):
    result = client.put("/api/settings", json={"llm_api_key": "secret", "llm_model": "test"})
    assert result.status_code == 200
    assert result.json()["api_key_set"] is True
    assert "secret" not in result.text
    client.put("/api/settings", json={"llm_api_key": ""})
    assert main.store.settings(private=True)["llm_api_key"] == "secret"
    assert client.put("/api/settings", json={"llm_base_url": "http://key:password@host/v1"}).status_code == 422
    assert client.put("/api/settings", json={"temperature": 3}).status_code == 422
    assert client.put("/api/settings", headers={"Origin": "http://evil.test"}, json={}).status_code == 403


def test_persistence_memories_and_session_delete(client):
    memory = client.post("/api/memories", json={"content": "我喜欢茶"}).json()
    assert client.get("/api/memories").json()[0]["content"] == "我喜欢茶"
    assert client.delete("/api/memories/" + memory["id"]).json()["deleted"]
    session_id = client.post("/api/sessions").json()["id"]
    assert client.get("/api/sessions").json()[0]["id"] == session_id
    assert client.delete("/api/sessions/" + session_id).json()["deleted"]
    assert client.get("/api/sessions/" + session_id + "/messages").status_code == 404


def test_long_context_keeps_latest_request_with_large_memory_collection():
    history = [{"role": "user" if index % 2 == 0 else "assistant", "content": str(index) * 1000} for index in range(40)]
    history.append({"role": "user", "content": "最新问题"})
    messages = context_messages({"system_prompt": "角色设定"}, [{"content": "记忆" * 500}] * 30, history)
    assert messages[-1] == {"role": "user", "content": "最新问题"}
    assert sum(len(item["content"]) for item in messages) <= 20000
    assert messages[0]["role"] == "system" and messages[1]["role"] == "user"


def test_legacy_chat_is_retired(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/chat"):
            pass


def test_owner_only_requires_enrolled_model(client, monkeypatch):
    async def unavailable(_address):
        return {"enabled": True, "ready": True, "enrolled": False}
    monkeypatch.setattr(main, "get_owner_status", unavailable)
    assert client.get("/api/settings").json()["owner_voice_only"] is False
    assert client.put("/api/settings", json={"owner_voice_only": True}).status_code == 409
    assert client.get("/api/settings").json()["owner_voice_only"] is False
    async def ready(_address):
        return {"enabled": True, "ready": True, "enrolled": True}
    monkeypatch.setattr(main, "get_owner_status", ready)
    assert client.put("/api/settings", json={"owner_voice_only": True}).json()["owner_voice_only"] is True
    monkeypatch.setattr(main, "get_owner_status", unavailable)
    assert client.put("/api/settings", json={"speech_base_url": "http://127.0.0.1:9999"}).status_code == 409
    response = client.put("/api/settings", json={"owner_voice_only": False, "speech_base_url": "http://127.0.0.1:9999"})
    assert response.json()["owner_voice_only"] is False


def test_streaming_preview_is_opt_in_and_preserves_other_settings(client):
    settings = client.get("/api/settings").json()
    assert settings["streaming_asr_preview"] is False
    assert client.put("/api/settings", json={"streaming_asr_preview": True}).json()["streaming_asr_preview"] is True
    assert client.get("/api/settings").json()["owner_voice_only"] is False


def test_optional_tts_settings_are_explicit_and_loopback_only(client):
    settings = client.get("/api/settings").json()
    assert (settings["tts_engine"], settings["cosyvoice_url"]) == ("local", "http://127.0.0.1:8770")
    assert client.put("/api/settings", json={"tts_engine": "unknown"}).status_code == 422
    assert client.put("/api/settings", json={"tts_alignment": "unknown"}).status_code == 422
    assert client.put("/api/settings", json={"cosyvoice_url": "http://example.com:8770"}).status_code == 422
    assert client.put("/api/settings", json={"tts_engine": "cosyvoice"}).status_code == 200
    assert client.get("/api/settings").json()["tts_engine"] == "cosyvoice"


@pytest.mark.parametrize("configured,busy,eligible,expected", [(True, False, True, "gpu"), (True, True, True, "cpu"), (False, False, True, "cpu"), (True, False, False, "cpu")])
def test_status_predicts_auto_route(client, monkeypatch, configured, busy, eligible, expected):
    monkeypatch.setenv("DAFEIYU_VOICE_MODE", "auto")
    native = httpx.AsyncClient
    def handler(request):
        if request.url.port == 8770:
            return httpx.Response(200, json={"model_name": "IndexTTS-2.5", "configured": configured, "busy": busy, "gpu_eligible": eligible})
        return httpx.Response(200, json={"asr": {"ready": True}, "tts": {"ready": True}})
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    policy = client.get("/api/status").json()["voice_policy"]
    assert policy["requested"] == "auto" and policy["predicted"] == expected and policy["prediction_only"] is True


def test_voice_metrics_endpoint_requires_existing_session(client):
    from server.voice_metrics import registry
    session = client.post("/api/sessions").json()["id"]
    assert client.get(f"/api/voice/metrics/{session}").status_code == 404
    registry.start(session).add("tts.ttfb", .2)
    assert client.get(f"/api/voice/metrics/{session}").json()["series"]["tts.ttfb"]["n"] == 1
    client.delete(f"/api/sessions/{session}")
    assert client.get(f"/api/voice/metrics/{session}").status_code == 404


def test_owner_enrollment_count_and_size_are_bounded(client):
    assert client.post("/api/voice/owner/enroll", files=[("files", ("one.wav", b"audio", "audio/wav"))]).status_code == 422
    files = [("files", ("one.wav", b"x" * 2_000_001, "audio/wav")), ("files", ("two.wav", b"audio", "audio/wav"))]
    assert client.post("/api/voice/owner/enroll", files=files).status_code == 413


def test_owner_status_tracks_setting_and_delete_disables(client, monkeypatch):
    async def ready(_address):
        return {"enabled": True, "ready": True, "enrolled": True}
    monkeypatch.setattr(main, "get_owner_status", ready)
    original_client = httpx.AsyncClient
    def mock_client(**kwargs):
        return original_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"deleted": True})), **kwargs)
    monkeypatch.setattr(main.httpx, "AsyncClient", mock_client)
    status = client.get("/api/voice/owner/status").json()
    assert status["enabled"] is False and status["service_enabled"] is True
    assert client.put("/api/settings", json={"owner_voice_only": True}).status_code == 200
    assert client.get("/api/voice/owner/status").json()["enabled"] is True
    assert client.delete("/api/voice/owner/enrollment").status_code == 200
    assert client.get("/api/voice/owner/status").json()["enabled"] is False


def test_owner_status_failure_does_not_enable_filter(client, monkeypatch):
    original_client = httpx.AsyncClient
    def mock_client(**kwargs):
        def fail(request):
            raise httpx.ConnectError("unavailable", request=request)
        return original_client(transport=httpx.MockTransport(fail), **kwargs)
    monkeypatch.setattr(main.httpx, "AsyncClient", mock_client)
    assert client.get("/api/voice/owner/status").status_code == 503
    assert client.put("/api/settings", json={"owner_voice_only": True}).status_code == 503
    assert client.get("/api/settings").json()["owner_voice_only"] is False


def test_owner_policy_change_closes_old_socket_but_failed_update_does_not(client, monkeypatch):
    from server import pipecat_voice
    async def echo_voice(socket, _store, _session):
        try:
            while True:
                await socket.send_text(await socket.receive_text())
        except (WebSocketDisconnect, RuntimeError):
            pass
    async def unavailable(_address):
        return {"enabled": True, "ready": True, "enrolled": False}
    async def ready(_address):
        return {"enabled": True, "ready": True, "enrolled": True}
    monkeypatch.setattr(pipecat_voice, "run_voice", echo_voice)
    monkeypatch.setattr(main, "get_owner_status", unavailable)
    session = client.post("/api/sessions").json()["id"]
    with client.websocket_connect(f"/ws/voice?session_id={session}") as ws:
        assert client.put("/api/settings", json={"owner_voice_only": True}).status_code == 409
        ws.send_text("still open")
        assert ws.receive_text() == "still open"
        monkeypatch.setattr(main, "get_owner_status", ready)
        assert client.put("/api/settings", json={"owner_voice_only": True}).status_code == 200
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
        assert closed.value.code == 4001
    with client.websocket_connect(f"/ws/voice?session_id={session}") as ws:
        assert client.put("/api/settings", json={"owner_voice_only": False}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_speech_address_and_enrollment_deletion_close_connections(client, monkeypatch):
    from server import pipecat_voice
    async def hold(socket, _store, _session):
        try:
            await socket.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            pass
    monkeypatch.setattr(pipecat_voice, "run_voice", hold)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"deleted": True})), **kwargs))
    session = client.post("/api/sessions").json()["id"]
    with client.websocket_connect(f"/ws/voice?session_id={session}") as ws:
        assert client.put("/api/settings", json={"speech_base_url": "http://127.0.0.1:9999"}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    with client.websocket_connect(f"/ws/voice?session_id={session}") as ws:
        assert client.delete("/api/voice/owner/enrollment").status_code == 200
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()



