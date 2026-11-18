"""Create independent labelled Chinese synthetic regression fixtures locally.

This is not a representative human corpus. Never enrolls a speaker, reads a
provider key or records a microphone. Audio and manifest remain in artifacts/.
"""
import argparse
import asyncio
import io
import json
from pathlib import Path
from urllib.parse import urlparse
import wave

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("greeting", "你好，今天过得怎么样？"),
    ("stop", "等一下，先别说了。"),
    ("topic-change", "换一个问题，我们聊聊明天的计划。"),
    ("backchannel-en", "嗯。"),
    ("backchannel-ok", "好的。"),
    ("short-command", "暂停。"),
    ("digits", "请记住我的编号是一二三四五六七八九零。"),
    ("date", "明天下午三点半提醒我开会。"),
    ("hesitation", "我想一下，这个问题应该怎么说呢？"),
    ("long-question", "如果我在你说话的时候打断你，你能先听完我的新问题再回答吗？"),
]


def wav_bytes(samples):
    target = io.BytesIO()
    with wave.open(target, "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        source.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return target.getvalue()


async def run(args):
    if urlparse(args.url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use a loopback speech service")
    args.output.mkdir(parents=True, exist_ok=True)
    cases = []
    async with httpx.AsyncClient(timeout=120) as client:
        for key, text in CASES:
            response = await client.post(args.url.rstrip("/") + "/v1/audio/speech", json={"input": text, "voice": "default", "response_format": "wav"})
            response.raise_for_status()
            with wave.open(io.BytesIO(response.content), "rb") as source:
                if source.getnchannels() != 1 or source.getsampwidth() != 2:
                    raise ValueError("Expected mono PCM16")
                # Offline corpus prep only; production uses framework resampling.
                rate = source.getframerate()
                samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
                if rate != 16000:
                    import soxr
                    samples = np.clip(soxr.resample(samples.astype(np.float32), rate, 16000), -32768, 32767).astype(np.int16)
            filename = key + ".wav"
            (args.output / filename).write_bytes(wav_bytes(samples))
            cases.append({"id": key, "path": filename, "text": text, "kind": "speech"})
            print("Generated", key, flush=True)
    rng = np.random.default_rng(20261106)
    for key, samples in [("silence", np.zeros(32000)), ("noise", rng.normal(0, 300, 32000))]:
        (args.output / (key + ".wav")).write_bytes(wav_bytes(samples))
        cases.append({"id": key, "path": key + ".wav", "text": "", "kind": key})
    (args.output / "manifest.json").write_text(json.dumps({"provenance": "Independent local sherpa VITS synthetic Chinese utterances and seeded noise; regression fixtures, not human microphone acceptance or speaker accuracy evidence.", "cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "manifest.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/voice-corpus")
    asyncio.run(run(parser.parse_args()))
