"""Speech activity detection independent of speaker enrollment."""

import os
import threading
from pathlib import Path

import numpy as np

from .speaker import VAD, SpeakerUnavailable

_lock = threading.Lock()
_config = None


def speech_activity(audio: np.ndarray) -> dict:
    global _config
    import sherpa_onnx

    with _lock:
        if _config is None:
            model = Path(os.environ.get("DAFEIYU_SPEAKER_VAD", str(VAD)))
            if not model.is_file():
                raise SpeakerUnavailable("Silero VAD 模型不可用")
            config = sherpa_onnx.VadModelConfig(silero_vad=sherpa_onnx.SileroVadModelConfig(model=str(model), threshold=0.35, min_silence_duration=0.3, min_speech_duration=0.05), sample_rate=16000, num_threads=1, provider="cpu")
            if not config.validate():
                raise SpeakerUnavailable("Silero VAD 配置无效")
            _config = config
        detector = sherpa_onnx.VoiceActivityDetector(_config, buffer_size_in_seconds=35)
        for start in range(0, len(audio), 512):
            detector.accept_waveform(audio[start:start + 512])
        detector.flush()
        segments = []
        while not detector.empty():
            segment = detector.front
            start = int(segment.start)
            end = min(len(audio), start + len(segment.samples))
            if end > start:
                segments.append({"start_s": start / 16000, "end_s": end / 16000})
            detector.pop()
    return {"speech_detected": bool(segments), "vad_segments": segments, "vad_model": "silero_vad_v5", "vad_device": "CPU"}
