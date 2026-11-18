"""Optional local speaker similarity. This is not identity authentication."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dafeiyu_paths import data_dir, models_dir, home_dir
import tempfile
import threading

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODEL = Path(os.environ.get("DAFEIYU_SPEAKER_MODEL", str(models_dir(ROOT) / "speaker-eres2net/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")))
_home_vad = home_dir(ROOT) / "public/vad/silero_vad_v5.onnx"
_source_vad = ROOT / "web/public/vad/silero_vad_v5.onnx"
# A source deployment may already own this public asset. Installed packages
# contain neither it nor a model fallback; explicit preparation writes HOME.
_default_vad = _home_vad if os.environ.get("DAFEIYU_HOME") and (_home_vad.is_file() or not _source_vad.is_file()) else _source_vad
VAD = Path(os.environ.get("DAFEIYU_SPEAKER_VAD", str(_default_vad)))
PROFILE = Path(os.environ.get("DAFEIYU_SPEAKER_PROFILE", str(data_dir(ROOT) / "speaker-owner.json")))
MIN_VOICED_SECONDS = 2.0
THRESHOLD = 0.65
MAX_SPEAKER_PENDING = 3
_admission = threading.BoundedSemaphore(MAX_SPEAKER_PENDING)


def limited_call(function, *args):
    if not _admission.acquire(blocking=False):
        raise SpeakerUnavailable("声纹服务繁忙，请稍后重试")
    try:
        return function(*args)
    finally:
        _admission.release()


class SpeakerUnavailable(RuntimeError):
    pass


class SpeakerQuality(ValueError):
    def __init__(self, voiced_seconds: float):
        self.voiced_seconds = voiced_seconds
        super().__init__(f"有效人声不足 {MIN_VOICED_SECONDS:g} 秒，请重新录制。")


class SpeakerService:
    def __init__(self):
        self.lock = threading.Lock()
        self.init_lock = threading.Lock()
        self.extractor = None
        self.vad_config = None
        self.enabled = True
        self.detail = "声纹模型尚未加载"

    def initialize(self):
        with self.init_lock:
            if self.extractor is not None and self.vad_config is not None:
                return
            self._initialize()

    def _initialize(self):
        try:
            import sherpa_onnx
            if not MODEL.is_file() or not VAD.is_file():
                raise FileNotFoundError("缺少模型；请运行 python -m speech.prepare speaker（同时准备 VAD）")
            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL), num_threads=2, provider="cpu")
            if not config.validate():
                raise ValueError("声纹模型配置无效")
            self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            self.vad_config = sherpa_onnx.VadModelConfig(silero_vad=sherpa_onnx.SileroVadModelConfig(model=str(VAD), threshold=0.5, min_silence_duration=0.3, min_speech_duration=0.25), sample_rate=16000, num_threads=1, provider="cpu")
            if not self.vad_config.validate():
                raise ValueError("VAD 模型配置无效")
            self.detail = "本地 CPU 模型可用；相似度不能用于身份认证"
        except Exception as exc:
            self.extractor = None
            self.vad_config = None
            self.detail = f"声纹模型不可用: {exc}"

    def status(self):
        return {"enabled": self.enabled, "ready": self.extractor is not None and self.vad_config is not None,
                "enrolled": PROFILE.is_file(), "detail": self.detail, "threshold": THRESHOLD, "not_authentication": True}

    def embedding(self, audio: np.ndarray) -> tuple[np.ndarray, float]:
        return self._embedding(audio, MIN_VOICED_SECONDS)

    def _embedding(self, audio: np.ndarray, minimum_voiced_seconds: float) -> tuple[np.ndarray, float]:
        if self.extractor is None or self.vad_config is None:
            raise SpeakerUnavailable(self.detail)
        import sherpa_onnx
        vad = sherpa_onnx.VoiceActivityDetector(self.vad_config, buffer_size_in_seconds=35)
        for start in range(0, len(audio), 512):
            vad.accept_waveform(audio[start:start + 512])
        vad.flush()
        pieces = []
        while not vad.empty():
            pieces.append(np.asarray(vad.front.samples, dtype=np.float32).copy())
            vad.pop()
        voiced = np.concatenate(pieces) if pieces else np.empty(0, dtype=np.float32)
        seconds = len(voiced) / 16000
        # VAD can occasionally classify brief noise as speech; require both
        # duration and a minimum fraction of the submitted clip.
        if not len(audio) or seconds < minimum_voiced_seconds or seconds / (len(audio) / 16000) < 0.25:
            raise SpeakerQuality(seconds)
        stream = self.extractor.create_stream()
        stream.accept_waveform(16000, voiced)
        stream.input_finished()
        if not self.extractor.is_ready(stream):
            raise SpeakerQuality(seconds)
        vector = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm <= 0:
            raise SpeakerUnavailable("声纹向量无效")
        return vector / norm, seconds

    def enroll(self, audios: list[np.ndarray]):
        if not 2 <= len(audios) <= 5:
            raise ValueError("请提供 2 至 5 段独立录音。")
        with self.lock:
            vectors = [self.embedding(audio)[0] for audio in audios]
            if any(float(np.dot(vectors[i], vectors[j])) < THRESHOLD for i in range(len(vectors)) for j in range(i)):
                raise ValueError("录入样本的声纹相似度不足，请确认录音来自同一人并重新录制。")
            vector = np.mean(vectors, axis=0)
            norm = np.linalg.norm(vector)
            if not np.isfinite(norm) or norm <= 0:
                raise ValueError("无法创建有效声纹模板。")
            vector /= norm
            PROFILE.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=PROFILE.parent, delete=False) as stream:
                temp = Path(stream.name)
                try:
                    json.dump({"version": 1, "model": MODEL.name, "embedding": vector.tolist(), "samples": len(vectors)}, stream)
                    stream.close()
                    os.replace(temp, PROFILE)
                finally:
                    temp.unlink(missing_ok=True)
        return {"enrolled": True, "samples": len(vectors), "not_authentication": True}

    def verify(self, audio: np.ndarray):
        with self.lock:
            if not self.enabled or self.extractor is None:
                raise SpeakerUnavailable(self.detail)
            if not PROFILE.is_file():
                raise SpeakerUnavailable("尚未录入本人声纹")
            try:
                profile = json.loads(PROFILE.read_text(encoding="utf-8"))
                if profile.get("version") != 1 or profile.get("model") != MODEL.name:
                    raise ValueError("模板与当前模型不兼容")
                reference = np.asarray(profile["embedding"], dtype=np.float32)
                if reference.shape != (self.extractor.dim,) or not np.isfinite(reference).all():
                    raise ValueError("模板数据无效")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise SpeakerUnavailable(f"声纹模板不可用: {exc}") from exc
            try:
                vector, seconds = self.embedding(audio)
            except SpeakerQuality as exc:
                return {"accepted": None, "reason": "insufficient_speech", "score": None, "voiced_seconds": round(exc.voiced_seconds, 2)}
            reference_norm = np.linalg.norm(reference)
            if not np.isfinite(reference_norm) or reference_norm <= 0:
                raise SpeakerUnavailable("声纹模板向量无效")
            score = float(np.dot(reference / reference_norm, vector))
            return {"accepted": score >= THRESHOLD, "reason": "match" if score >= THRESHOLD else "mismatch", "score": round(score, 4), "voiced_seconds": round(seconds, 2)}

    def delete(self):
        with self.lock:
            PROFILE.unlink(missing_ok=True)
        return {"enrolled": False}


speaker = SpeakerService()
