import json
import asyncio
import threading

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from speech import server, streaming_asr


def test_health_distinguishes_files_and_loaded(monkeypatch, tmp_path):
    monkeypatch.setenv("DAFEIYU_STREAM_ASR", "1")
    monkeypatch.setenv("DAFEIYU_STREAM_ASR_MODEL", str(tmp_path))
    monkeypatch.setattr(streaming_asr, "_recognizer", None)
    assert streaming_asr.status()["enabled"] is True
    assert streaming_asr.status()["files_present"] is False
    for name in streaming_asr.MODEL_FILES:
        (tmp_path / name).touch()
    assert streaming_asr.status()["files_present"] is True
    assert streaming_asr.status()["loaded"] is False
    assert streaming_asr.status()["device"] is None
    monkeypatch.setattr(streaming_asr, "_recognizer", object())
    assert streaming_asr.status()["loaded"] is True
    assert streaming_asr.status()["device"] == "CPU"


class FakeStream:
    def accept_waveform(self, rate, samples):
        assert rate == 16000 and len(samples) == 160


class FakeRecognizer:
    def create_stream(self):
        return FakeStream()

    def is_ready(self, stream):
        return False

    def get_result_as_json_string(self, stream):
        return json.dumps({"text": "你好", "tokens": ["你", "好"], "timestamps": [0.1, 0.2]})

    def is_endpoint(self, stream):
        return True


@pytest.mark.asyncio
async def test_cancelled_native_call_waits_until_thread_exits():
    started, release = threading.Event(), threading.Event()
    def work():
        started.set()
        release.wait(2)
    task = asyncio.create_task(streaming_asr.native_call(work))
    assert await asyncio.to_thread(started.wait, 1)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_online_asr_disabled_by_default(monkeypatch):
    monkeypatch.setattr(server.engine, "start", lambda: None)
    monkeypatch.delenv("DAFEIYU_STREAM_ASR", raising=False)
    with TestClient(server.app) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/v1/audio/stream") as socket:
                socket.receive_json()
    assert exc.value.code == 1008


def test_online_asr_preview_is_unverified_and_has_token_times(monkeypatch):
    monkeypatch.setattr(server.engine, "start", lambda: None)
    monkeypatch.setenv("DAFEIYU_STREAM_ASR", "1")
    monkeypatch.setattr(streaming_asr, "_recognizer", FakeRecognizer())
    with TestClient(server.app) as client:
        with client.websocket_connect("/v1/audio/stream") as socket:
            assert socket.receive_json()["verified"] is False
            socket.send_bytes(b"\0\0" * 160)
            event = socket.receive_json()
            assert event == {"type": "preview", "verified": False, "text": "你好", "tokens": ["你", "好"], "timestamps": [0.1, 0.2], "endpoint": True}
            socket.send_bytes(b"x")
            with pytest.raises(WebSocketDisconnect) as exc:
                socket.receive_json()
            assert exc.value.code == 1003
