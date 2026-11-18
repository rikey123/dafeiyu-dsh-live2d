"""Repeatable Chinese ASR/owner/online-preview evaluation with explicit limits.

Input manifest: {"provenance": "...", "cases": [{"id": "...", "path":
"relative.wav", "text": "expected text", "kind": "speech|noise|silence"}]}.
No microphone, cloud provider, application settings or enrollment is touched.
Use independent human recordings for real quality acceptance; synthetic TTS
fixtures only test the local integration and regression behavior.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import time
import unicodedata
from urllib.parse import urlparse
import wave

import httpx


def normalized(text):
    # Preserve numbers and Chinese characters; do not silently translate
    # number words to digits or "correct" an incorrect recognition.
    return "".join(c.lower() for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c)[0] in "LN")


def edits(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lo = math.floor(index)
    return ordered[lo] + (ordered[math.ceil(index)] - ordered[lo]) * (index - lo)


def summary(values):
    return {"n": len(values), "p50": statistics.median(values) if values else None, "p95": percentile(values, .95), "max": max(values) if values else None, "unit": "seconds"}


def wav_pcm(path):
    data = path.read_bytes()
    with wave.open(io.BytesIO(data), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"Not mono PCM16/16k: {path}")
        pcm = source.readframes(source.getnframes())
    if not pcm or len(pcm) > 26 * 32000:
        raise ValueError("Cases must be between >0 and 26 seconds, leaving room for endpoint silence")
    return data, pcm


async def preview(base, pcm, paced):
    import websockets
    url = base.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/v1/audio/stream"
    started = time.monotonic()
    first = endpoint = None
    text, tokens, timestamps = "", [], []
    async with websockets.connect(url, max_size=1_000_000, open_timeout=30) as socket:
        ready = json.loads(await asyncio.wait_for(socket.recv(), 90))
        if ready.get("type") != "ready" or ready.get("verified") is not False:
            raise ValueError("Unexpected online ASR readiness or identity semantics")
        stream_started = time.monotonic()
        padded = pcm + bytes(3 * 32000)
        for offset in range(0, len(padded), 3200):
            chunk = padded[offset:offset + 3200]
            await socket.send(chunk)
            event = json.loads(await asyncio.wait_for(socket.recv(), 30))
            if event.get("type") != "preview" or event.get("verified") is not False:
                raise ValueError("Online preview must remain explicitly identity-unverified")
            if event.get("text"):
                text = event["text"]
                tokens, timestamps = event.get("tokens", []), event.get("timestamps", [])
                if first is None:
                    first = {"wall_seconds": time.monotonic() - started, "input_seconds": (offset + len(chunk)) / 32000}
            if text and event.get("endpoint") and endpoint is None:
                endpoint = {"wall_seconds": time.monotonic() - started, "input_seconds": (offset + len(chunk)) / 32000}
                break
            if paced:
                await asyncio.sleep(max(0, stream_started + (offset + len(chunk)) / 32000 - time.monotonic()))
    return {"text": text, "tokens": tokens, "timestamps": timestamps, "first_partial": first, "endpoint": endpoint, "wall_seconds": time.monotonic() - started, "paced": paced, "identity_verified": False}


async def evaluate(args):
    address = urlparse(args.url)
    if address.hostname not in {"127.0.0.1", "localhost", "::1"} or address.scheme not in {"http", "https"}:
        raise ValueError("This local diagnostic only accepts loopback speech services")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Cases must have non-empty, unique IDs")
    results = []
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        health_response = await client.get(args.url.rstrip("/") + "/health")
        health_response.raise_for_status()
        health = health_response.json()
        for repeat in range(args.repeats):
            for case in cases:
                path = (args.manifest.parent / case["path"]).resolve()
                data, pcm = wav_pcm(path)
                started = time.monotonic()
                response = await client.post(args.url.rstrip("/") + "/v1/audio/transcriptions", files={"file": ("case.wav", data, "audio/wav")}, data={"owner_only": str(args.owner_only).lower()})
                elapsed = time.monotonic() - started
                response.raise_for_status()
                body = response.json()
                reference, hypothesis = normalized(case["text"]), normalized(body.get("text", ""))
                row = {"id": case["id"], "repeat": repeat, "kind": case.get("kind", "speech"), "audio_sha256": hashlib.sha256(data).hexdigest(), "audio_seconds": len(pcm) / 32000, "expected": case["text"], "text": body.get("text", ""), "reference_characters": len(reference), "character_edits": edits(reference, hypothesis), "http_seconds": elapsed, "speaker": body.get("speaker"), "noise_false_text": bool(hypothesis) if not reference else None}
                if args.online:
                    online = await preview(args.url.rstrip("/"), pcm, not args.unpaced)
                    online["character_edits"] = edits(reference, normalized(online["text"]))
                    row["online"] = online
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    speech = [r for r in results if r["reference_characters"]]
    noise = [r for r in results if not r["reference_characters"]]
    total_characters = sum(r["reference_characters"] for r in speech)
    report = {"provenance": manifest.get("provenance", "unspecified: not human acceptance"), "service_health": health, "owner_only": args.owner_only,
              "repeats": args.repeats, "unique_cases": len(cases), "results": results,
              "summary": {"final_cer": sum(r["character_edits"] for r in speech) / total_characters if total_characters else None, "reference_characters": total_characters, "final_http_latency": summary([r["http_seconds"] for r in results]), "non_speech_false_transcription_count": sum(r["noise_false_text"] for r in noise), "non_speech_cases": len(noise), "online_first_partial_wall": summary([r["online"]["first_partial"]["wall_seconds"] for r in results if r.get("online", {}).get("first_partial")])},
              "limitations": "Fixed local WAV corpus. HTTP latency excludes utterance duration and device capture; online first-partial uses paced input unless unpaced requested. Preview is identity-unverified, even when final owner filtering is enabled. CER preserves number formatting differences. No physical AEC, human FAR/FRR, NPU qualification or human long-session acceptance inferred."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--unpaced", action="store_true")
    parser.add_argument("--owner-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts/voice-corpus/results.json")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("repeats must be between 1 and 100")
    asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
