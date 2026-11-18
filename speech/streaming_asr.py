"""Optional unverified online ASR preview; never an owner or final decision."""

import asyncio
import json
import logging
import os
from pathlib import Path

from dafeiyu_paths import models_dir

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
log = logging.getLogger("speech.streaming")
_client_lock = asyncio.Lock()
_recognizer = None
MODEL_FILES = ("tokens.txt", "encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.onnx", "joiner-epoch-99-avg-1.int8.onnx")


def model_path():
    return Path(os.environ.get("DAFEIYU_STREAM_ASR_MODEL", str(models_dir(Path(__file__).resolve().parent.parent) / "streaming-zipformer-zh-en")))


def status():
    missing = [name for name in MODEL_FILES if not (model_path() / name).is_file()]
    return {"enabled": os.environ.get("DAFEIYU_STREAM_ASR", "0") == "1", "files_present": not missing, "missing_files": missing, "loaded": _recognizer is not None, "device": "CPU" if _recognizer is not None else None}


async def native_call(function):
    task = asyncio.create_task(asyncio.to_thread(function))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def load_recognizer():
    import sherpa_onnx

    model = model_path()
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(model / "tokens.txt"), encoder=str(model / "encoder-epoch-99-avg-1.int8.onnx"),
        decoder=str(model / "decoder-epoch-99-avg-1.onnx"), joiner=str(model / "joiner-epoch-99-avg-1.int8.onnx"),
        num_threads=2, enable_endpoint_detection=True,
    )


@router.websocket("/v1/audio/stream")
async def stream_asr(socket: WebSocket):
    global _recognizer
    await socket.accept()
    if os.environ.get("DAFEIYU_STREAM_ASR", "0") != "1":
        await socket.close(code=1008, reason="online ASR disabled")
        return
    if _client_lock.locked():
        await socket.close(code=1013, reason="online ASR busy")
        return
    async with _client_lock:
        try:
            if _recognizer is None:
                _recognizer = await native_call(load_recognizer)
            recognizer = _recognizer
            stream = recognizer.create_stream()
            total = 0
            await socket.send_json({"type": "ready", "verified": False, "sample_rate": 16000})
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("text") == "reset":
                    stream = recognizer.create_stream()
                    total = 0
                    continue
                audio = message.get("bytes")
                if not audio or len(audio) % 2 or len(audio) > 16000:
                    await socket.close(code=1003, reason="expected mono PCM16 frames up to 0.5s")
                    break
                total += len(audio)
                if total > 16000 * 2 * 30:
                    await socket.close(code=1009, reason="segment exceeds 30 seconds")
                    break

                def decode():
                    stream.accept_waveform(16000, np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768)
                    while recognizer.is_ready(stream):
                        recognizer.decode_stream(stream)
                    result = json.loads(recognizer.get_result_as_json_string(stream))
                    return result, recognizer.is_endpoint(stream)

                result, endpoint = await native_call(decode)
                event = {"type": "preview", "verified": False, "text": result.get("text", ""), "tokens": result.get("tokens", []), "timestamps": result.get("timestamps", []), "endpoint": endpoint}
                await socket.send_json(event)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("online ASR unavailable")
            try:
                await socket.close(code=1011, reason="online ASR unavailable")
            except RuntimeError:
                pass
