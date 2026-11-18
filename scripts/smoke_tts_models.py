"""Run real cold/warm local synthesis, record evidence on E:, and release the worker."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

async def run(args):
    from server.model_tts_sidecar import ModelHost, check_assets, model_config
    config = model_config(args.kind)
    configured, detail = check_assets(args.kind, config)
    if not configured:
        raise RuntimeError(detail)
    host = ModelHost(args.kind, config)
    try:
        for run_index in range(args.runs):
            host.busy = True
            start = time.perf_counter()
            audio = bytearray()
            first = None
            async for chunk in host.stream(args.text, "default"):
                if first is None:
                    first = time.perf_counter() - start
                audio.extend(chunk)
            elapsed = time.perf_counter() - start
            import numpy as np
            signal = np.frombuffer(audio, dtype="<i2")
            if len(signal) < 2400 or np.max(np.abs(signal.astype(np.int32))) < 50:
                raise RuntimeError("Synthesis returned empty or silent audio")
            state = "cold" if run_index == 0 else "warm"
            suffix = "" if run_index == 0 else f"-warm-{run_index}"
            output = Path("E:/Dafeiyu/verification") / (args.kind + "-smoke" + suffix + ".wav")
            output.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(output), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(audio)
            report = {"kind": args.kind, "metadata": host.metadata, "text": args.text,
                      "run_state": state, "run_index": run_index, "sample_rate": 24000,
                      "duration_seconds": len(audio) / 48000,
                      f"first_pcm_seconds_{state}": first, f"total_seconds_{state}": elapsed,
                      f"rtf_{state}": elapsed / (len(audio) / 48000), "wav": str(output),
                      "verified": "non_silent_pcm", "listening_review": "required"}
            output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    finally:
        host.stop()
        print("Inference worker stopped; model memory released.", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("moss_tts", "index_tts", "gpt_sovits"), required=True)
    parser.add_argument("--prompt-wav", help="Authorized Index reference WAV; overrides local environment")
    parser.add_argument("--prompt-text", help="Exact reference transcript for GPT-SoVITS")
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=1, help="First run is cold; remaining runs reuse the initialized worker")
    parser.add_argument("--text", default="你好，我是大飞鱼，很高兴和你聊天。")
    args = parser.parse_args()
    cache = "E:/Dafeiyu/cache"
    for key, value in {"TEMP": cache+"/tmp", "TMP": cache+"/tmp", "HF_HOME": cache+"/huggingface",
                       "HF_HUB_OFFLINE": "1", "TORCH_HOME": cache+"/torch", "NLTK_DATA": cache+"/nltk",
                       "XDG_CACHE_HOME": cache, "PYTHONDONTWRITEBYTECODE": "1",
                       "MPLCONFIGDIR": cache+"/matplotlib", "NUMBA_CACHE_DIR": cache+"/numba",
                       "TORCHINDUCTOR_CACHE_DIR": cache+"/torchinductor", "TRITON_CACHE_DIR": cache+"/triton",
                       "DAFEIYU_MODEL_SERVICE": args.kind}.items():
        os.environ[key] = value
    if args.prompt_wav:
        os.environ["DAFEIYU_GSV_PROMPT_WAV" if args.kind == "gpt_sovits" else "DAFEIYU_INDEX_PROMPT_WAV"] = args.prompt_wav
    if args.prompt_text:
        os.environ["DAFEIYU_GSV_PROMPT_TEXT"] = args.prompt_text
    asyncio.run(run(args))
