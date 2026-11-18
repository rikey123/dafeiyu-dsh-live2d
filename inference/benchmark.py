"""Measure OpenVINO GenAI devices using identical real prompts and generation settings."""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import openvino as ov
import openvino_genai as genai

PROMPT = [{"role": "user", "content": "你好，请用两句话介绍你自己，然后问我今天过得怎么样。"}]


def benchmark(model: Path, device: str, runs: int) -> dict:
    started = time.perf_counter()
    pipeline = genai.LLMPipeline(str(model), device)
    compile_seconds = time.perf_counter() - started
    prompt = pipeline.get_tokenizer().apply_chat_template(PROMPT, True, extra_context={"enable_thinking": False})

    def generate() -> dict:
        begin = time.perf_counter()
        first_token = None
        chunks = []

        def on_token(text: str) -> int:
            nonlocal first_token
            if text:
                if first_token is None:
                    first_token = time.perf_counter() - begin
                chunks.append(text)
            return genai.StreamingStatus.RUNNING.value

        result = pipeline.generate(prompt, streamer=on_token, apply_chat_template=False,
                                   max_new_tokens=64, do_sample=False)
        total = time.perf_counter() - begin
        return {"ttft_seconds": round(first_token, 4) if first_token is not None else None,
                "total_seconds": round(total, 4), "characters": len("".join(chunks)),
                "output": "".join(chunks)}

    warmup = generate()
    samples = [generate() for _ in range(runs)]
    del pipeline
    gc.collect()
    return {"device": device, "compile_seconds": round(compile_seconds, 4), "warmup": warmup,
            "samples": samples,
            "median_ttft_seconds": round(statistics.median(x["ttft_seconds"] for x in samples), 4),
            "median_total_seconds": round(statistics.median(x["total_seconds"] for x in samples), 4)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--devices", nargs="+", default=["CPU", "GPU"])
    args = parser.parse_args()
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "model": str(args.model.resolve()),
              "available_devices": ov.Core().available_devices, "openvino_version": ov.__version__,
              "genai_version": genai.__version__, "prompt": PROMPT, "max_new_tokens": 64,
              "do_sample": False, "runs_per_device": args.runs, "results": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for device in args.devices:
        try:
            result = benchmark(args.model, device, args.runs)
        except Exception as error:
            result = {"device": device, "error": str(error)}
        report["results"].append(result)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
