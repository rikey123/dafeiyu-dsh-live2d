"""GPU enable-time preparation, without requiring hardware in unit tests."""
import asyncio
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import server.model_tts_sidecar as sidecar


class Process:
    pid = 123

    def __init__(self, **kwargs):
        self.alive = False
        self.terminated = False

    def start(self): self.alive = True
    def is_alive(self): return self.alive
    def terminate(self): self.terminated = True; self.alive = False
    def join(self, timeout): pass
    def close(self): pass


class Pipe:
    def close(self): pass


@pytest.fixture
def assets(monkeypatch):
    monkeypatch.setattr(sidecar, "check_assets", lambda *args: (True, "configured"))
    monkeypatch.setattr(sidecar.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="16000"))


@pytest.mark.parametrize("mode", ["gpu", "auto", "cpu", "api"])
def test_only_explicit_gpu_preloads(monkeypatch, mode):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    configure = importlib.import_module("voice_mode").configure_voice_mode
    env = {"DAFEIYU_GPU_PRELOAD": "stale"}
    configure(env, set(), settings={"tts_mode": mode})
    assert env["DAFEIYU_GPU_PRELOAD"] == ("1" if mode == "gpu" else "0")


@pytest.mark.parametrize("device,pcm,expected", [("cuda", b"\0\1", ["warming", "ready"]),
    ("cpu", b"\0\1", ["warming", "error"]), ("cuda", b"", ["warming", "error"])])
def test_worker_warms_before_ready_and_discards_pcm(monkeypatch, device, pcm, expected):
    from speech.model_worker import serve
    events, calls = [], []
    class Engine:
        metadata = {"device": device}
        def stream(self, text, voice):
            calls.append((text, voice))
            yield pcm
    class WorkerPipe:
        def send(self, value): events.append(value)
        def recv(self): raise EOFError
        def close(self): pass
    monkeypatch.setitem(sys.modules, "speech.model_engines", SimpleNamespace(create_engine=lambda *a: Engine()))
    monkeypatch.setattr("os.chdir", lambda *a: None)
    serve(WorkerPipe(), "gpt_sovits", {"source": ".", "preload": True})
    assert [event[0] for event in events] == expected
    assert len(calls) == 1
    if expected[-1] == "ready":
        assert events[-1][1]["warmed_up"] is True


@pytest.mark.asyncio
async def test_preparation_states_require_verified_warm_cuda(monkeypatch, assets):
    host = sidecar.ModelHost("gpt_sovits", {"preload": True})
    spawned = []
    def spawn(**kwargs):
        process = Process(**kwargs)
        spawned.append(process)
        return process
    monkeypatch.setattr(sidecar.multiprocessing, "get_context", lambda *a: SimpleNamespace(
        Pipe=lambda: (Pipe(), Pipe()), Process=spawn))
    states = []
    messages = iter([("warming", None), ("ready", {"device": "cuda", "warmed_up": True})])
    async def receive(deadline):
        health = host.health()
        states.append(health["state"])
        assert not health["ready"] and health["device"] is None and not health["resident"]
        return next(messages)
    monkeypatch.setattr(host, "receive", receive)
    await host.prepare()
    assert states == ["loading", "warming"]
    health = host.health()
    assert health["ready"] and health["resident"] and health["warmed_up"]
    await host.prepare()
    assert len(spawned) == 1
    host.stop()
    assert spawned[0].terminated and not host.health()["ready"]


@pytest.mark.parametrize("metadata", [{"device": "cpu", "warmed_up": True}, {"device": "cuda"}])
@pytest.mark.asyncio
async def test_failed_preparation_is_not_ready(monkeypatch, assets, metadata):
    host = sidecar.ModelHost("gpt_sovits", {"preload": True})
    monkeypatch.setattr(sidecar.multiprocessing, "get_context", lambda *a: SimpleNamespace(
        Pipe=lambda: (Pipe(), Pipe()), Process=Process))
    async def receive(deadline): return "ready", metadata
    monkeypatch.setattr(host, "receive", receive)
    await host.prepare()
    assert host.process is None and not host.busy
    assert host.health()["state"] == "error"
    assert not host.health()["ready"] and not host.health()["resident"]


@pytest.mark.asyncio
async def test_spawn_failure_cleans_unstarted_process(monkeypatch, assets):
    host = sidecar.ModelHost("gpt_sovits", {"preload": True})
    class FailedProcess(Process):
        pid = None
        def start(self): raise OSError("spawn failed")
        def join(self, timeout): raise AssertionError("cannot join an unstarted process")
    monkeypatch.setattr(sidecar.multiprocessing, "get_context", lambda *a: SimpleNamespace(
        Pipe=lambda: (Pipe(), Pipe()), Process=FailedProcess))
    await host.prepare()
    assert host.process is None and host.last_error == "spawn failed" and not host.busy


@pytest.mark.asyncio
async def test_eager_startup_idempotency_busy_admission_and_shutdown(monkeypatch, assets):
    app = sidecar.create_app("gpt_sovits", {"preload": True})
    host = app.state.host
    started, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def load(deadline):
        calls.append(True)
        host.state = "warming"
        started.set()
        await finish.wait()
        host.process = Process()
        host.process.start()
        host.metadata = {"device": "cuda", "warmed_up": True}
        host.state = "ready"
    monkeypatch.setattr(host, "ensure_loaded", load)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), 1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/health")).json()["state"] == "warming"
            for _ in range(3):
                assert (await client.post("/v1/model/load")).status_code == 202
            assert (await client.post("/v1/audio/speech", json={"input": "hello"})).status_code == 409
            assert len(calls) == 1
            finish.set()
            for _ in range(10):
                await asyncio.sleep(.01)
                if not host.busy: break
            assert (await client.get("/health")).json()["ready"]
            assert (await client.post("/v1/model/load")).status_code == 202
            assert len(calls) == 1
            worker = host.process
    assert worker.terminated and host.process is None


@pytest.mark.asyncio
async def test_shutdown_cancels_background_preparation(monkeypatch, assets):
    app = sidecar.create_app("gpt_sovits", {"preload": True})
    started = asyncio.Event()
    async def load(deadline):
        app.state.host.process = Process()
        app.state.host.process.start()
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(app.state.host, "ensure_loaded", load)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), 1)
        worker = app.state.host.process
    assert worker.terminated and not app.state.host.busy


def test_lazy_mode_does_not_preload_or_accept_explicit_load(assets):
    app = sidecar.create_app("gpt_sovits", {"preload": False})
    with TestClient(app) as client:
        assert client.get("/health").json()["state"] == "unloaded"
        assert client.post("/v1/model/load").status_code == 409
        assert app.state.host.process is None


@pytest.mark.parametrize("preload", [True, False])
@pytest.mark.asyncio
async def test_only_lazy_workers_are_reaped_when_idle(assets, preload):
    app = sidecar.create_app("gpt_sovits", {"preload": preload, "idle_seconds": 0})
    host = app.state.host
    host.process = worker = Process()
    worker.start()
    host.metadata = {"device": "cuda", "warmed_up": True}
    host.state, host.last_used = "ready", 0
    async with app.router.lifespan_context(app):
        await asyncio.sleep(5.1)
        assert worker.is_alive() is preload
        assert host.health()["resident"] is preload


@pytest.mark.asyncio
async def test_failed_preload_can_be_explicitly_retried(monkeypatch, assets):
    app = sidecar.create_app("gpt_sovits", {"preload": True})
    host, calls = app.state.host, []
    async def load(deadline):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("warmup failed")
        host.process = Process()
        host.process.start()
        host.metadata = {"device": "cuda", "warmed_up": True}
        host.state = "ready"
    monkeypatch.setattr(host, "ensure_loaded", load)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(.01)
        assert host.health()["state"] == "error"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/v1/audio/speech", json={"input": "hello"})).status_code == 503
            assert len(calls) == 1
            assert (await client.post("/v1/model/load")).status_code == 202
            await asyncio.sleep(.01)
            assert host.health()["ready"] and not host.last_error and len(calls) == 2


@pytest.mark.parametrize("mode,model,preload,status", [
    ("cpu", "GPT-SoVITS-v5-turbo", True, 409),
    ("api", "GPT-SoVITS-v5-turbo", True, 409),
    ("gpu", "IndexTTS-2.5", True, 409),
    ("gpu", "GPT-SoVITS-v5-turbo", False, 409),
    ("gpu", "GPT-SoVITS-v5-turbo", True, 202),
])
def test_gateway_preparation_validates_saved_mode_and_service(tmp_path, monkeypatch, mode, model, preload, status):
    from server import main
    from server.storage import Store
    store = Store(tmp_path)
    store.update_settings({"tts_mode": mode, "gpu_tts_model": "gpt_sovits"})
    monkeypatch.setattr(main, "store", store)
    native, posts = httpx.AsyncClient, []
    def handler(request):
        if request.method == "POST": posts.append(str(request.url))
        return httpx.Response(200, json={"model_name": model, "preload": preload})
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kw: native(transport=httpx.MockTransport(handler), **kw))
    try:
        with TestClient(main.app) as client:
            assert client.post("/api/tts/load").status_code == status
        assert bool(posts) is (status == 202)
    finally:
        store.db.close()
