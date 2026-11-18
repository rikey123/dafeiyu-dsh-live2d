import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from pipecat.frames.frames import LLMContextFrame, LLMFullResponseStartFrame, LLMFullResponseEndFrame, LLMTextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from server import main
from server.dsh import BridgeClient, ProjectionStore
from server.dsh_llm import DSHLLMService
from server.playback import PlaybackLedger
from server.storage import Store


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("DAFEIYU_HARNESS", "dsh")
    monkeypatch.setenv("DAFEIYU_PLUGIN_TOKEN", "plugin-secret")
    monkeypatch.setenv("DAFEIYU_DSH_BRIDGE_TOKEN", "bridge-secret")
    monkeypatch.setenv("DAFEIYU_DSH_BRIDGE_URL", "http://127.0.0.1:1234")
    store = Store(tmp_path)
    store.update_settings({"llm_api_key": "old-secret", "llm_model": "old-model"})
    monkeypatch.setattr(main, "store", store)
    requests = []
    async def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer bridge-secret"
        path = request.url.path
        if path == "/v1/status":
            return httpx.Response(200, json={"ready": True, "provider": "dsh", "model": "host-model", "configured": True})
        if path == "/v1/sessions" and request.method == "GET":
            return httpx.Response(200, json=[{"id": "s1", "title": "host", "created_at": "now"}])
        if path == "/v1/sessions" and request.method == "POST":
            return httpx.Response(200, json={"id": "s1", "title": "host", "created_at": "now"})
        if path.endswith("/messages"):
            return httpx.Response(200, json=[{"role": "user", "content": "host history"}])
        if request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True})
        if path == "/v1/playback":
            return httpx.Response(200, json={"accepted": True})
        return httpx.Response(404)
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(main.dsh, "BridgeClient", lambda: BridgeClient(transport=transport))
    with TestClient(main.app) as client:
        yield client, store, requests, transport


def test_plugin_auth_settings_memory_and_sessions(plugin):
    client, store, requests, _ = plugin
    assert client.get("/api/health").status_code == 401
    assert client.post("/api/memories", json={}).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/voice?session_id=s1"):
            pass
    headers = {"X-Dafeiyu-Plugin-Token": "plugin-secret"}
    assert client.get("/api/health", headers={**headers, "Origin": "http://evil.test"}).status_code == 403
    assert client.get("/api/health", headers={**headers, "Origin": "http://127.0.0.1:3080"}).status_code == 200
    before = len(requests)
    for method, path in (("GET", "/api/memories"), ("POST", "/api/memories"), ("DELETE", "/api/memories/1")):
        assert client.request(method, path, headers=headers).status_code == 410
    assert len(requests) == before
    result = client.get("/api/settings", headers=headers)
    assert result.json()["llm_model"] == "host-model"
    assert result.json()["llm_base_url"] == "dsh://active"
    assert result.json()["memory_owner"] == "dsh"
    assert "old-secret" not in result.text and "bridge-secret" not in result.text
    result = client.put("/api/settings", headers=headers, json={"llm_api_key": "new-secret", "llm_model": "bad", "llm_base_url": "dsh://active", "harness_provider": "dsh", "memory_owner": "dsh", "api_key_set": True, "temperature": .5})
    assert result.status_code == 200, result.text
    assert result.json()["llm_model"] == "host-model" and result.json()["temperature"] == .7
    assert result.json()["llm_temperature_managed"] is True
    with store.lock:
        rows = dict(store.db.execute("SELECT key,value FROM settings"))
    assert json.loads(rows["llm_api_key"]) == "old-secret"
    assert json.loads(rows["llm_model"]) == "old-model"
    assert client.get("/api/sessions", headers=headers).json()[0]["id"] == "s1"
    assert client.post("/api/sessions", headers=headers, json={"session_id": "s1"}).json()["id"] == "s1"
    assert json.loads(requests[-1].content) == {"session_id": "s1"}
    assert client.get("/api/sessions/s1/messages", headers=headers).json()[0]["content"] == "host history"
    assert client.delete("/api/sessions/s1", headers=headers).json() == {"deleted": True}
    assert store.sessions() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("initiative", [False, True])
async def test_llm_protocol_and_generation_id(tmp_path, initiative):
    requests = []
    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if request.url.path == "/v1/voice/turns":
            return httpx.Response(200, json={"accepted": True, "request_id": body["dafeiyu"]["request_id"]})
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n')
    bridge = BridgeClient("http://127.0.0.1:1234", "bridge-secret", transport=httpx.MockTransport(handler))
    settings_store = Store(tmp_path)
    rows = [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"}]
    projection = ProjectionStore(settings_store, "s1", rows, bridge, model="host-model")
    if not initiative:
        projection.add_message("s1", "user", "新问题")
    settings = settings_store.settings(private=True)
    settings["systemone_initiative_max_reply_chars"] = 80
    processor = DSHLLMService(projection, "s1", settings, lambda: initiative)
    output = []
    async def push(frame, *args): output.append(frame)
    processor.push_frame = push
    current = "用户尚未说完" if initiative else "新问题"
    system = settings["system_prompt"] + ("\n用户仍在说话" if initiative else "")
    messages = [{"role": "system", "content": system}, *rows, {"role": "user", "content": current}]
    await processor.process_frame(LLMContextFrame(LLMContext(messages=messages)), FrameDirection.DOWNSTREAM)
    body = requests[0]
    assert body["model"] == "host-model"
    assert "temperature" not in body
    assert body["dafeiyu"]["kind"] == ("initiative" if initiative else "normal")
    assert body["messages"][-1] == {"role": "user", "content": current}
    assert body["dafeiyu"]["confirmed_messages"] == rows
    if not initiative:
        assert output == []
        for event in ({"type": "response.start", "generation_id": "native-attempt", "kind": "normal"},
                      {"type": "response.text", "generation_id": "native-attempt", "kind": "normal", "text": "\u4f60\u597d"},
                      {"type": "response.end", "generation_id": "native-attempt", "kind": "normal"}):
            await processor._event(event)
    start = next(x for x in output if isinstance(x, LLMFullResponseStartFrame))
    expected_generation = body["dafeiyu"]["request_id"] if initiative else "native-attempt"
    assert start.metadata["dsh_request_id"] == expected_generation
    assert start.metadata["generation_id"] == expected_generation
    if initiative:
        assert body["dafeiyu"]["max_reply_chars"] == 80
    else:
        assert "max_reply_chars" not in body["dafeiyu"]
    assert [x.text for x in output if isinstance(x, LLMTextFrame)] == ["你好"]
    assert current not in [row["content"] for row in projection.messages("s1")] if initiative else True


@pytest.mark.asyncio
async def test_playback_prefix_and_interrupt_are_ordered(tmp_path):
    calls = []
    async def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})
    bridge = BridgeClient("http://127.0.0.1:1234", "x", transport=httpx.MockTransport(handle))
    projection = ProjectionStore(Store(tmp_path), "s1", [], bridge)
    ledger = PlaybackLedger(lambda group, text: projection.enqueue_playback(group, text),
                            on_interrupt=lambda group, text: projection.enqueue_playback(group, text, True))
    ledger.begin_generation("request-1")
    ledger.generating("epoch-1")
    turn = ledger.start("epoch-1")
    turn.text = ["已听到"]
    turn.samples, turn.boundary = 10, True
    assert ledger.acknowledge({"epoch": "epoch-1", "consumed_samples": 10, "sample_rate": 24000, "completed": True})
    ledger.interrupt()
    await projection.close()
    assert calls == [{"session_id": "s1", "generation_id": "request-1", "text": "已听到", "interrupted": False},
                     {"session_id": "s1", "generation_id": "request-1", "text": "已听到", "interrupted": True}]

@pytest.mark.asyncio
async def test_moss_delegation_uses_bridge_without_standalone_credentials(tmp_path, monkeypatch):
    from server.moss_live import MossLiveBridge
    requests = []
    async def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "后台答复"}}]})
    bridge_client = BridgeClient("http://127.0.0.1:1234", "bridge-secret", transport=httpx.MockTransport(handle))
    store = Store(tmp_path)
    store.update_settings({"llm_api_key": "old-secret"})
    monkeypatch.setenv("DAFEIYU_HARNESS", "dsh")
    projection = ProjectionStore(store, "s1", [{"role": "user", "content": "先前内容"}], bridge_client)
    class Socket:
        def __init__(self): self.sent = []
        async def send(self, data): self.sent.append(json.loads(data))
    socket = Socket()
    moss = MossLiveBridge(socket, store.settings(private=True), projection, "s1", PlaybackLedger(lambda *_: None))
    await moss.execute("delegate-1", "真正的问题", [], 2)
    body = requests[0]
    assert body["dafeiyu"]["kind"] == "delegation"
    # The native Session supplies canonical context; do not copy the acoustic
    # projection or the standalone persona into a second model history.
    assert body["dafeiyu"]["confirmed_messages"] == []
    assert body["dafeiyu"]["persona"] == ""
    assert body["messages"][-1] == {"role": "user", "content": "真正的问题"}
    assert "old-secret" not in json.dumps(body)
    assert socket.sent[0]["status"] == "completed" and socket.sent[0]["content"] == "后台答复"


@pytest.mark.asyncio
async def test_cancelled_llm_closes_bridge_stream_without_retry(tmp_path):
    entered, closed = asyncio.Event(), asyncio.Event()
    calls = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b""
        async def aclose(self): closed.set()
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())
    client = BridgeClient("http://127.0.0.1:1234", "bridge-secret", transport=httpx.MockTransport(handler))
    store = Store(tmp_path)
    projection = ProjectionStore(store, "s1", [{"role": "user", "content": "问题"}], client)
    processor = DSHLLMService(projection, "s1", store.settings(private=True), lambda: True)
    processor.push_frame = AsyncMock()
    frame = LLMContextFrame(LLMContext(messages=[{"role": "user", "content": "问题"}]))
    task = asyncio.create_task(processor.process_frame(frame, FrameDirection.DOWNSTREAM))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    await asyncio.wait_for(closed.wait(), 1)
    assert len(calls) == 1

def test_real_pipeline_text_and_stop_preserves_event_stream(plugin, monkeypatch):
    import threading
    from pipecat.frames.protobufs import frames_pb2
    from pipecat.processors.frame_processor import FrameProcessor
    from server import pipecat_voice
    client, store, _, _ = plugin
    admitted, closed = threading.Event(), threading.Event()
    bodies, paths, states = [], [], []
    inactive = threading.Event()
    class WaitingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'id: ready-1\ndata: {"type":"ready"}\n\n'
            await asyncio.Event().wait()
        async def aclose(self): closed.set()
    async def handle(request):
        paths.append((request.method, request.url.path))
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json=[])
        if request.url.path == "/v1/voice/turns":
            body = json.loads(request.content)
            bodies.append(body)
            admitted.set()
            return httpx.Response(200, json={"accepted": True, "request_id": body["dafeiyu"]["request_id"]})
        if request.url.path == "/v1/voice/events":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=WaitingStream())
        if request.url.path == "/v1/voice/state":
            states.append(json.loads(request.content))
            if not states[-1]["active"]:
                inactive.set()
            return httpx.Response(200, json={"accepted": True})
        return httpx.Response(200, json={"ready": True, "provider": "dsh", "model": "fixture", "configured": True})
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(main.dsh, "BridgeClient", lambda: BridgeClient("http://127.0.0.1:1234", "bridge-secret", transport=transport))
    class Passthrough(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            await self.push_frame(frame, direction)
    monkeypatch.setattr(pipecat_voice, "create_tts", lambda settings: Passthrough())
    def send(ws, payload):
        frame = frames_pb2.Frame()
        frame.message.data = json.dumps(payload)
        ws.send_bytes(frame.SerializeToString())
    with client.websocket_connect("/ws/voice?session_id=s1", headers={"X-Dafeiyu-Plugin-Token": "plugin-secret"}) as ws:
        send(ws, {"label": "rtvi-ai", "type": "client-ready", "id": "ready", "data": {}})
        while True:
            frame = frames_pb2.Frame.FromString(ws.receive_bytes())
            if frame.WhichOneof("frame") == "message" and json.loads(frame.message.data).get("type") == "bot-ready":
                break
        send(ws, {"label": "rtvi-ai", "type": "send-text", "id": "one", "data": {"content": "question"}})
        assert admitted.wait(10)
        send(ws, {"label": "rtvi-ai", "type": "client-message", "id": "stop", "data": {"t": "voice.stop", "d": {}}})
        while True:
            frame = frames_pb2.Frame.FromString(ws.receive_bytes())
            if frame.WhichOneof("frame") == "message":
                message = json.loads(frame.message.data)
                if message.get("id") == "stop" and message.get("type") == "server-response":
                    assert message["data"]["d"]["stopped"] is True
                    break
        assert not closed.is_set()
        assert len(bodies) == 1
        assert not any(method == "DELETE" or "cancel" in path for method, path in paths)
    assert closed.wait(5) and inactive.wait(5)
    assert len(bodies) == 1 and bodies[0]["dafeiyu"]["kind"] == "normal"
    assert bodies[0]["messages"][-1] == {"role": "user", "content": "question"}
    assert bodies[0]["dafeiyu"]["confirmed_messages"] == []
    assert [state["active"] for state in states] == [True, False]
    assert states[0]["connection_id"] == states[1]["connection_id"]
    assert not any(path == "/v1/playback" or method == "DELETE" or "cancel" in path for method, path in paths)
    assert store.sessions() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    'data: {"error":{"message":"bridge-secret"}}\n\ndata: [DONE]\n\n',
    'event: error\ndata: {"message":"bridge-secret"}\n\ndata: [DONE]\n\n',
    'data: [DONE]\n\n',
    '',
    'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
])
async def test_llm_surfaces_bridge_failure_instead_of_empty_success(tmp_path, payload):
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=payload)
    client = BridgeClient("http://127.0.0.1:1234", "bridge-secret", transport=httpx.MockTransport(handler))
    store = Store(tmp_path)
    projection = ProjectionStore(store, "s1", [], client)
    processor = DSHLLMService(projection, "s1", store.settings(private=True), lambda: True)
    processor.push_frame, processor.push_error = AsyncMock(), AsyncMock()
    await processor.process_frame(LLMContextFrame(LLMContext(messages=[{"role": "user", "content": "question"}])), FrameDirection.DOWNSTREAM)
    processor.push_error.assert_awaited_once_with(error_msg="DSH bridge generation failed")
    assert "bridge-secret" not in str(processor.push_error.call_args)



@pytest.mark.asyncio
async def test_preview_agent_task_error_closes_without_voice_error(tmp_path):
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text='data: {"error":{"code":"AGENT_ERROR"}}\n\n')
    client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handler))
    store = Store(tmp_path)
    projection = ProjectionStore(store, "s1", [], client)
    processor = DSHLLMService(projection, "s1", store.settings(private=True), lambda: True)
    processor.push_frame, processor.push_error = AsyncMock(), AsyncMock()
    await processor.process_frame(LLMContextFrame(LLMContext(messages=[{"role": "user", "content": "question"}])), FrameDirection.DOWNSTREAM)
    processor.push_error.assert_not_awaited()
    assert isinstance(processor.push_frame.await_args_list[-1].args[0], LLMFullResponseEndFrame)


def test_voice_finally_flushes_projection_after_pipeline_error(plugin, monkeypatch):
    from server import pipecat_voice
    client, _, requests, _ = plugin
    projections = []
    async def failure(ws, store, session_id):
        projections.append(store)
        store.enqueue_playback("last-request", "last-confirmed-prefix")
        raise RuntimeError("synthetic pipeline failure")
    monkeypatch.setattr(pipecat_voice, "run_voice", failure)
    with client.websocket_connect("/ws/voice?session_id=s1", headers={"X-Dafeiyu-Plugin-Token": "plugin-secret"}) as ws:
        assert ws.receive()["code"] == 1011
    assert projections[0]._worker.done()
    assert projections[0]._close_task.done()
    playback = [json.loads(request.content) for request in requests if request.url.path == "/v1/playback"]
    assert playback == [{"session_id": "s1", "generation_id": "last-request", "text": "last-confirmed-prefix", "interrupted": False}]


@pytest.mark.asyncio
async def test_projection_close_is_idempotent_and_joins_last_ack(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    bridge = type("Bridge", (), {})()
    calls = []
    async def playback(*args):
        entered.set()
        await release.wait()
        calls.append(args)
    bridge.playback = playback
    projection = ProjectionStore(Store(tmp_path), "s1", [], bridge)
    projection.enqueue_playback("request-1", "prefix")
    await entered.wait()
    closing = asyncio.create_task(projection.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    await projection.close()
    assert calls == [("s1", "request-1", "prefix", False)]
    assert projection._worker.done()


def test_plugin_https_origin_requires_exact_loopback_origin(plugin, monkeypatch):
    client, _, _, _ = plugin
    monkeypatch.setenv("DAFEIYU_DSH_ORIGIN", "https://127.0.0.1:3443")
    assert main.dsh_origin() == "https://127.0.0.1:3443"
    headers = {"X-Dafeiyu-Plugin-Token": "plugin-secret", "Origin": "https://127.0.0.1:3443"}
    assert client.get("/api/health", headers=headers).status_code == 200
    for origin in ("http://127.0.0.1:3443", "https://localhost:3443", "https://127.0.0.1:3444",
                   "https://127.0.0.1:3443/", "https://remote.example:3443", "null", "*"):
        assert client.get("/api/health", headers={**headers, "Origin": origin}).status_code == 403
    for invalid in ("https://remote.example:3443", "https://127.0.0.1", "https://user@127.0.0.1:3443",
                    "https://127.0.0.1:3443/path", "https://127.0.0.1:3443?q=1", "*"):
        monkeypatch.setenv("DAFEIYU_DSH_ORIGIN", invalid)
        assert main.dsh_origin() is None


@pytest.mark.asyncio
async def test_moss_delegated_audio_metadata_and_confirmed_projection(tmp_path):
    from server.moss_live import MossLiveBridge
    calls = []
    async def handle(request):
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": "delegated"}}]})
        return httpx.Response(200, json={"accepted": True})
    bridge_client = BridgeClient("http://127.0.0.1:1234", "secret", transport=httpx.MockTransport(handle))
    store = Store(tmp_path)
    projection = ProjectionStore(store, "s1", [], bridge_client)
    socket = type("Socket", (), {"send": AsyncMock()})()
    ledger = PlaybackLedger(lambda *_: None)
    moss = MossLiveBridge(socket, store.settings(private=True), projection, "s1", ledger)
    moss.push_frame = AsyncMock()
    await moss.execute("delegation-1", "question", [], 2)
    request_id = calls[0][1]["dafeiyu"]["request_id"]
    identity = {"run_id": "native-run", "turn_id": "native-turn", "delegation_id": "delegation-1"}
    await moss.event("response.audio.started", identity)
    await moss.event("response.audio.context", {**identity, "chunk_id": "chunk-1"})
    await moss.audio(bytes(4800))
    frames = [call.args[0] for call in moss.push_frame.call_args_list]
    assert frames and all(frame.metadata["generation_id"] == request_id for frame in frames)
    reply = moss.replies[("native-run", "native-turn")]
    assert reply.group == request_id and ledger.group == request_id
    epoch = next(iter(reply.pending))
    turn = ledger.start(epoch)
    turn.samples, turn.boundary = 2400, True
    await moss.event("output.transcript.done", {**identity, "text": "confirmed spoken result"})
    await moss.event("response.audio.done", identity)
    assert not any(path == "/v1/playback" for path, _ in calls)
    assert await moss.acknowledge({"epoch": epoch, "consumed_samples": 2400, "sample_rate": 24000, "completed": True})
    await projection.close()
    assert calls[-1] == ("/v1/playback", {"session_id": "s1", "generation_id": request_id,
                                        "text": "confirmed spoken result", "interrupted": False})


def test_plugin_status_and_reads_never_use_standalone_llm_or_history(plugin, monkeypatch):
    client, store, _, _ = plugin
    def forbidden(*args, **kwargs):
        raise AssertionError("Standalone history/memory must not be accessed")
    for method in ("memories", "add_memory", "delete_memory", "sessions", "session", "has_session", "messages", "delete_session"):
        monkeypatch.setattr(store, method, forbidden)
    # A poison credential proves settings never fetch/parse the old credential.
    with store.lock, store.db:
        store.db.execute("UPDATE settings SET value=? WHERE key='llm_api_key'", ("not-json",))
    probes = []
    async def handle(request):
        probes.append(request)
        assert request.url.path == "/health"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"asr": {"ready": False}})
    native = httpx.AsyncClient
    def factory(**kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = httpx.MockTransport(handle)
        return native(**kwargs)
    monkeypatch.setattr(main.httpx, "AsyncClient", factory)
    headers = {"X-Dafeiyu-Plugin-Token": "plugin-secret"}
    status = client.get("/api/status", headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()["llm"]["provider"] == "dsh"
    assert status.json()["conversation"]["llm_model"] == "host-model"
    assert "bridge-secret" not in status.text and "old-secret" not in status.text
    assert len(probes) == 3
    assert client.get("/api/settings", headers=headers).status_code == 200
    assert client.get("/api/sessions", headers=headers).status_code == 200
    assert client.get("/api/sessions/s1/messages", headers=headers).status_code == 200
    for method in ("GET", "POST", "DELETE"):
        assert client.request(method, "/api/memories", headers=headers).status_code == 410
