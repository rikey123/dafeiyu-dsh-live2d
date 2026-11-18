"""Explicit offline CosyVoice generator and WAV probe."""

import argparse
import json
import time
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir")
    parser.add_argument("prompt_wav")
    parser.add_argument("--prompt-text", default="希望你以后能够做的比我还好呦。")
    parser.add_argument("--version", choices=("2", "3"), default="3")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--precision", choices=("fp32", "fp16"), default="fp32")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import os
    from pathlib import Path
    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    if args.device == "cpu" and args.precision == "fp16":
        parser.error("CPU fp16 is unsupported")
    if not (Path(args.model_dir) / f"cosyvoice{args.version}.yaml").is_file():
        parser.error("model directory does not match selected version")
    import torch
    import numpy as np
    from cosyvoice.cli.cosyvoice import CosyVoice2, CosyVoice3
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA unavailable")

    started = time.monotonic()
    model = (CosyVoice2 if args.version == "2" else CosyVoice3)(args.model_dir, fp16=args.precision == "fp16")
    loaded = time.monotonic()
    fragments = ["你好，今天过得怎么样？", "我们可以慢慢聊。"]
    def text_stream():
        for fragment in fragments:
            print(json.dumps({"event": "text", "seconds": time.monotonic() - loaded}, ensure_ascii=False), flush=True)
            yield fragment

    first = None
    samples = 0
    chunks = 0
    prompt = args.prompt_text
    if args.version == "3" and "<|endofprompt|>" not in prompt:
        prompt = "You are a helpful assistant.<|endofprompt|>" + prompt
    pcm = []
    for output in model.inference_zero_shot(text_stream(), prompt, args.prompt_wav, stream=True):
        samples += output["tts_speech"].numel()
        pcm.append((np.clip(output["tts_speech"].detach().cpu().numpy().reshape(-1), -1, 1) * 32767).astype("<i2").tobytes())
        chunks += 1
        if first is None:
            first = time.monotonic() - loaded
            print(json.dumps({"event": "first_audio", "seconds": first}, ensure_ascii=False), flush=True)
    elapsed = time.monotonic() - loaded
    duration = samples / model.sample_rate
    with wave.open(args.output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(model.sample_rate)
        wav.writeframes(b"".join(pcm))
    print(json.dumps({"event": "completed", "load_seconds": loaded - started, "first_audio_seconds": first,
                      "elapsed_seconds": elapsed, "audio_seconds": duration, "chunks": chunks,
                      "rtf": elapsed / duration if duration else None, "device": str(model.model.device),
                      "precision": "fp16" if model.model.fp16 else "fp32", "model_version": args.version}), flush=True)


if __name__ == "__main__":
    main()
