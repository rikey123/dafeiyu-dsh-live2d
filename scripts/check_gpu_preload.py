"""Verify a running saved GPU route; no LLM, API TTS or microphone calls.

Audio/evidence default to E:. --verify-mode-switch temporarily selects API,
without synthesizing there, then restores the saved GPU configuration.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import wave

GATEWAY = "http://127.0.0.1:8765"


def request(url, *, method="GET", data=None, timeout=10):
    payload = None if data is None else json.dumps(data).encode("utf-8")
    with urlopen(Request(url, data=payload, method=method,
                         headers={"Content-Type": "application/json"}), timeout=timeout) as response:
        return json.load(response)


def wait_ready(address, snapshots, timeout=240):
    started = time.monotonic()
    previous = None
    while time.monotonic() - started < timeout:
        try:
            health = request(address + "/health")
        except (URLError, TimeoutError):
            time.sleep(.5)
            continue
        state = health.get("state")
        if state != previous:
            snapshots.append({"elapsed_seconds": round(time.monotonic()-started, 3), "health": health})
            print(f"GPU: {state}", flush=True)
            previous = state
        if state == "error":
            raise RuntimeError(health.get("detail", "GPU preparation failed"))
        if health.get("ready"):
            assert health.get("device") == "cuda"
            assert health.get("preload") and health.get("resident") and health.get("warmed_up")
            return health
        time.sleep(.5)
    raise TimeoutError("GPU preparation did not finish")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("E:/Dafeiyu/verification"))
    parser.add_argument("--verify-mode-switch", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"snapshots": [], "calls_llm_or_paid_tts": False}
    path = args.output_dir / "gpu-preload.json"
    settings = request(GATEWAY + "/api/settings")
    assert settings["tts_mode"] == "gpu" and settings["conversation_mode"] != "moss_live"
    address = settings["index_tts_url"].rstrip("/")
    try:
        # Deliberately do not call any synthesis/load endpoint before readiness.
        before = report["ready_before_first_synthesis"] = wait_ready(address, report["snapshots"])
        started, first, pcm = time.monotonic(), None, bytearray()
        payload = json.dumps({"input": "你好，我是大飞鱼，很高兴和你聊天。", "voice": "default", "response_format": "pcm"}).encode("utf-8")
        with urlopen(Request(address + "/v1/audio/speech/stream", data=payload,
                             headers={"Content-Type": "application/json"}), timeout=185) as response:
            assert response.headers.get("X-Audio-Sample-Rate") == "24000"
            while chunk := response.read1(4800):
                if first is None: first = time.monotonic()-started
                pcm.extend(chunk)
                assert len(pcm) <= 15_000_000
        assert pcm and any(pcm) and len(pcm) % 2 == 0
        elapsed = time.monotonic()-started
        audio = args.output_dir / "gpu-preload-first-request.wav"
        with wave.open(str(audio), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(pcm)
        after = request(address + "/health")
        assert after["ready"] and after["warmed_up"]
        assert after["preparation_seconds"] == before["preparation_seconds"], "Worker was unexpectedly reloaded"
        report["first_synthesis"] = {"ttfb_seconds": first, "total_seconds": elapsed,
                                     "audio_seconds": len(pcm)/48000, "wav": str(audio), "health_after": after}
        if args.verify_mode_switch:
            try:
                request(GATEWAY + "/api/settings", method="PUT", data={"tts_mode": "api"})
                deadline = time.monotonic()+45
                while time.monotonic() < deadline:
                    try:
                        request(address + "/health", timeout=2)
                    except (URLError, TimeoutError):
                        report["gpu_service_stopped_in_api_mode"] = True
                        break
                    time.sleep(.5)
                assert report.get("gpu_service_stopped_in_api_mode"), "Owned GPU service did not stop"
            finally:
                request(GATEWAY + "/api/settings", method="PUT", data={"tts_mode": "gpu"})
            report["mode_switch_snapshots"] = []
            report["ready_after_mode_enable_without_synthesis"] = wait_ready(address, report["mode_switch_snapshots"])
        report["passed"] = True
    finally:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(path, flush=True)


if __name__ == "__main__":
    main()
