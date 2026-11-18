"""Serial HTTP comparison against the already-running loopback speech service."""
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8766"
SENTENCES = {
    "short": "你好，今天怎么样？",
    "long": "你好，今天我们一起聊聊天吧。你可以告诉我最近遇到的事情，我会认真听，也可以陪你一起想办法。",
}
result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "endpoint": BASE, "method": "Three serial stream then WAV requests per sentence; times from HTTP request start to first PCM and complete WAV. No warmup excluded.", "samples": []}
with httpx.Client(timeout=120) as client:
    health = client.get(BASE + "/health")
    health.raise_for_status()
    result["tts_health"] = health.json()["tts"]
    for label, sentence in SENTENCES.items():
        for repeat in range(1, 4):
            t0 = time.perf_counter()
            with client.stream("POST", BASE + "/v1/audio/speech/stream", json={"input": sentence, "voice": "", "response_format": "pcm"}) as response:
                response.raise_for_status()
                first = None
                total = 0
                chunks = 0
                for chunk in response.iter_bytes():
                    if chunk and first is None:
                        first = time.perf_counter() - t0
                    total += len(chunk)
                    chunks += bool(chunk)
                stream_complete = time.perf_counter() - t0
                sample_rate = response.headers.get("X-Audio-Sample-Rate")
            if first is None or total % 2:
                raise ValueError("empty or invalid PCM")
            t0 = time.perf_counter()
            wav = client.post(BASE + "/v1/audio/speech", json={"input": sentence, "voice": "", "response_format": "wav"})
            wav.raise_for_status()
            wav_complete = time.perf_counter() - t0
            if not wav.content.startswith(b"RIFF"):
                raise ValueError("invalid WAV")
            result["samples"].append({"sentence": label, "text": sentence, "repeat": repeat, "first_pcm_s": first, "stream_complete_s": stream_complete, "pcm_bytes": total, "chunks": chunks, "sample_rate": sample_rate, "wav_complete_s": wav_complete, "wav_bytes": len(wav.content)})
result["summary"] = {label: {key: statistics.median(s[key] for s in result["samples"] if s["sentence"] == label) for key in ("first_pcm_s", "stream_complete_s", "wav_complete_s")} for label in SENTENCES}
path = Path(__file__).resolve().parents[1] / 'artifacts/benchmark-speech-tts.json'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
