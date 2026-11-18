"""Loopback TTS: prewarmed resident GPU mode, lazy auto/CPU, bounded isolated IPC."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import io
import json
import multiprocessing
import os
from pathlib import Path
import time
import subprocess
from typing import Literal
import wave

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from dafeiyu_paths import home_dir, models_dir
from speech.model_worker import serve

MODEL_NAMES = {"index_tts": "IndexTTS-2.5", "moss_tts": "MOSS-TTS-Nano", "gpt_sovits": "GPT-SoVITS-v5-turbo"}


def model_config(kind):
    prefix = "DAFEIYU_INDEX_" if kind == "index_tts" else "DAFEIYU_MOSS_"
    name = "index-tts-2.5" if kind == "index_tts" else "moss-tts-nano"
    if kind == "gpt_sovits":
        prefix, name = "DAFEIYU_GSV_", "gpt-sovits-v5"
    return {"source": os.getenv(prefix+"SOURCE", str(home_dir() / "source" / name)),
            "model": os.getenv(prefix+"MODEL", str(models_dir() / name)),
            "prompt_wav": os.getenv(prefix+"PROMPT_WAV", ""),
            "prompt_text": os.getenv(prefix+"PROMPT_TEXT", ""),
            "preload": kind in {"index_tts", "gpt_sovits"} and os.getenv("DAFEIYU_GPU_PRELOAD", "1") == "1",
            "idle_seconds": max(60, min(3600, int(os.getenv(prefix+"IDLE_SECONDS", "900" if kind == "gpt_sovits" else "180")))),
            "threads": int(os.getenv(prefix+"THREADS", "4"))}


def check_assets(kind, config):
    source, model = Path(config["source"]), Path(config["model"])
    entry = {"index_tts": "indextts/infer_v2_5.py", "moss_tts": "ort_cpu_runtime.py", "gpt_sovits": "GPT_SoVITS/TTS_infer_pack/TTS.py"}[kind]
    if not (source / entry).is_file():
        return False, "缺少官方推理源文件，请运行模型准备脚本"
    if kind == "index_tts":
        required = ("config.yaml", "gpt.pth", "s2mel.pth", "codec.pth", "feat1.pt", "feat2.pt",
                    "wav2vec2bert_stats.pt", "multilingual_zh_ja_yue_char_del.tiktoken",
                    "hf_cache/w2v-bert-2.0/config.json", "hf_cache/w2v-bert-2.0/preprocessor_config.json",
                    "hf_cache/w2v-bert-2.0/model.safetensors", "hf_cache/campplus_cn_common.bin",
                    "hf_cache/bigvgan/config.json", "hf_cache/bigvgan/bigvgan_generator.pt")
        if any(not (model / name).is_file() or (model / name).stat().st_size == 0 for name in required):
            return False, "缺少 IndexTTS-2.5 模型文件"
        if not config["prompt_wav"] or not Path(config["prompt_wav"]).is_file():
            return False, "请配置有权使用的 IndexTTS 参考录音"
    elif kind == "gpt_sovits":
        required = ("s1v3.ckpt", "gsv-v5-pretrained/s2Gv5turbo.pth", "gsv-v5-pretrained/vocoder.pth",
                    "chinese-hubert-base/config.json", "chinese-hubert-base/pytorch_model.bin",
                    "chinese-roberta-wwm-ext-large/config.json", "chinese-roberta-wwm-ext-large/pytorch_model.bin",
                    "chinese-roberta-wwm-ext-large/tokenizer.json", "g2pw/g2pw.onnx", "g2pw/config.py")
        if any(not (model / name).is_file() or (model / name).stat().st_size == 0 for name in required):
            return False, "缺少 GPT-SoVITS v5 turbo 权重、中文前处理或声码器，请运行 prepare_gpt_sovits.py"
        if not config.get("prompt_text", "").strip() or not config.get("prompt_wav") or not Path(config["prompt_wav"]).is_file():
            return False, "请配置 GPT-SoVITS 参考录音及准确文本（3–10 秒，有权使用）"
        # Upstream has fixed relative paths for vocoder/G2PW; preparation links
        # them to the explicit E: model directory before inference is allowed.
        for relative, expected in (("GPT_SoVITS/pretrained_models", model), ("GPT_SoVITS/text/G2PWModel", model / "g2pw")):
            if (source / relative).resolve() != expected.resolve():
                return False, "GPT-SoVITS 本地资源链接缺失，请重新运行准备脚本"
    else:
        candidates = (model / "browser_poc_manifest.json", model / "MOSS-TTS-Nano-100M-ONNX/browser_poc_manifest.json")
        manifest = next((p for p in candidates if p.is_file()), None)
        if manifest is None:
            return False, "缺少 MOSS ONNX manifest、模型或音频编解码器"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for key in ("tts_meta", "codec_meta", "tokenizer_model"):
                asset = manifest.parent / data["model_files"][key]
                if not asset.is_file():
                    return False, "MOSS ONNX 模型文件不完整"
                if key.endswith("_meta"):
                    meta = json.loads(asset.read_text(encoding="utf-8"))
                    required = list(meta["files"].values())
                    required += [name for names in meta.get("external_data_files", {}).values() for name in names]
                    if any(not (asset.parent / name).is_file() or (asset.parent / name).stat().st_size == 0
                           for name in required):
                        return False, "MOSS ONNX 权重或音频编解码器文件不完整"
        except (OSError, ValueError, KeyError, TypeError):
            return False, "MOSS ONNX manifest 无效"
    return True, "模型文件已配置，等待加载并验证设备"


class ModelHost:
    def __init__(self, kind, config):
        self.kind, self.config = kind, config
        self.process = self.pipe = None
        self.metadata = {}
        self.busy = False
        self.last_used = time.monotonic()
        self.last_error = ""
        self.preload = kind in {"index_tts", "gpt_sovits"} and config.get("preload", True)
        self.config = {**config, "preload": self.preload}
        self.state = "unloaded"
        self.preparation_seconds = None
        self.timeout = 180
        self._gpu_checked = 0
        self._gpu_eligible = False

    def stop(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=2)
            else:
                # start() can fail before the process acquires a pid.
                if self.process.pid is not None:
                    self.process.join(timeout=1)
            self.process.close()
        if self.pipe is not None:
            self.pipe.close()
        self.process = self.pipe = None
        self.metadata = {}
        self.state = "error" if self.last_error else "unloaded"

    def health(self):
        configured, detail = check_assets(self.kind, self.config)
        if self.kind in {"index_tts", "gpt_sovits"} and time.monotonic() - self._gpu_checked > 15:
            self._gpu_checked = time.monotonic()
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                                        capture_output=True, text=True, timeout=2,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self._gpu_eligible = result.returncode == 0 and int(result.stdout.splitlines()[0]) >= 6144
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                self._gpu_eligible = False
        # health runs on a pool thread; the event loop may close a worker
        # between the process snapshot and is_alive(). Treat that as unloaded.
        process, metadata = self.process, self.metadata.copy()
        try:
            loaded = process is not None and process.is_alive() and bool(metadata) and self.state not in {"loading", "warming", "error"}
        except ValueError:
            loaded = False
        if not loaded:
            metadata = {}
        return {"model_name": MODEL_NAMES[self.kind], "model_version": {"index_tts": "2.5", "gpt_sovits": "v5turbo", "moss_tts": "100M-ONNX"}[self.kind],
                "backend": metadata.get("backend", {"index_tts": "native-bf16", "gpt_sovits": "native-fp16", "moss_tts": "onnx"}[self.kind]),
                "configured": configured, "ready": loaded, "busy": self.busy,
                "state": "ready" if loaded else "unloaded" if self.state == "ready" else self.state, "preload": self.preload,
                "resident": self.preload and loaded, "warmed_up": bool(metadata.get("warmed_up")),
                "preparation_seconds": self.preparation_seconds,
                "ar_backend": metadata.get("ar_backend"), "cuda_graph_active": metadata.get("cuda_graph_active"),
                "delivery": metadata.get("delivery"),
                "device": metadata.get("device"), "device_requested": "cpu" if self.kind == "moss_tts" else "cuda",
                # Admission uses a hardware memory probe; ready/device still
                # require a successfully loaded worker. No inference is implied.
                "gpu_eligible": configured and self._gpu_eligible and not self.busy,
                "verification": "warmed" if loaded and metadata.get("warmed_up") else "loaded" if loaded else "not_loaded",
                "detail": self.last_error or ("模型已加载并预热，GPU 模式期间常驻显存" if loaded and self.preload else "模型已加载，设备已验证" if loaded else
                    "模型正在加载，请稍候" if self.state == "loading" else "模型正在预热参考音色和推理缓存，请稍候" if self.state == "warming" else detail)}

    async def ensure_loaded(self, deadline):
        if self.process is not None and self.process.is_alive():
            return
        self.stop()
        self.state = "loading"
        started = time.monotonic()
        context = multiprocessing.get_context("spawn")
        self.pipe, child = context.Pipe()
        self.process = context.Process(target=serve, args=(child, self.kind, self.config), daemon=True)
        try:
            self.process.start()
        finally:
            child.close()
        while True:
            kind, value = await self.receive(deadline)
            if kind == "warming":
                self.state = "warming"
                continue
            if kind != "ready":
                raise RuntimeError(str(value))
            if self.preload and (value.get("device") != "cuda" or value.get("warmed_up") is not True):
                raise RuntimeError("GPU 模型未通过加载与预热验证")
            self.metadata = value
            self.preparation_seconds = round(time.monotonic()-started, 3)
            self.state = "ready"
            return

    async def prepare(self):
        if self.busy:
            return
        self.busy = True
        self.last_error = ""
        try:
            configured, detail = check_assets(self.kind, self.config)
            if not configured:
                raise RuntimeError(detail)
            await self.ensure_loaded(time.monotonic()+self.timeout)
        except asyncio.CancelledError:
            self.stop()
            raise
        except Exception as exc:
            self.last_error = str(exc)
            self.stop()
        finally:
            self.busy = False
            self.last_used = time.monotonic()

    async def receive(self, deadline):
        while time.monotonic() < deadline:
            if self.pipe.poll():
                return self.pipe.recv()
            if not self.process.is_alive():
                raise RuntimeError("模型推理进程意外退出，请查看服务日志")
            await asyncio.sleep(.02)
        raise TimeoutError("本地模型加载或合成超过 180 秒")

    async def stream(self, text, voice):
        completed = False
        try:
            deadline = time.monotonic() + self.timeout
            await self.ensure_loaded(deadline)
            self.pipe.send((text, voice))
            total = 0
            while True:
                kind, value = await self.receive(deadline)
                if kind == "done":
                    if not total:
                        raise RuntimeError("模型返回空音频")
                    if isinstance(value, dict):
                        self.metadata = value
                    completed = True
                    self.state = "ready"
                    self.last_error = ""
                    return
                if kind != "audio" or not isinstance(value, bytes) or len(value) % 2:
                    raise RuntimeError(str(value) if kind == "error" else "模型音频格式无效")
                total += len(value)
                if total > 15_000_000:
                    raise RuntimeError("模型音频超过大小限制")
                yield value
        except (RuntimeError, TimeoutError, EOFError, OSError) as exc:
            self.last_error = str(exc)
            raise
        finally:
            if not completed:
                self.stop()
            self.busy = False
            self.last_used = time.monotonic()


class SpeechInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    voice: str = Field(default="default", max_length=200)
    response_format: Literal["pcm", "wav"] = "pcm"


def create_app(kind=None, config=None):
    kind = kind or os.environ.get("DAFEIYU_MODEL_SERVICE", "index_tts")
    if kind not in MODEL_NAMES:
        raise ValueError("unsupported model service")
    host = ModelHost(kind, config or model_config(kind))
    load_tasks = set()

    def schedule_load():
        if host.busy or load_tasks:
            return
        if host.process is not None and host.process.is_alive() and host.metadata and host.state == "ready":
            return
        task = asyncio.create_task(host.prepare(), name="tts-model-preload")
        load_tasks.add(task)
        task.add_done_callback(load_tasks.discard)

    @asynccontextmanager
    async def lifespan(app):
        if host.preload:
            schedule_load()
        async def reap():
            while True:
                await asyncio.sleep(5)
                if host.preload:
                    # Cancellation releases an unsafe/incomplete worker; rebuild
                    # it in the background, never on the next user's sentence.
                    if not host.busy and not host.last_error and (host.process is None or not host.process.is_alive()):
                        schedule_load()
                elif not host.busy and time.monotonic() - host.last_used > host.config.get("idle_seconds", 180):
                    host.stop()
        reaper = asyncio.create_task(reap())
        try:
            yield
        finally:
            reaper.cancel()
            tasks = list(load_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(reaper, *tasks, return_exceptions=True)
            host.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.host = host

    @app.get("/health")
    async def health():
        return await asyncio.to_thread(host.health)

    @app.get("/v1/audio/voices")
    def voices():
        if kind != "moss_tts":
            raise HTTPException(404, "当前模型不提供 MOSS 内置音色")
        from .tts_voices import installed_catalog, VoiceCatalogUnavailable
        try:
            return installed_catalog(host.config["model"])
        except VoiceCatalogUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/v1/model/load", status_code=202)
    async def load_model():
        if not host.preload:
            raise HTTPException(409, "当前服务为按需加载模式，请先切换为显式 GPU 模式")
        configured, detail = check_assets(kind, host.config)
        if not configured:
            raise HTTPException(503, detail)
        schedule_load()
        return await asyncio.to_thread(host.health)

    async def synthesize(value: SpeechInput, request: Request, stream: bool):
        configured, detail = check_assets(kind, host.config)
        if not configured:
            raise HTTPException(503, detail)
        if host.busy:
            raise HTTPException(409, "本地模型正在加载或预热，请等待就绪后重试" if host.state in {"loading", "warming"} else "本地模型正在合成，请稍后重试")
        if host.preload and (host.process is None or not host.process.is_alive() or not host.metadata):
            if not host.last_error:
                schedule_load()
            raise HTTPException(503, host.last_error or "GPU 模型尚未就绪，正在后台准备，请稍候重试")
        if stream and value.response_format != "pcm":
            raise HTTPException(422, "流式端点仅支持 PCM")
        host.busy = True
        source = host.stream(value.input, value.voice)
        try:
            # Preflight the first real audio chunk before sending HTTP 200.
            # Also cancel model loading when the peer disconnects before first audio.
            task = asyncio.create_task(anext(source))
            try:
                while not task.done():
                    if await request.is_disconnected():
                        raise asyncio.CancelledError
                    await asyncio.sleep(.02)
                first = task.result()
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        except BaseException as exc:
            await source.aclose()
            host.busy = False
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            raise HTTPException(503, "本地模型合成失败，请检查 /health 与服务日志") from None

        async def chunks():
            try:
                yield first
                async for audio in source:
                    yield audio
            finally:
                await source.aclose()
        if stream:
            # StreamingResponse closes its body iterator on disconnect. The
            # source finally kills incomplete model work and frees GPU memory.
            return StreamingResponse(chunks(), media_type="audio/pcm", headers={
                "X-Audio-Sample-Rate": "24000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le",
                "Cache-Control": "no-store"})
        audio = b"".join([chunk async for chunk in chunks()])
        if value.response_format == "pcm":
            return Response(audio, media_type="audio/pcm")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(audio)
        return Response(output.getvalue(), media_type="audio/wav")

    @app.post("/v1/audio/speech/stream")
    async def speech_stream(value: SpeechInput, request: Request):
        return await synthesize(value, request, True)

    @app.post("/v1/audio/speech")
    async def speech(value: SpeechInput, request: Request):
        return await synthesize(value, request, False)

    return app


app = create_app()
