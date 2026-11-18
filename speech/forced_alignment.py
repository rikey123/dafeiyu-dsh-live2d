"""Optional offline Qwen3 forced alignment; output units are not phonemes."""

import argparse
import json
import math
import time
import wave
from pathlib import Path

from dafeiyu_paths import models_dir

import numpy as np


def read_audio(path):
    with wave.open(str(path), "rb") as wav:
        rate, frames = wav.getframerate(), wav.getnframes()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or rate != 16000 or not 0 < frames <= rate * 30:
            raise ValueError("expected mono 16 kHz PCM16 WAV, at most 30 seconds")
        raw = wav.readframes(frames)
        if len(raw) != frames * 2:
            raise ValueError("truncated WAV")
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768, frames / rate


def validate_items(items, duration):
    result = []
    previous = 0.0
    for item in items:
        text = str(item.text)
        start, end = float(item.start_time), float(item.end_time)
        if not text or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end <= duration + 0.02 or start < previous:
            raise ValueError("aligner returned invalid or unordered intervals")
        result.append({"text": text, "start_s": start, "end_s": end})
        previous = end
    if not result:
        raise ValueError("aligner returned no intervals")
    return result


def align_file(model_path, audio_path, text):
    if not text.strip() or len(text) > 1000:
        raise ValueError("text must contain 1 to 1000 characters")
    if not Path(model_path).is_dir():
        raise ValueError("alignment model directory is missing")
    audio, duration = read_audio(audio_path)
    import torch
    from qwen_asr import Qwen3ForcedAligner
    begin = time.perf_counter()
    aligner = Qwen3ForcedAligner.from_pretrained(str(model_path), dtype=torch.float32, device_map="cpu", local_files_only=True)
    loaded = time.perf_counter()
    aligned = aligner.align(audio=(audio, 16000), text=text, language="Chinese")
    items = validate_items(aligned[0].items, duration)
    return {"engine": "Qwen3-ForcedAligner-0.6B", "device": "CPU", "unit": "chinese_character_or_word", "phoneme_timestamps": None, "audio_duration_s": duration, "model_load_s": loaded - begin, "inference_s": time.perf_counter() - loaded, "items": items}


def main():
    parser = argparse.ArgumentParser(description="Offline Chinese character/word forced alignment")
    parser.add_argument("wav")
    parser.add_argument("text")
    parser.add_argument("--model", default=str(models_dir(Path(__file__).resolve().parent.parent) / "qwen3-forced-aligner-0.6b"))
    args = parser.parse_args()
    print(json.dumps(align_file(args.model, args.wav, args.text), ensure_ascii=False))


if __name__ == "__main__":
    main()
