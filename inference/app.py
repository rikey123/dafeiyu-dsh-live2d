from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import openvino_genai as genai
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("dafeiyu.local_llm")
ROOT = Path(os.environ.get("DAFEIYU_ROOT", Path(__file__).resolve().parent.parent))
MODEL_DIR = Path(os.environ.get("DAFEIYU_LLM_MODEL_DIR", ROOT / "models" / "qwen3-1.7b-int4"))
MODEL_ID = os.environ.get("DAFEIYU_LLM_MODEL_ID", "qwen3-1.7b-int4")
DEVICE = os.environ.get("DAFEIYU_LLM_DEVICE", "CPU").upper()


class Runtime:
    def __init__(self):
        self.status = "loading"
        self.detail = "正在加载模型"
        self.pipeline = None
        self.semaphore = asyncio.Semaphore(1)

    def load(self):
        try:
            if not (MODEL_DIR / "openvino_model.xml").is_file() or not (MODEL_DIR / "openvino_model.bin").is_file():
                raise FileNotFoundError(f"模型文件不完整: {MODEL_DIR}")
            pipeline = genai.LLMPipeline(str(MODEL_DIR), DEVICE)
            # Trigger first-run kernels before declaring the service ready.
            if os.environ.get("DAFEIYU_LLM_WARMUP", "1") != "0":
                prompt = pipeline.get_tokenizer().apply_chat_template(
                    [{"role": "user", "content": "你好"}], True, extra_context={"enable_thinking": False})
                pipeline.generate(prompt, max_new_tokens=1, do_sample=False, apply_chat_template=False)
            self.pipeline = pipeline
            self.status = "ready"
            self.detail = "模型已加载"
        except Exception as error:
            log.exception("Failed to load local LLM")
            self.status = "error"
            self.detail = f"模型加载失败: {error}"


runtime = Runtime()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # A daemon thread prevents a slow device compilation from blocking HTTP health checks.
    threading.Thread(target=runtime.load, name="llm-loader", daemon=True).start()
    yield


app = FastAPI(title="Dafeiyu local OpenVINO LLM", lifespan=lifespan)


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=8000)


class Completion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    messages: list[Message] = Field(min_length=1, max_length=40)
    stream: bool = False
    max_tokens: int = Field(default=256, ge=1, le=512)
    temperature: float = Field(default=0.7, ge=0, le=2)


@app.get("/health")
def health():
    return {"status": runtime.status, "ready": runtime.status == "ready", "device": DEVICE,
            "model": MODEL_ID, "detail": runtime.detail}


@app.get("/v1/models")
def models():
    if runtime.status != "ready":
        raise HTTPException(503, runtime.detail)
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}]}


def sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def stream_completion(body: Completion):
    await runtime.semaphore.acquire()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    stop = threading.Event()
    completion_id = "chatcmpl-" + uuid.uuid4().hex
    created = int(time.time())

    def enqueue(item) -> bool:
        if stop.is_set():
            return False
        future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
        while not stop.is_set():
            try:
                future.result(timeout=0.1)
                return True
            except FutureTimeout:
                continue
            except Exception:
                return False
        future.cancel()
        return False

    def work():
        try:
            history = [entry.model_dump() for entry in body.messages]
            prompt = runtime.pipeline.get_tokenizer().apply_chat_template(
                history, True, extra_context={"enable_thinking": False})

            def on_token(text: str) -> int:
                if stop.is_set() or (text and not enqueue(("token", text))):
                    return genai.StreamingStatus.CANCEL.value
                return genai.StreamingStatus.RUNNING.value

            kwargs = {"max_new_tokens": body.max_tokens, "apply_chat_template": False,
                      "do_sample": body.temperature > 0}
            if body.temperature > 0:
                kwargs["temperature"] = body.temperature
            runtime.pipeline.generate(prompt, streamer=on_token, **kwargs)
            enqueue(("done", None))
        except Exception as error:
            log.exception("Local LLM generation failed")
            enqueue(("error", str(error)))
        finally:
            try:
                loop.call_soon_threadsafe(runtime.semaphore.release)
            except RuntimeError:
                pass

    threading.Thread(target=work, name="llm-generation", daemon=True).start()
    try:
        while True:
            kind, value = await queue.get()
            if kind == "token":
                yield sse({"id": completion_id, "object": "chat.completion.chunk", "created": created,
                           "model": MODEL_ID, "choices": [{"index": 0, "delta": {"content": value}, "finish_reason": None}]})
            elif kind == "error":
                yield sse({"error": {"message": "本地模型生成失败，请查看服务日志。", "type": "inference_error"}})
                break
            else:
                yield sse({"id": completion_id, "object": "chat.completion.chunk", "created": created,
                           "model": MODEL_ID, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
                yield "data: [DONE]\n\n"
                break
    finally:
        stop.set()


@app.post("/v1/chat/completions")
async def completions(body: Completion):
    if runtime.status != "ready":
        raise HTTPException(503, runtime.detail)
    if body.model != MODEL_ID:
        raise HTTPException(404, "指定的本地模型不存在")
    if sum(len(entry.content) for entry in body.messages) > 24000:
        raise HTTPException(400, "对话上下文过长")
    if not body.stream:
        raise HTTPException(400, "本地服务目前仅支持 stream=true")
    return StreamingResponse(stream_completion(body), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
