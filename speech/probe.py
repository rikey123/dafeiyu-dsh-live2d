"""Probe device correctness in a child process, including native runtime shutdown."""

import io
import sys
import wave

import numpy as np
import openvino_genai


def main():
    model_path, device = sys.argv[1:]
    with wave.open(io.BytesIO(sys.stdin.buffer.read()), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("TTS probe must be mono PCM16")
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if rate != 16000:
        samples = np.interp(np.arange(round(len(samples) * 16000 / rate)) * rate / 16000, np.arange(len(samples)), samples).astype(np.float32)
    pipeline = openvino_genai.WhisperPipeline(model_path, device)
    text = str(pipeline.generate(samples, language="zh", task="transcribe", max_new_tokens=64)).strip()
    if "你好" not in text or "天气" not in text:
        raise RuntimeError(f"unexpected Chinese transcription: {text[:80]!r}")
    print("Chinese ASR probe passed", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
