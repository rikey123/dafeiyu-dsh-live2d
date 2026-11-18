import json
import os
import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from inference import app as module


class FakeTokenizer:
    def apply_chat_template(self, history, add_generation_prompt, extra_context):
        assert history[-1]["content"] == "你好"
        assert add_generation_prompt
        assert extra_context == {"enable_thinking": False}
        return "rendered"


class FakePipeline:
    def get_tokenizer(self):
        return FakeTokenizer()

    def generate(self, prompt, streamer, **kwargs):
        assert prompt == "rendered"
        assert kwargs["apply_chat_template"] is False
        streamer("你好")
        streamer("！")


def test_chat_stream(monkeypatch):
    monkeypatch.setattr(module.runtime, "status", "ready")
    monkeypatch.setattr(module.runtime, "pipeline", FakePipeline())
    monkeypatch.setattr(module.runtime, "load", lambda: None)
    with TestClient(module.app) as client:
        response = client.post("/v1/chat/completions", json={"model": module.MODEL_ID, "stream": True,
                                                               "messages": [{"role": "user", "content": "你好"}]})
        assert response.status_code == 200
        chunks = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
        assert "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks) == "你好！"
        assert "data: [DONE]" in response.text


@pytest.mark.asyncio
async def test_cancel_retains_lock_until_generation_thread_exits(monkeypatch):
    continue_generation = threading.Event()
    callback_status = []

    class SlowPipeline(FakePipeline):
        def generate(self, prompt, streamer, **kwargs):
            streamer("你好")
            continue_generation.wait(3)
            callback_status.append(streamer("旧回复"))

    local_runtime = module.Runtime()
    local_runtime.pipeline = SlowPipeline()
    local_runtime.status = "ready"
    monkeypatch.setattr(module, "runtime", local_runtime)
    body = module.Completion(model=module.MODEL_ID, stream=True,
                             messages=[module.Message(role="user", content="你好")])
    stream = module.stream_completion(body)
    assert "你好" in await anext(stream)
    await stream.aclose()
    assert local_runtime.semaphore.locked()
    continue_generation.set()
    for _ in range(100):
        if not local_runtime.semaphore.locked():
            break
        await asyncio.sleep(0.01)
    assert not local_runtime.semaphore.locked()
    assert callback_status == [module.genai.StreamingStatus.CANCEL.value]


@pytest.mark.skipif(os.environ.get("DAFEIYU_RUN_LLM_TEST") != "1", reason="requires downloaded model")
def test_actual_openvino_model():
    with TestClient(module.app) as client:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and client.get("/health").json()["status"] == "loading":
            time.sleep(0.5)
        health = client.get("/health").json()
        assert health["ready"], health
        response = client.post("/v1/chat/completions", json={"model": module.MODEL_ID, "stream": True,
            "max_tokens": 24, "temperature": 0, "messages": [{"role": "user", "content": "你好，请简短地打招呼。"}]})
        assert response.status_code == 200
        chunks = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
        text = "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)
        assert text.strip(), response.text
        assert "<think>" not in text
        print("\nLocal model output:", ascii(text))
        assert "\ufffd" not in text
