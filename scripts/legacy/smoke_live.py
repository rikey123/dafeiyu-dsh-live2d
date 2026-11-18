"""Real-service integration check. Uses synthesized speech, not a physical mic.

Run only when local services and a real LLM provider are ready. Results describe
server/network timings; they are not acoustic end-to-end latency measurements.
"""
from __future__ import annotations
import asyncio
import base64
import io
import json
from pathlib import Path
import time
import wave
import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/live-smoke"


async def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result = {"method": "real local model + TTS-generated Chinese input; no physical microphone/speaker measurement", "turns": []}
    async with httpx.AsyncClient(timeout=120) as client:
        status = (await client.get("http://127.0.0.1:8765/api/status")).json()
        result["status"] = status
        if not status["llm"]["ready"]:
            raise RuntimeError(f"Real LLM provider not ready: {status['llm']}")
        speech = await client.post("http://127.0.0.1:8766/v1/audio/speech", json={"input": "你好，请简单介绍一下你自己。", "response_format": "wav"})
        speech.raise_for_status()
        (OUTPUT / "input.wav").write_bytes(speech.content)
        with wave.open(io.BytesIO(speech.content), "rb") as wav:
            if wav.getframerate() != 16000 or wav.getsampwidth() != 2 or wav.getnchannels() != 1:
                raise RuntimeError("Smoke input expects mono 16k PCM16 from local TTS")
            pcm = wav.readframes(wav.getnframes())
        with wave.open(str(OUTPUT / "microphone.wav"), "wb") as fixture:
            fixture.setnchannels(1)
            fixture.setsampwidth(2)
            fixture.setframerate(16000)
            fixture.writeframes(b"\0\0" * 16000 * 3 + pcm + b"\0\0" * 16000 * 10)
        async with websockets.connect("ws://127.0.0.1:8765/ws/chat", max_size=20_000_000) as ws:
            session = json.loads(await ws.recv())
            session_id = session["session_id"]
            async def finish_turn(event, turn_number):
                started = time.perf_counter()
                await ws.send(json.dumps(event))
                turn = {"first_audio_received_ms": None, "text": "", "transcript": None, "audio_segments": 0, "errors": []}
                while True:
                    item = json.loads(await asyncio.wait_for(ws.recv(), 180))
                    kind = item["type"]
                    if kind == "audio":
                        if turn["first_audio_received_ms"] is None:
                            turn["first_audio_received_ms"] = round((time.perf_counter() - started) * 1000)
                        raw = base64.b64decode(item["audio"])
                        (OUTPUT / f"reply-{turn_number}-{item['segment_id']}.wav").write_bytes(raw)
                        turn["audio_segments"] += 1
                        # Validate server acknowledgement logic without claiming actual audio playback.
                        await ws.send(json.dumps({"type": "playback.ack", "epoch": item["epoch"], "segment_id": item["segment_id"]}))
                    elif kind == "transcript":
                        turn["transcript"] = item["text"]
                    elif kind == "response.done":
                        turn["text"] = item["text"]
                    elif kind == "error":
                        turn["errors"].append(item)
                        if not turn["text"] and item["code"].startswith("llm_"):
                            raise RuntimeError(item["message"])
                    elif kind == "metrics":
                        turn["server_metrics"] = item
                    elif kind == "state" and item["state"] == "listening" and turn["text"]:
                        break
                turn["total_received_ms"] = round((time.perf_counter() - started) * 1000)
                assert turn["audio_segments"] > 0 and turn["text"] and not turn["errors"], turn
                result["turns"].append(turn)
            await finish_turn({"type": "audio", "audio": base64.b64encode(pcm).decode(), "sample_rate": 16000}, 1)
            await finish_turn({"type": "text", "text": "我喜欢晴天和音乐。请用一句话回应我。"}, 2)
            await ws.send(json.dumps({"type": "text", "text": "请详细介绍四季的变化，至少说八句话。"}))
            old_epoch = None
            while True:
                item = json.loads(await asyncio.wait_for(ws.recv(), 180))
                if item["type"] == "audio":
                    old_epoch = item["epoch"]
                    break
                if item["type"] == "error":
                    raise RuntimeError(item)
            interrupt_started = time.perf_counter()
            await ws.send(json.dumps({"type": "interrupt"}))
            while True:
                item = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if item["type"] == "audio.clear" and item["epoch"] > old_epoch:
                    result["cancel_clear_roundtrip_ms"] = round((time.perf_counter() - interrupt_started) * 1000, 2)
                    new_epoch = item["epoch"]
                    break
            stale_audio = 0
            end = time.perf_counter() + 1.5
            while time.perf_counter() < end:
                try:
                    item = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end-time.perf_counter())))
                    stale_audio += int(item["type"] == "audio" and item["epoch"] < new_epoch)
                except asyncio.TimeoutError:
                    break
            result["stale_audio_after_clear"] = stale_audio
            assert stale_audio == 0
            await finish_turn({"type": "text", "text": "换个话题，请只说一句晚安。"}, 3)
        messages = (await client.get(f"http://127.0.0.1:8765/api/sessions/{session_id}/messages")).json()
        result["stored_roles"] = [row["role"] for row in messages]
        result["unplayed_interrupted_reply_stored"] = any(row["role"] == "assistant" and "四季" in row["content"] for row in messages)
        await client.delete(f"http://127.0.0.1:8765/api/sessions/{session_id}")
    (OUTPUT / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
