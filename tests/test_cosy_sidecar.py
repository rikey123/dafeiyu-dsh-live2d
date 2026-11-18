import asyncio
import queue
import threading
import time
import sys
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from server import cosyvoice_sidecar as sidecar


class FakeProcess:
    instances = []
    def __init__(self, target, args, daemon):
        self.input, self.output, _, self.cancelled = args
        self.alive = False
        self.joined = False
        self.terminated = False
        self.instances.append(self)
    def start(self):
        self.alive = True
        self.output.put(("ready", {"sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "device": "cpu", "text_ack": True}))
        def run():
            texts = []
            while self.alive:
                try:
                    value = self.input.get(timeout=.05)
                except queue.Empty:
                    continue
                if value == "start":
                    texts = []
                elif value is None:
                    self.output.put(("audio", "".join(texts).encode()))
                    self.output.put(("done", None))
                else:
                    sequence, text = value
                    self.output.put(("text_ack", sequence))
                    texts.append(text)
        threading.Thread(target=run, daemon=True).start()
    def is_alive(self):
        return self.alive
    def terminate(self):
        self.terminated = True
        self.alive = False
    def join(self, timeout=None):
        self.joined = True
    def kill(self):
        self.alive = False


class FakeQueue(queue.Queue):
    def cancel_join_thread(self):
        pass
    def close(self):
        pass


class FakeContext:
    Queue = FakeQueue
    Process = FakeProcess
    Event = threading.Event


def wait_joined(process):
    deadline = time.monotonic() + 5
    while not process.joined and time.monotonic() < deadline:
        time.sleep(.01)
    assert process.terminated and process.joined


def test_cancel_preserves_worker_and_admission_recovers(monkeypatch, tmp_path):
    (tmp_path / "cosyvoice3.yaml").touch()
    monkeypatch.setattr(sidecar.mp, "get_context", lambda _: FakeContext())
    monkeypatch.setattr(sidecar, "configuration", lambda: {"model": str(tmp_path), "source": "s", "matcha": "m", "prompt_wav": "p", "prompt_text": "t", "device": "cpu", "version": "3", "precision": "auto"})
    with TestClient(sidecar.app) as client:
        with client.websocket_connect("/v1/tts/bistream") as ws:
            ws.send_json({"type": "init"})
            ready = ws.receive_json()
            assert ready["type"] == "ready" and ready["text_ack"] is True
            running = client.get("/health").json()
            assert running["ready"] and running["loaded"] and running["busy"] and running["device"] == "cpu"
            with client.websocket_connect("/v1/tts/bistream") as busy:
                assert busy.receive_json()["reason"] == "busy"
            ws.send_json({"type": "text", "text": "first"})
            ws.send_json({"type": "text", "text": "second"})
            ws.send_json({"type": "cancel"})
        process = FakeProcess.instances[-1]
        deadline = time.monotonic() + 2
        while client.get("/health").json()["busy"] and time.monotonic() < deadline:
            time.sleep(.01)
        assert client.get("/health").json()["loaded"]
        assert process.is_alive() and not process.terminated
        for text in ("next", "again"):
            with client.websocket_connect("/v1/tts/bistream") as ws:
                ws.send_json({"type": "init"})
                assert ws.receive_json()["type"] == "ready"
                ws.send_json({"type": "text", "text": text})
                assert ws.receive_json() == {"type": "text_ack", "sequence": 1}
                ws.send_json({"type": "end"})
                assert ws.receive_bytes() == text.encode()
                assert ws.receive_json()["type"] == "done"
            assert FakeProcess.instances[-1] is process
    wait_joined(process)


def test_init_rejects_client_prompt_paths(monkeypatch):
    with TestClient(sidecar.app) as client:
        with client.websocket_connect("/v1/tts/bistream") as ws:
            ws.send_json({"type": "init", "prompt_wav": "/etc/passwd"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


@pytest.mark.parametrize("device,precision,expected", [("cpu", "auto", True), ("cuda", "auto", True), ("cpu", "fp16", False), ("cuda", "invalid", False)])
def test_health_rejects_invalid_precision(monkeypatch, tmp_path, device, precision, expected):
    (tmp_path / "cosyvoice3.yaml").touch()
    monkeypatch.setattr(sidecar, "configuration", lambda: {"model": str(tmp_path), "source": "s", "matcha": "m", "prompt_wav": "p", "prompt_text": "t", "device": device, "version": "3", "precision": precision})
    status = sidecar.health()
    assert status["configured"] is expected
    assert status["model_version"] == "3" and status["precision"] is None


def test_health_rejects_wrong_model_version(monkeypatch, tmp_path):
    (tmp_path / "cosyvoice2.yaml").touch()
    monkeypatch.setattr(sidecar, "configuration", lambda: {"model": str(tmp_path), "source": "s", "matcha": "m", "prompt_wav": "p", "prompt_text": "t", "device": "cpu", "version": "3", "precision": "auto"})
    assert not sidecar.health()["configured"]


def test_gpu_probe_threshold_and_warm_reserved(monkeypatch):
    gib = 2**30
    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: True, mem_get_info=lambda: (3 * gib, 8 * gib))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(sidecar, "warm", None)
    eligible, hardware = sidecar.gpu_hardware(True)
    assert not eligible and hardware["reason"] == "insufficient_memory"
    monkeypatch.setattr(sidecar, "warm", (SimpleNamespace(is_alive=lambda: True), None, None, {}, {"reserved_bytes": 4 * gib}))
    eligible, hardware = sidecar.gpu_hardware(True)
    assert eligible and hardware["effective_free_gib"] == 7
    monkeypatch.setenv("DAFEIYU_COSY_MIN_FREE_GIB", "nan")
    eligible, hardware = sidecar.gpu_hardware(True)
    assert not eligible and hardware["reason"] == "probe_failed"


@pytest.mark.parametrize("available,total,free,expected,reason", [
    (False, 0, 0, False, "cuda_unavailable"),
    (True, 7.4, 6.5, False, "insufficient_memory"),
    (True, 8, 5.9, False, "insufficient_memory"),
    (True, 8, 6, True, "eligible"),
])
def test_gpu_probe_admission_boundaries(monkeypatch, available, total, free, expected, reason):
    gib = 2**30
    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: available, mem_get_info=lambda: (int(free * gib), int(total * gib)))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.delenv("DAFEIYU_COSY_MIN_FREE_GIB", raising=False)
    monkeypatch.delenv("DAFEIYU_COSY_MIN_TOTAL_GIB", raising=False)
    monkeypatch.setattr(sidecar, "warm", None)
    eligible, hardware = sidecar.gpu_hardware(True)
    assert eligible is expected and hardware["reason"] == reason


def test_gpu_probe_cache_force_refresh_and_dead_warm(monkeypatch):
    gib = 2**30
    clock = [100.0]
    free = [6 * gib]
    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: True, mem_get_info=lambda: (free[0], 8 * gib))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(sidecar.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sidecar, "_gpu_cache", None)
    monkeypatch.setattr(sidecar, "warm", (SimpleNamespace(is_alive=lambda: False), None, None, {}, {"reserved_bytes": 4 * gib}))
    monkeypatch.delenv("DAFEIYU_COSY_MIN_FREE_GIB", raising=False)
    monkeypatch.delenv("DAFEIYU_COSY_MIN_TOTAL_GIB", raising=False)
    assert sidecar.gpu_hardware()[0]
    free[0] = 3 * gib
    clock[0] += 4.9
    assert sidecar.gpu_hardware()[0]
    eligible, hardware = sidecar.gpu_hardware(True)
    assert not eligible and hardware["effective_free_gib"] == 3
    free[0] = 6 * gib
    clock[0] += 5.1
    assert sidecar.gpu_hardware()[0]


def test_auto_init_rechecks_gpu_and_never_starts_cpu(monkeypatch, tmp_path):
    (tmp_path / "cosyvoice3.yaml").touch()
    monkeypatch.setattr(sidecar, "configuration", lambda: {"model": str(tmp_path), "source": "s", "matcha": "m", "prompt_wav": "p", "prompt_text": "t", "device": "auto", "version": "3", "precision": "auto"})
    monkeypatch.setattr(sidecar, "gpu_hardware", lambda force=False: (not force, {"reason": "insufficient_memory"}))
    before = len(FakeProcess.instances)
    with TestClient(sidecar.app) as client:
        with client.websocket_connect("/v1/tts/bistream") as ws:
            ws.send_json({"type": "init"})
            assert ws.receive_json() == {"type": "error", "reason": "gpu_unavailable"}
    assert len(FakeProcess.instances) == before


def test_worker_constructs_cosy3_once_and_caches_prompt(monkeypatch, tmp_path):
    (tmp_path / "cosyvoice3.yaml").touch()
    calls = []
    class Model:
        def __init__(self, path, fp16):
            calls.append(("construct", path, fp16))
            self.model = SimpleNamespace(device="cpu", fp16=fp16, token_hop_len=25)
            self.sample_rate = 24000
        def add_zero_shot_spk(self, prompt, wav, key):
            calls.append(("prompt", prompt, wav, key))
        def inference_zero_shot(self, texts, *_args, **_kwargs):
            assert self.model.token_hop_len == 25
            self.model.token_hop_len = 100
            calls.append(("inference", list(texts)))
            return iter(())
    module = ModuleType("cosyvoice.cli.cosyvoice")
    module.CosyVoice2 = lambda *_args, **_kwargs: pytest.fail("wrong model")
    module.CosyVoice3 = Model
    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    monkeypatch.setitem(sys.modules, "cosyvoice", ModuleType("cosyvoice"))
    monkeypatch.setitem(sys.modules, "cosyvoice.cli", ModuleType("cosyvoice.cli"))
    monkeypatch.setitem(sys.modules, "cosyvoice.cli.cosyvoice", module)
    incoming, outgoing = queue.Queue(), queue.Queue()
    for value in ("start", (1, "first"), None, "start", (1, "second"), None, "stop"):
        incoming.put(value)
    sidecar.worker(incoming, outgoing, {"model": str(tmp_path), "source": "s", "matcha": "m", "prompt_wav": "p", "prompt_text": "参考语音", "device": "cpu", "version": "3", "precision": "auto"}, threading.Event())
    assert calls == [("construct", str(tmp_path), False), ("prompt", "You are a helpful assistant.<|endofprompt|>参考语音", "p", "local-prompt"), ("inference", ["first"]), ("inference", ["second"])]
    assert [outgoing.get()[0] for _ in range(5)] == ["ready", "text_ack", "done", "text_ack", "done"]


def test_completed_worker_reused_without_cross_session_audio_and_disposed(monkeypatch, tmp_path):
    (tmp_path / "cosyvoice3.yaml").touch()
    monkeypatch.setattr(sidecar.mp, "get_context", lambda _: FakeContext())
    monkeypatch.setattr(sidecar, "configuration", lambda: {"model": str(tmp_path), "source": "s", "matcha": "m", "prompt_wav": "p", "prompt_text": "t", "device": "cpu", "version": "3", "precision": "auto"})
    before = len(FakeProcess.instances)
    with TestClient(sidecar.app) as client:
        assert not client.get("/health").json()["ready"]
        for text in ("first", "second"):
            with client.websocket_connect("/v1/tts/bistream") as ws:
                ws.send_json({"type": "init"})
                assert ws.receive_json()["text_ack"] is True
                ws.send_json({"type": "text", "text": text})
                assert ws.receive_json() == {"type": "text_ack", "sequence": 1}
                ws.send_json({"type": "text", "text": "!"})
                assert ws.receive_json() == {"type": "text_ack", "sequence": 2}
                ws.send_json({"type": "end"})
                assert ws.receive_bytes() == (text + "!").encode()
                assert ws.receive_json()["type"] == "done"
            health = client.get("/health").json()
            assert health["ready"] and health["loaded"] and health["device"] == "cpu"
        assert len(FakeProcess.instances) == before + 1
        process = FakeProcess.instances[-1]
        assert process.is_alive()
    assert process.terminated and process.joined
    assert not sidecar.health()["ready"]


def test_cancel_timeout_discards_unresponsive_worker(monkeypatch, tmp_path):
    (tmp_path / "cosyvoice3.yaml").touch()
    def stalled_start(process):
        process.alive = True
        process.output.put(("ready", {"sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "device": "cpu"}))
    monkeypatch.setattr(FakeProcess, "start", stalled_start)
    monkeypatch.setattr(sidecar, "CANCEL_TIMEOUT", .05)
    monkeypatch.setattr(sidecar.mp, "get_context", lambda _: FakeContext())
    monkeypatch.setattr(sidecar, "configuration", lambda: {"model": str(tmp_path), "source": "s", "matcha": "m", "prompt_wav": "p", "prompt_text": "t", "device": "cpu", "version": "3", "precision": "auto"})
    with TestClient(sidecar.app) as client:
        with client.websocket_connect("/v1/tts/bistream") as ws:
            ws.send_json({"type": "init"})
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "cancel"})
            process = FakeProcess.instances[-1]
            wait_joined(process)
        assert not client.get("/health").json()["loaded"]
        assert not client.get("/health").json()["busy"]



@pytest.mark.asyncio
async def test_cancelled_queue_reader_cannot_steal_completion():
    output = queue.Queue()
    process = SimpleNamespace(is_alive=lambda: True)
    task = asyncio.create_task(sidecar.worker_output(output, process))
    await asyncio.sleep(.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    output.put(("done", 123))
    assert await asyncio.wait_for(sidecar.worker_output(output, process), .2) == ("done", 123)


def test_worker_cancel_finishes_cleanup_and_reuses_model_without_stale_input(monkeypatch, tmp_path):
    (tmp_path / "cosyvoice3.yaml").touch()
    cancelled = threading.Event()
    calls, cleaned = [], []
    class Model:
        def __init__(self, *_args, **_kwargs):
            self.model = SimpleNamespace(device="cpu", fp16=False, token_hop_len=25)
            self.sample_rate = 24000
            calls.append("loaded")
        def add_zero_shot_spk(self, *_args):
            pass
        def inference_zero_shot(self, texts, *_args, **_kwargs):
            assert self.model.token_hop_len == 25
            self.model.token_hop_len = 100
            try:
                for text in texts:
                    calls.append(text)
                    if text == "old":
                        cancelled.set()
                        # Exhausting this generator is required to run cleanup;
                        # closing it early at yield would skip the assertion.
                        yield {"tts_speech": None}
                        cleaned.append("old")
            finally:
                cleaned.append("joined")
    module = ModuleType("cosyvoice.cli.cosyvoice")
    module.CosyVoice2 = module.CosyVoice3 = Model
    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    monkeypatch.setitem(sys.modules, "cosyvoice", ModuleType("cosyvoice"))
    monkeypatch.setitem(sys.modules, "cosyvoice.cli", ModuleType("cosyvoice.cli"))
    monkeypatch.setitem(sys.modules, "cosyvoice.cli.cosyvoice", module)
    incoming, outgoing = queue.Queue(), queue.Queue()
    config = {"model": str(tmp_path), "source": "s", "matcha": "m", "prompt_wav": "p", "prompt_text": "t", "device": "cpu", "version": "3", "precision": "auto"}
    thread = threading.Thread(target=sidecar.worker, args=(incoming, outgoing, config, cancelled), daemon=True)
    thread.start()
    assert outgoing.get(timeout=2)[0] == "ready"
    try:
        for value in ("start", (1, "old"), (2, "stale"), None):
            incoming.put(value)
        assert outgoing.get(timeout=2) == ("text_ack", 1)
        assert outgoing.get(timeout=2)[0] == "done"
        assert cleaned == ["old", "joined"]
        cancelled.clear()
        for value in ("start", (1, "new"), None):
            incoming.put(value)
        assert outgoing.get(timeout=2) == ("text_ack", 1)
        assert outgoing.get(timeout=2)[0] == "done"
        # Cancel a session before any text: no inference or background thread.
        cancelled.set()
        for value in ("start", None):
            incoming.put(value)
        assert outgoing.get(timeout=2)[0] == "done"
    finally:
        incoming.put("stop")
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert calls == ["loaded", "old", "new"]
    assert cleaned == ["old", "joined", "joined"]
    assert outgoing.empty()
