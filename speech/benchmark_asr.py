"""Compare cached Whisper models on the same local WAV and generated Chinese samples."""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import time
import unicodedata
from pathlib import Path

from dafeiyu_paths import models_dir

from faster_whisper import WhisperModel

from speech.server import Engine, read_wav


def normalized(text: str) -> str:
    text = text.translate(str.maketrans("零一二三四五六七八九", "0123456789"))
    return "".join(c.lower() for c in text if not c.isspace() and not unicodedata.category(c).startswith("P"))


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        row = [i]
        for j, right in enumerate(b, 1):
            row.append(min(row[-1] + 1, prev[j] + 1, prev[j - 1] + (left != right)))
        prev = row
    return prev[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="16 kHz PCM16 input WAV")
    parser.add_argument("--output", type=Path, required=True, help="Result JSON")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--mode", choices=("cpu", "gpu", "sensevoice"), default="cpu")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    engine = Engine()
    engine._init_tts()
    if not engine.tts_state["ready"]:
        raise RuntimeError(engine.tts_state["detail"])
    phrases = [("greeting", "你好，请简单介绍一下你自己。"),
               ("name_and_time", "我叫小林，明天下午三点提醒我开会。"),
               ("name_and_digits", "我的名字是李明，电话号码是一三八零零一三八零零零。")]
    samples = []
    for name, expected in phrases:
        path = args.output.parent / f"asr-benchmark-{name}.wav"
        if args.mode == "cpu":
            audio = args.input.read_bytes() if name == "greeting" else engine.synthesize(expected, "")
            path.write_bytes(audio)
        else:
            audio = path.read_bytes()
        samples.append((name, expected, read_wav(audio), str(path)))
    result = json.loads(args.output.read_text(encoding="utf-8")) if args.mode != "cpu" and args.output.exists() else {
        "method": "TTS-generated Chinese audio, local CPU int8; no physical microphone or background noise; other application processes may be active",
        "platform": platform.platform(), "threads": 4, "tts": engine.tts_state,
        "repeats": args.repeats, "trials": [],
    }
    if args.mode == "sensevoice":
        import sherpa_onnx
        model_dir = models_dir() / "sensevoice"
        start = time.perf_counter()
        model = sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(model_dir / "model.int8.onnx"), tokens=str(model_dir / "tokens.txt"), num_threads=4, language="zh", use_itn=True)
        load_ms = round((time.perf_counter() - start) * 1000)
        def run(audio):
            stream = model.create_stream()
            stream.accept_waveform(16000, audio)
            model.decode_stream(stream)
            return stream.result.text
        run(samples[0][2])
        for name, expected, audio, path in samples:
            timings, texts = [], []
            for _ in range(args.repeats):
                start = time.perf_counter()
                texts.append(run(audio))
                timings.append(round((time.perf_counter() - start) * 1000))
            ref, hyp = normalized(expected), normalized(texts[0])
            row = {"model": "sensevoice-int8", "device": "CPU", "sample": name, "reference": expected,
                   "transcripts": texts, "warm_ms": timings, "warm_median_ms": statistics.median(timings),
                   "normalized_character_error_rate": round(edit_distance(ref, hyp) / len(ref), 3),
                   "audio_seconds": round(len(audio) / 16000, 2), "model_load_ms": load_ms, "wav": path}
            result["trials"].append(row)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(row, ensure_ascii=False), flush=True)
        return
    if args.mode == "gpu":
        import openvino_genai
        for precision, model_dir in (("int8", "whisper-base-openvino"), ("fp16", "whisper-base-fp16-openvino")):
            try:
                start = time.perf_counter()
                model = openvino_genai.WhisperPipeline(str(models_dir() / model_dir), "GPU")
                load_ms = round((time.perf_counter() - start) * 1000)
                model.generate(samples[0][2], language="zh", task="transcribe", max_new_tokens=128)
                for name, expected, audio, path in samples:
                    timings, texts = [], []
                    for _ in range(args.repeats):
                        start = time.perf_counter()
                        texts.append(str(model.generate(audio, language="zh", task="transcribe", max_new_tokens=128)).strip())
                        timings.append(round((time.perf_counter() - start) * 1000))
                    ref, hyp = normalized(expected), normalized(texts[0])
                    row = {"model": f"openvino-whisper-base-{precision}", "device": "GPU", "sample": name,
                           "reference": expected, "transcripts": texts, "warm_ms": timings,
                           "warm_median_ms": statistics.median(timings),
                           "normalized_character_error_rate": round(edit_distance(ref, hyp) / len(ref), 3),
                           "audio_seconds": round(len(audio) / 16000, 2), "model_load_ms": load_ms, "wav": path}
                    result["trials"].append(row)
                    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                del model
                gc.collect()
            except Exception as exc:
                result["trials"].append({"model": f"openvino-whisper-base-{precision}", "device": "GPU", "error": str(exc)})
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    for size in ("base", "small"):
        start = time.perf_counter()
        model = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
        load_ms = round((time.perf_counter() - start) * 1000)
        # Prime runtime and caches before measuring warm transcription.
        segments, _ = model.transcribe(samples[0][2], language="zh", beam_size=1, vad_filter=False, condition_on_previous_text=False)
        list(segments)
        for beam in (1, 3):
            for name, expected, audio, path in samples:
                timings = []
                texts = []
                for _ in range(args.repeats):
                    start = time.perf_counter()
                    segments, _ = model.transcribe(audio, language="zh", beam_size=beam, vad_filter=False, condition_on_previous_text=False)
                    text = "".join(s.text for s in segments).strip()
                    timings.append(round((time.perf_counter() - start) * 1000))
                    texts.append(text)
                ref, hyp = normalized(expected), normalized(texts[0])
                row = {"model": size, "beam_size": beam, "sample": name, "reference": expected, "transcripts": texts,
                       "warm_ms": timings, "warm_median_ms": statistics.median(timings),
                       "normalized_character_error_rate": round(edit_distance(ref, hyp) / len(ref), 3),
                       "audio_seconds": round(len(audio) / 16000, 2), "model_load_ms": load_ms, "wav": path}
                result["trials"].append(row)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(row, ensure_ascii=False), flush=True)
        del model
        gc.collect()


if __name__ == "__main__":
    main()
