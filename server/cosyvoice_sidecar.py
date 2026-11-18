"""Optional CosyVoice sidecar with bounded cancellation and warm model reuse."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import logging
import math
import os
import queue
import sys
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app):
    yield
    await dispose_warm()


app = FastAPI(lifespan=lifespan)
admission = asyncio.Lock()
warm = None
active_ready = None
MAX_TEXT = 8000
QUEUE_SIZE = 16
CANCEL_TIMEOUT = 8
_gpu_cache = None


def gpu_hardware(force=False):
    global _gpu_cache
    now = time.monotonic()
    if not force and _gpu_cache and now - _gpu_cache[0] < 5:
        return _gpu_cache[1]
    try:
        minimum = float(os.environ.get("DAFEIYU_COSY_MIN_FREE_GIB", "6"))
        total_min = float(os.environ.get("DAFEIYU_COSY_MIN_TOTAL_GIB", "7.5"))
        if not math.isfinite(minimum) or not math.isfinite(total_min) or minimum <= 0 or total_min <= 0:
            raise ValueError("invalid GPU threshold")
        import torch
        available = torch.cuda.is_available()
        free, total = torch.cuda.mem_get_info() if available else (0, 0)
        cached = warm[4] if warm and warm[0].is_alive() else None
        reserved = cached.get("reserved_bytes", 0) if cached else 0
        effective = min(total, free + reserved)
        eligible = available and total >= total_min * 2**30 and effective >= minimum * 2**30
        result = {"cuda_available": available, "total_gib": total / 2**30 if available else None,
                  "free_gib": free / 2**30 if available else None, "effective_free_gib": effective / 2**30 if available else None,
                  "min_free_gib": minimum, "min_total_gib": total_min,
                  "reason": "eligible" if eligible else "cuda_unavailable" if not available else "insufficient_memory"}
    except Exception:
        log.exception("GPU hardware probe failed")
        result = {"cuda_available": False, "total_gib": None, "free_gib": None, "effective_free_gib": None,
                  "min_free_gib": None, "min_total_gib": None, "reason": "probe_failed"}
        eligible = False
    _gpu_cache = (now, (eligible, result))
    return eligible, result


async def dispose_warm():
    global warm
    item, warm = warm, None
    if item:
        process, input_queue, output_queue = item[:3]
        if process.is_alive():
            process.terminate()
        await asyncio.to_thread(process.join, 5)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join)
        for channel in (input_queue, output_queue):
            channel.cancel_join_thread()
            channel.close()


async def worker_output(output_queue, process):
    # A cancelled to_thread(queue.get) can steal the terminal message after the
    # coroutine has stopped. Nonblocking reads leave no orphan queue consumers.
    while True:
        try:
            return output_queue.get_nowait()
        except queue.Empty:
            if not process.is_alive():
                return "error", "worker_exited"
            await asyncio.sleep(.01)


def worker(input_queue, output_queue, config, cancelled):
    try:
        if config["device"] == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        sys.path[:0] = [config["source"], config["matcha"]]
        import numpy as np
        import torch
        from cosyvoice.cli.cosyvoice import CosyVoice2, CosyVoice3
        if config["device"] == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable")
        model_dir = Path(config["model"])
        if not model_dir.is_dir() or not (model_dir / f"cosyvoice{config['version']}.yaml").is_file():
            raise ValueError("model version mismatch")
        use_fp16 = config["precision"] == "fp16" or (config["precision"] == "auto" and config["device"] == "cuda")
        model = (CosyVoice2 if config["version"] == "2" else CosyVoice3)(str(model_dir), fp16=use_fp16)
        prompt = config["prompt_text"]
        if config["version"] == "3" and "<|endofprompt|>" not in prompt:
            prompt = "You are a helpful assistant.<|endofprompt|>" + prompt
        model.add_zero_shot_spk(prompt, config["prompt_wav"], "local-prompt")
        native = model.model
        initial_hop_len = native.token_hop_len
        device = str(native.device)
        precision = "fp16" if model.model.fp16 else "fp32"
        output_queue.put(("ready", {"sample_rate": model.sample_rate, "channels": 1, "format": "pcm_s16le", "device": device, "text_ack": True, "worker_pid": os.getpid(),
                                    "reserved_bytes": torch.cuda.memory_reserved() if config["device"] == "cuda" else 0,
                                    "model_name": model_name(config["version"]), "model_version": config["version"],
                                    "precision_requested": config["precision"], "precision": precision}))

        while True:
            command = input_queue.get()
            if command != "start":
                return
            # Wait for actual text before starting upstream inference. Cancelling
            # an opened but empty session must not launch a model thread.
            first = input_queue.get()
            input_ended = first is None

            def text_stream():
                nonlocal input_ended
                value = first
                first_text = True
                while value is not None:
                    # Once inference has begun, deliver its first text even if a
                    # cancellation races startup. Upstream cannot synthesize an
                    # empty token stream. Subsequent input can be discarded.
                    if not first_text and cancelled.is_set():
                        return
                    first_text = False
                    sequence, text = value
                    output_queue.put(("text_ack", sequence))
                    yield text
                    value = input_queue.get()
                input_ended = True

            if not input_ended and not cancelled.is_set():
                # Upstream grows this value while streaming; reset each turn so
                # a warm model retains its original first-chunk latency.
                native.token_hop_len = initial_hop_len
                for result in model.inference_zero_shot(text_stream(), "", "", zero_shot_spk_id="local-prompt", stream=True):
                    # Exhaust the generator even on cancellation: upstream owns
                    # its inference thread joins and per-request cache cleanup.
                    if cancelled.is_set():
                        continue
                    audio = result["tts_speech"].detach().cpu().numpy().reshape(-1)
                    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
                    if pcm:
                        output_queue.put(("audio", pcm))
            if cancelled.is_set() and not input_ended:
                # Consume through the one end marker before acknowledging idle,
                # so old text cannot become the next turn's command/audio.
                while input_queue.get() is not None:
                    pass
            output_queue.put(("done", torch.cuda.memory_reserved() if config["device"] == "cuda" else 0))
    except BaseException as exc:
        log.exception("CosyVoice worker failed")
        try:
            output_queue.put(("error", "gpu_oom" if type(exc).__name__ == "OutOfMemoryError" else "worker_failed"), timeout=1)
        except queue.Full:
            pass


def configuration():
    return {"model": os.environ.get("DAFEIYU_COSY_MODEL", ""), "source": os.environ.get("DAFEIYU_COSY_SOURCE", ""),
            "matcha": os.environ.get("DAFEIYU_COSY_MATCHA", ""), "prompt_wav": os.environ.get("DAFEIYU_COSY_PROMPT_WAV", ""),
            "prompt_text": os.environ.get("DAFEIYU_COSY_PROMPT_TEXT", ""), "device": os.environ.get("DAFEIYU_COSY_DEVICE", "cpu").lower(),
            "version": os.environ.get("DAFEIYU_COSY_VERSION", "3"), "precision": os.environ.get("DAFEIYU_COSY_PRECISION", "auto").lower()}


def model_name(version):
    return {"2": "CosyVoice2-0.5B", "3": "Fun-CosyVoice3-0.5B-2512"}.get(version)


@app.get("/health")
def health():
    config = configuration()
    configured = config.get("version") in {"2", "3"} and config.get("precision") in {"auto", "fp32", "fp16"} and config["device"] in {"cpu", "cuda", "auto"} and not (config["device"] == "cpu" and config["precision"] == "fp16") and all(config[key] for key in ("model", "source", "matcha", "prompt_wav", "prompt_text")) and (Path(config["model"]) / f"cosyvoice{config['version']}.yaml").is_file()
    eligible, hardware = gpu_hardware() if config["device"] in {"auto", "cuda"} else (False, None)
    warm_config = {**config, "device": "cuda"} if config["device"] == "auto" else config
    cached = warm[4] if warm and warm[0].is_alive() and warm[3] == warm_config else None
    actual = active_ready or cached
    ready = bool(actual)
    return {"configured": configured, "ready": ready, "loaded": ready,
            "worker_pid": actual.get("worker_pid") if ready else None,
            "device": actual.get("device") if ready else None, "device_requested": config["device"],
            "model_name": actual.get("model_name") if ready else model_name(config.get("version")), "model_version": actual.get("model_version") if ready else config.get("version"),
            "precision_requested": config.get("precision"), "precision": actual.get("precision") if ready else None,
            "gpu_eligible": eligible, "hardware": hardware, "effective_device": actual.get("device") if actual else ("cuda" if eligible else None),
            "detail": "模型已在隔离进程中加载。" if ready else "模型将在请求的隔离进程中加载。", "busy": admission.locked()}


@app.websocket("/v1/tts/bistream")
async def bistream(socket: WebSocket):
    global warm, active_ready
    await socket.accept()
    if admission.locked():
        await socket.send_json({"type": "error", "reason": "busy"})
        await socket.close(code=1013)
        return
    async with admission:
        active_ready = None
        process = None
        input_queue = output_queue = None
        completed = False
        ended = False
        cancelled = None
        ready = None
        try:
            first = await asyncio.wait_for(socket.receive_json(), 10)
            if first != {"type": "init"}:
                await socket.close(code=1008)
                return
            config = configuration()
            if not health()["configured"]:
                await socket.send_json({"type": "error", "reason": "not_configured"})
                await socket.close(code=1011)
                return
            if config["device"] == "auto":
                eligible, _ = await asyncio.to_thread(gpu_hardware, True)
                if not eligible:
                    await socket.send_json({"type": "error", "reason": "gpu_unavailable"})
                    return
                config = {**config, "device": "cuda"}
            if warm and warm[0].is_alive() and warm[3] == config:
                process, input_queue, output_queue, _, ready, cancelled = warm
                warm = None
                active_ready = ready
                await socket.send_json({"type": "ready", **ready})
            else:
                await dispose_warm()
                context = mp.get_context("spawn")
                input_queue, output_queue = context.Queue(QUEUE_SIZE), context.Queue(QUEUE_SIZE)
                cancelled = context.Event()
                process = context.Process(target=worker, args=(input_queue, output_queue, config, cancelled), daemon=True)
                process.start()
                ready = None
            cancelled.clear()
            input_queue.put_nowait("start")
            total = 0
            sequence = 0
            async def receive():
                nonlocal ended, total, sequence
                while True:
                    message = await socket.receive_json()
                    kind = message.get("type") if isinstance(message, dict) else None
                    if kind == "cancel":
                        return
                    if kind == "text" and not ended and set(message) == {"type", "text"} and isinstance(message["text"], str) and message["text"]:
                        total += len(message["text"])
                        if total > MAX_TEXT or len(message["text"]) > 1000:
                            raise ValueError("text_limit")
                        sequence += 1
                        input_queue.put_nowait((sequence, message["text"]))
                    elif kind == "end" and not ended and set(message) == {"type"}:
                        input_queue.put_nowait(None)
                        ended = True
                    else:
                        raise ValueError("invalid_message")

            async def send():
                global active_ready
                nonlocal completed, ready
                while True:
                    kind, payload = await worker_output(output_queue, process)
                    if kind == "audio":
                        await socket.send_bytes(payload)
                    elif kind == "ready":
                        ready = payload
                        active_ready = payload
                        await socket.send_json({"type": "ready", **payload})
                    elif kind == "text_ack":
                        await socket.send_json({"type": "text_ack", "sequence": payload})
                    elif kind == "done":
                        ready["reserved_bytes"] = payload
                        completed = True
                        await socket.send_json({"type": "done"})
                        return
                    else:
                        await socket.send_json({"type": "error", "reason": payload if payload == "gpu_oom" else "worker_failed"})
                        return

            tasks = [asyncio.create_task(receive()), asyncio.create_task(send())]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        except (ValueError, queue.Full):
            try:
                await socket.send_json({"type": "error", "reason": "invalid_or_backpressure"})
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            if process and not completed:
                started = time.monotonic()
                cancelled.set()
                try:
                    if not ended:
                        input_queue.put_nowait(None)
                        ended = True
                    async with asyncio.timeout(CANCEL_TIMEOUT):
                        while True:
                            kind, payload = await worker_output(output_queue, process)
                            if kind == "ready":
                                ready = payload
                                active_ready = ready
                            elif kind == "done":
                                ready["reserved_bytes"] = payload
                                completed = True
                                log.info("Cancellation settled in %.3fs; keeping worker pid=%s", time.monotonic() - started, getattr(process, "pid", None))
                                break
                            elif kind == "error":
                                break
                except (TimeoutError, queue.Full):
                    log.warning("Cancellation did not settle within its budget; discarding worker")
            active_ready = None
            if completed and process and process.is_alive() and ready:
                warm = (process, input_queue, output_queue, config, ready, cancelled)
                process = input_queue = output_queue = None
            if process:
                if process.is_alive():
                    process.terminate()
                await asyncio.to_thread(process.join, 5)
                if process.is_alive():
                    process.kill()
                    await asyncio.to_thread(process.join)
            for item in (input_queue, output_queue):
                if item:
                    item.cancel_join_thread()
                    item.close()
            try:
                await socket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("DAFEIYU_COSY_PORT", "8770")))
