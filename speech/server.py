"""Local speech service. No model is downloaded during server operation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import io
import json
import logging
import os
from pathlib import Path

from dafeiyu_paths import data_dir, models_dir
import subprocess
import sys
import tempfile
import threading
import time
import wave

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from queue import Empty, Full, Queue
from pydantic import BaseModel, Field
from .speaker import SpeakerQuality, SpeakerUnavailable, limited_call, speaker
from .quality import speech_activity

log = logging.getLogger("speech")
ROOT = Path(__file__).resolve().parent.parent
MAX_AUDIO_BYTES = 2_000_000
MAX_AUDIO_SECONDS = 30


class Engine:
    def __init__(self) -> None:
        self.asr_lock = threading.Lock()
        self.tts_lock = threading.Lock()
        self.asr = None
        self.asr_kind = ""
        self.tts = None
        self.tts_kind = ""
        self.asr_state = {"ready": False, "device": None, "detail": "正在加载语音识别模型"}
        self.tts_state = {"ready": False, "device": "CPU", "detail": "正在检测 Windows 语音"}
        self.devices: list[str] = []
        self._npu_error = ""

    def start(self) -> None:
        self._init_tts()
        self._init_asr()

    def _init_asr(self) -> None:
        try:
            import openvino as ov
            self.devices = ov.Core().available_devices
        except Exception as exc:
            self._npu_error = f"OpenVINO 不可用: {exc}"
        model_path = Path(os.environ.get("DAFEIYU_OV_WHISPER", str(models_dir(ROOT) / "whisper-base-openvino")))
        requested = os.environ.get("DAFEIYU_ASR_DEVICE", "AUTO").upper()
        if requested not in {"AUTO", "NPU", "CPU", "GPU"}:
            self.asr_state = {"ready": False, "device": None, "detail": f"无效的 DAFEIYU_ASR_DEVICE: {requested}"}
            return
        cached_failure = self._cached_failure(model_path) if requested == "AUTO" else ""
        if cached_failure:
            self._npu_error = f"上次 NPU 自检失败，24 小时内使用 CPU: {cached_failure}"
        if model_path.is_dir() and requested != "CPU" and not cached_failure:
            device = "NPU" if requested == "AUTO" else requested
            try:
                if device not in self.devices:
                    raise RuntimeError(f"设备 {device} 未被 OpenVINO 枚举；可用设备: {self.devices}")
                if not self.tts_state["ready"]:
                    raise RuntimeError("无法生成中文自检语音；拒绝使用未经验证的推理设备")
                probe = self.synthesize("你好，今天的天气怎么样？", "")
                probe_result = subprocess.run(
                    [sys.executable, "-m", "speech.probe", str(model_path), device],
                    input=probe, capture_output=True, timeout=120, cwd=str(ROOT),
                )
                if probe_result.returncode != 0:
                    details = (probe_result.stdout + probe_result.stderr).decode("utf-8", errors="replace")
                    raise RuntimeError(f"中文语音自检失败 (exit {probe_result.returncode}): {details[-500:]}")
                import openvino_genai
                self.asr = openvino_genai.WhisperPipeline(str(model_path), device)
                self.asr_kind = "openvino"
                self.asr_state = {"ready": True, "device": device, "detail": f"OpenVINO Whisper 已加载并通过中文语音自检: {model_path.name}"}
                return
            except Exception as exc:
                self._npu_error = f"OpenVINO {device} 初始化失败: {exc}"
                log.warning(self._npu_error)
                if requested == "AUTO":
                    self._save_failure(model_path, self._npu_error)
        elif requested in {"NPU", "GPU"} or (requested == "AUTO" and not self._npu_error):
            self._npu_error = f"OpenVINO Whisper 模型未找到: {model_path}"
        if requested in {"NPU", "GPU"} and os.environ.get("DAFEIYU_ASR_FALLBACK", "1") == "0":
            self.asr_state = {"ready": False, "device": requested, "detail": self._npu_error}
            return
        backend = os.environ.get("DAFEIYU_ASR_BACKEND", "auto").lower()
        if backend not in {"auto", "sensevoice", "faster-whisper"}:
            self.asr_state = {"ready": False, "device": None, "detail": f"无效的 DAFEIYU_ASR_BACKEND: {backend}"}
            return
        sense_model = Path(os.environ.get("DAFEIYU_SENSEVOICE_MODEL", str(models_dir(ROOT) / "sensevoice")))
        sense_error = ""
        if backend != "faster-whisper" and (sense_model / "model.int8.onnx").is_file():
            try:
                import sherpa_onnx
                self.asr = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(sense_model / "model.int8.onnx"), tokens=str(sense_model / "tokens.txt"),
                    num_threads=4, language="zh", use_itn=True,
                )
                self.asr_kind = "sensevoice"
                suffix = f"；{self._npu_error}" if self._npu_error else ""
                self.asr_state = {"ready": True, "device": "CPU", "detail": f"sherpa-onnx SenseVoice int8{suffix}"}
                return
            except Exception as exc:
                sense_error = f"SenseVoice 初始化失败: {exc}"
                log.warning(sense_error)
        elif backend == "sensevoice":
            sense_error = f"SenseVoice 模型未找到: {sense_model}"
        if backend == "sensevoice":
            self.asr_state = {"ready": False, "device": "CPU", "detail": sense_error}
            return
        try:
            from faster_whisper import WhisperModel
            local_model = models_dir(ROOT) / "faster-whisper-base"
            model_name = os.environ.get("DAFEIYU_WHISPER_MODEL", str(local_model) if local_model.is_dir() else "base")
            self.asr = WhisperModel(model_name, device="cpu", compute_type="int8", local_files_only=True, cpu_threads=4)
            self.asr_kind = "faster-whisper"
            suffix = "".join(f"；{error}" for error in (self._npu_error, sense_error) if error)
            self.asr_state = {"ready": True, "device": "CPU", "detail": f"faster-whisper {model_name} (int8){suffix}"}
        except Exception as exc:
            self.asr_state = {"ready": False, "device": "CPU", "detail": f"未能加载本地 Whisper 模型: {exc}。{self._npu_error}"}
            log.exception("ASR unavailable")

    @staticmethod
    def _fingerprint(model_path: Path) -> str:
        import openvino
        model_file = model_path / "openvino_decoder_model.xml"
        return f"{model_path.resolve()}|{model_file.stat().st_mtime_ns}|{openvino.__version__}"

    def _cached_failure(self, model_path: Path) -> str:
        if os.environ.get("DAFEIYU_ASR_RETRY") == "1":
            return ""
        try:
            data = json.loads((data_dir(ROOT) / "npu-asr-failure.json").read_text(encoding="utf-8"))
            if data["fingerprint"] == self._fingerprint(model_path) and 0 <= time.time() - data["time"] < 86400:
                return data["reason"]
        except (OSError, ValueError, KeyError, ImportError):
            pass
        return ""

    def _save_failure(self, model_path: Path, reason: str) -> None:
        try:
            path = data_dir(ROOT) / "npu-asr-failure.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"fingerprint": self._fingerprint(model_path), "time": time.time(), "reason": reason}, ensure_ascii=False), encoding="utf-8")
        except (OSError, ImportError):
            log.exception("Unable to cache NPU failure")

    def _init_tts(self) -> None:
        backend = os.environ.get("DAFEIYU_TTS_BACKEND", "vits").lower()
        if backend == "disabled":
            self.tts_state = {"ready": False, "device": None, "detail": "TTS 由独立 IndexTTS / MOSS 服务提供"}
            return
        if backend == "kokoro":
            try:
                from .kokoro import load_kokoro
                self.tts = load_kokoro()
                self.tts_kind = "kokoro"
                self.tts_state = {"ready": True, "device": "CPU", "detail": "sherpa-onnx Kokoro 中英多语，默认中文音色 45"}
            except Exception as exc:
                self.tts_state = {"ready": False, "device": "CPU", "detail": f"Kokoro 初始化失败: {exc}"}
                log.exception("Kokoro unavailable")
            return
        if backend == "zipvoice":
            try:
                from .zipvoice import load_zipvoice
                self.tts, self.zip_reference_text, self.zip_reference_samples, self.zip_reference_rate = load_zipvoice()
                self.tts_kind = "zipvoice"
                self.tts_state = {"ready": True, "device": "CPU", "detail": "sherpa-onnx ZipVoice 本地参考音色"}
            except Exception as exc:
                self.tts_state = {"ready": False, "device": "CPU", "detail": f"ZipVoice 初始化失败: {exc}"}
                log.exception("ZipVoice unavailable")
            return
        if backend != "vits":
            self.tts_state = {"ready": False, "device": None, "detail": f"无效的 DAFEIYU_TTS_BACKEND: {backend}"}
            return
        model = Path(os.environ.get("DAFEIYU_TTS_MODEL", str(models_dir(ROOT) / "sherpa-onnx-vits-zh-ll")))
        sherpa_error = ""
        if (model / "model.onnx").is_file():
            try:
                import sherpa_onnx
                vits = sherpa_onnx.OfflineTtsVitsModelConfig(model=str(model / "model.onnx"), lexicon=str(model / "lexicon.txt"), tokens=str(model / "tokens.txt"))
                config = sherpa_onnx.OfflineTtsConfig(
                    model=sherpa_onnx.OfflineTtsModelConfig(vits=vits, provider="cpu", num_threads=4),
                    rule_fsts=",".join(str(model / n) for n in ("phone.fst", "date.fst", "number.fst")),
                    max_num_sentences=1,
                )
                if not config.validate():
                    raise RuntimeError("模型文件不完整")
                self.tts = sherpa_onnx.OfflineTts(config)
                self.tts_kind = "sherpa"
                self.tts_state = {"ready": True, "device": "CPU", "detail": f"sherpa-onnx VITS: {model.name}"}
                return
            except Exception as exc:
                sherpa_error = f"；sherpa-onnx TTS 初始化失败: {exc}"
                log.warning(sherpa_error)
        if os.name != "nt":
            self.tts_state = {"ready": False, "device": None, "detail": "未找到可用的本地 TTS 模型" + sherpa_error}
            return
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            try:
                voice = win32com.client.Dispatch("SAPI.SpVoice")
                voices = voice.GetVoices()
                names = [voices.Item(i).GetDescription() for i in range(voices.Count)]
                if not names:
                    raise RuntimeError("Windows 没有安装 SAPI 语音")
                preferred = self._choose_voice(voice)
                self.tts_kind = "sapi"
                self.tts_state = {"ready": True, "device": "CPU", "detail": f"Windows SAPI: {preferred}{sherpa_error}", "voices": names}
                del voices, voice
            finally:
                pythoncom.CoUninitialize()
        except Exception as exc:
            self.tts_state = {"ready": False, "device": "CPU", "detail": f"Windows SAPI 不可用: {exc}"}
            log.exception("TTS unavailable")

    @staticmethod
    def _choose_voice(voice, requested: str = "") -> str:
        voices = voice.GetVoices()
        selected = None
        for i in range(voices.Count):
            candidate = voices.Item(i)
            name = candidate.GetDescription()
            if requested and requested.lower() in name.lower():
                selected = candidate
                break
            try:
                language = candidate.GetAttribute("Language").lower().split(";")
            except Exception:
                language = []
            if selected is None and any(code in {"804", "zh-cn"} for code in language):
                selected = candidate
        if requested and selected is None:
            raise ValueError(f"未找到语音: {requested}")
        if selected is not None:
            voice.Voice = selected
        return voice.Voice.GetDescription()

    def transcribe(self, audio: np.ndarray, cancelled: threading.Event | None = None) -> str:
        if not self.asr_state["ready"]:
            raise RuntimeError(self.asr_state["detail"])
        with self.asr_lock:
            if cancelled and cancelled.is_set():
                raise RuntimeError("语音识别已取消")
            if self.asr_kind == "openvino":
                return str(self.asr.generate(audio, language="zh", task="transcribe", max_new_tokens=128)).strip()
            if self.asr_kind == "sensevoice":
                stream = self.asr.create_stream()
                stream.accept_waveform(16000, audio)
                self.asr.decode_stream(stream)
                return stream.result.text.strip()
            segments, _ = self.asr.transcribe(audio, language="zh", beam_size=1, vad_filter=False, condition_on_previous_text=False)
            return "".join(segment.text for segment in segments).strip()

    def generate_sherpa(self, text, sid, speed, callback):
        if self.tts_kind == "zipvoice":
            from .zipvoice import generate_zipvoice
            return generate_zipvoice(self.tts, text, self.zip_reference_text, self.zip_reference_samples, self.zip_reference_rate, speed, callback)
        return self.tts.generate(text, sid=sid, speed=speed, callback=callback)

    def synthesize(self, text: str, voice_name: str, cancelled: threading.Event | None = None, speed: float = 1.0) -> bytes:
        if not self.tts_state["ready"]:
            raise RuntimeError(self.tts_state["detail"])
        with self.tts_lock:
            if cancelled and cancelled.is_set():
                raise RuntimeError("语音合成已取消")
            if self.tts_kind in {"sherpa", "zipvoice", "kokoro"}:
                try:
                    sid = int(voice_name) if voice_name not in {"", "default"} else (45 if self.tts_kind == "kokoro" else 0)
                except ValueError as exc:
                    raise ValueError("sherpa 语音需要数字 speaker ID") from exc
                if sid < 0 or (self.tts_kind == "zipvoice" and sid != 0) or (self.tts_kind in {"sherpa", "kokoro"} and sid >= self.tts.num_speakers):
                    raise ValueError("无效的 speaker ID")
                result = self.generate_sherpa(text, sid, speed, lambda _samples, _progress: 0 if cancelled and cancelled.is_set() else 1)
                if cancelled and cancelled.is_set():
                    raise RuntimeError("语音合成已取消")
                if not result.samples:
                    raise RuntimeError("TTS 没有返回音频")
                samples = np.clip(np.asarray(result.samples), -1, 1)
                out = io.BytesIO()
                with wave.open(out, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(result.sample_rate)
                    wav.writeframes((samples * 32767).astype("<i2").tobytes())
                return out.getvalue()
            if speed != 1.0:
                raise ValueError("当前语音引擎不支持调整语速")
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    path = tmp.name
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                self._choose_voice(speaker, voice_name if voice_name not in {"", "default"} else "")
                stream = win32com.client.Dispatch("SAPI.SpFileStream")
                stream.Open(path, 3, False)
                try:
                    speaker.AudioOutputStream = stream
                    speaker.Speak(text, 0)
                finally:
                    stream.Close()
                output = Path(path).read_bytes()
                del stream, speaker
                return output
            finally:
                if path:
                    Path(path).unlink(missing_ok=True)
                pythoncom.CoUninitialize()


engine = Engine()


class Admission:
    """Bound the active inference and its waiters; cancellation never releases an active lock early."""

    def __init__(self, max_pending: int = 3):
        self.max_pending = max_pending
        self.pending = 0
        self.lock = asyncio.Lock()

    async def _disconnected(self, request: Request) -> bool:
        try:
            return await request.is_disconnected()
        except Exception:
            log.exception("Unable to check speech request connection")
            return True

    async def run(self, request: Request, function, *args):
        if self.pending >= self.max_pending:
            raise HTTPException(503, "语音服务繁忙，请稍后重试")
        self.pending += 1
        acquired = False
        ownership_deferred = False
        cancelled = threading.Event()
        worker = None
        try:
            acquire = asyncio.create_task(self.lock.acquire())
            try:
                async with asyncio.timeout(30):
                    while not acquire.done():
                        done, _ = await asyncio.wait({acquire}, timeout=0.1)
                        if not done and await self._disconnected(request):
                            raise asyncio.CancelledError()
                await acquire
                acquired = True
            except TimeoutError:
                raise HTTPException(503, "语音服务排队超时，请重试") from None
            finally:
                if not acquire.done():
                    acquire.cancel()
                    await asyncio.gather(acquire, return_exceptions=True)
                elif not acquired and not acquire.cancelled() and acquire.exception() is None and acquire.result():
                    self.lock.release()
            if await self._disconnected(request):
                raise asyncio.CancelledError()
            worker = asyncio.create_task(asyncio.to_thread(function, *args, cancelled))
            while not worker.done():
                done, _ = await asyncio.wait({worker}, timeout=0.1)
                if not done and await self._disconnected(request):
                    raise asyncio.CancelledError()
            return await worker
        except asyncio.CancelledError:
            cancelled.set()
            if worker is not None and not worker.done():
                # Keep ownership until the native call exits, even if this task is cancelled again.
                def release_when_done(done):
                    try:
                        done.exception()
                    except BaseException:
                        pass
                    self.lock.release()
                    self.pending -= 1
                worker.add_done_callback(release_when_done)
                acquired = False
                ownership_deferred = True
            raise
        finally:
            if acquired:
                self.lock.release()
            if not ownership_deferred:
                self.pending -= 1


asr_admission = Admission()
tts_admission = Admission()
stream_admission = threading.BoundedSemaphore(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load = asyncio.create_task(asyncio.to_thread(engine.start))
    yield
    await load


app = FastAPI(title="Dafeiyu local speech", lifespan=lifespan)
from .streaming_asr import router as streaming_asr_router, status as streaming_asr_status
app.include_router(streaming_asr_router)


@app.get("/health")
def health():
    return {"status": "ok" if engine.asr_state["ready"] and engine.tts_state["ready"] else "degraded", "asr": engine.asr_state, "tts": engine.tts_state, "devices": engine.devices, "speaker": speaker.status(), "streaming_asr": streaming_asr_status()}


def read_wav(data: bytes) -> np.ndarray:
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
            if channels != 1 or width != 2 or rate != 16000 or frames > MAX_AUDIO_SECONDS * rate or frames <= 0:
                raise ValueError("音频必须是 16 kHz、单声道、16 位 PCM WAV，长度不超过 30 秒")
            raw = wav.readframes(frames)
            if len(raw) != frames * 2:
                raise ValueError("WAV 数据不完整")
            return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    except (wave.Error, EOFError) as exc:
        raise ValueError("无效的 WAV 音频") from exc


@app.get("/v1/speaker/status")
async def speaker_status():
    if speaker.extractor is None:
        await asyncio.to_thread(speaker.initialize)
    return speaker.status()


async def speaker_audio(file: UploadFile) -> np.ndarray:
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "音频文件过大")
    try:
        return read_wav(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/speaker/enroll")
async def speaker_enroll(files: list[UploadFile] = File(...)):
    if not 2 <= len(files) <= 5:
        raise HTTPException(400, "请提供 2 至 5 段独立录音。")
    if speaker.extractor is None:
        await asyncio.to_thread(speaker.initialize)
    try:
        audio = [await speaker_audio(file) for file in files]
        return await asyncio.to_thread(limited_call, speaker.enroll, audio)
    except SpeakerUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/v1/speaker/enrollment")
async def speaker_delete():
    return await asyncio.to_thread(speaker.delete)


@app.post("/v1/speaker/verify")
async def speaker_verify(file: UploadFile = File(...)):
    if speaker.extractor is None:
        await asyncio.to_thread(speaker.initialize)
    try:
        audio = await speaker_audio(file)
        return await asyncio.to_thread(limited_call, speaker.verify, audio)
    except SpeakerUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/audio/transcriptions")
async def transcriptions(request: Request, file: UploadFile = File(...), owner_only: bool = Form(False)):
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "音频文件过大")
    try:
        audio = read_wav(data)
        quality = await asr_admission.run(request, lambda samples, cancelled: speech_activity(samples), audio)
        metadata = {"audio": {"sample_rate": 16000, "channels": 1, "sample_format": "pcm_s16le", "duration_s": len(audio) / 16000}, "quality": quality, "alignment": {"tokens": None, "words": None, "reason": "not_available_for_current_asr"}}
        if not quality["speech_detected"]:
            return {"text": "", "reason": "no_speech", **metadata, **({"speaker": {"accepted": None, "reason": "insufficient_speech"}} if owner_only else {})}
        if owner_only:
            if speaker.extractor is None:
                await asyncio.to_thread(speaker.initialize)
            decision = await asyncio.to_thread(limited_call, speaker.verify, audio)
            if decision["accepted"] is not True:
                return {"text": "", "speaker": decision, **metadata}
        result = await asr_admission.run(request, engine.transcribe, audio)
        return {"text": result, **metadata, **({"speaker": decision} if owner_only else {})}
    except SpeakerUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        log.exception("transcription failed")
        raise HTTPException(503, f"语音识别不可用: {exc}") from exc


class SpeechRequest(BaseModel):
    input: str = Field(min_length=1, max_length=2000)
    voice: str = Field(default="", max_length=200)
    response_format: str = "wav"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


@app.post("/v1/audio/speech/stream")
async def speech_stream(payload: SpeechRequest):
    if engine.tts_kind not in {"sherpa", "zipvoice", "kokoro"} or not engine.tts_state["ready"]:
        raise HTTPException(501, "当前语音引擎不支持增量 PCM")
    if payload.response_format != "pcm":
        raise HTTPException(400, "增量语音仅支持 pcm")
    try:
        sid = int(payload.voice) if payload.voice not in {"", "default"} else (45 if engine.tts_kind == "kokoro" else 0)
    except ValueError as exc:
        raise HTTPException(400, "sherpa 语音需要数字 speaker ID") from exc
    if sid < 0 or (engine.tts_kind == "zipvoice" and sid != 0) or (engine.tts_kind in {"sherpa", "kokoro"} and sid >= engine.tts.num_speakers):
        raise HTTPException(400, "无效的 speaker ID")
    if not stream_admission.acquire(blocking=False):
        raise HTTPException(503, "语音服务繁忙，请稍后重试")
    cancelled = threading.Event()
    chunks: Queue = Queue(maxsize=4)

    def produce():
        def callback(samples, _progress):
            if cancelled.is_set():
                return 0
            pcm = (np.clip(np.asarray(samples), -1, 1) * 32767).astype("<i2").tobytes()
            while not cancelled.is_set():
                try:
                    chunks.put(pcm, timeout=0.1)
                    return 1
                except Full:
                    continue
            return 0
        try:
            with engine.tts_lock:
                if not cancelled.is_set():
                    engine.generate_sherpa(payload.input, sid, payload.speed, callback)
        except Exception as exc:
            log.exception("streaming synthesis failed")
            while not cancelled.is_set():
                try:
                    chunks.put(exc, timeout=0.1)
                    break
                except Full:
                    continue
        finally:
            while not cancelled.is_set():
                try:
                    chunks.put(None, timeout=0.1)
                    break
                except Full:
                    continue
            stream_admission.release()

    async def stream():
        worker = asyncio.create_task(asyncio.to_thread(produce))
        try:
            while True:
                try:
                    item = await asyncio.to_thread(chunks.get, True, 0.2)
                except Empty:
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            cancelled.set()
            # The native call retains tts_lock until it returns; do not cancel its thread.
            worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    return StreamingResponse(stream(), media_type="audio/pcm", headers={"X-Audio-Sample-Rate": str(engine.tts.sample_rate), "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le", "X-Audio-Phonemes": "unavailable", "X-Audio-Phoneme-Timestamps": "unavailable"})


@app.post("/v1/audio/speech")
async def speech(payload: SpeechRequest, request: Request):
    if payload.response_format != "wav":
        raise HTTPException(400, "仅支持 wav")
    try:
        data = await tts_admission.run(request, lambda text, voice, cancelled: engine.synthesize(text, voice, cancelled, speed=payload.speed), payload.input, payload.voice)
        return Response(data, media_type="audio/wav")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        log.exception("speech synthesis failed")
        raise HTTPException(503, f"语音合成不可用: {exc}") from exc
