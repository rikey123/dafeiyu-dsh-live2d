"""Exercise an isolated Pipecat gateway with real local STT/TTS and controlled LLM.

Requires scripts/serve_voice_acceptance.py on 8875 and its controlled provider on
8874. Never reads or changes production settings. Audio runs in real time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path

import httpx
import websockets
from pipecat.frames.protobufs import frames_pb2

ROOT = Path(__file__).resolve().parents[1]


def message(kind: str, data: dict, message_id: str) -> bytes:
    frame = frames_pb2.Frame()
    frame.message.data = json.dumps({"label": "rtvi-ai", "type": kind, "id": message_id, "data": data}, ensure_ascii=False)
    return frame.SerializeToString()


async def receive_until(ws, predicate, timeout=60):
    events, audio_bytes = [], 0
    async with asyncio.timeout(timeout):
        while True:
            frame = frames_pb2.Frame.FromString(await ws.recv())
            kind = frame.WhichOneof("frame")
            if kind == "audio":
                audio_bytes += len(frame.audio.audio)
            elif kind == "message":
                event = json.loads(frame.message.data)
                events.append(event)
                if event.get("type") == "error":
                    raise RuntimeError(f"Pipecat returned an error: {event.get('data')}")
                if predicate(event):
                    return events, audio_bytes


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8875")
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--fixture", type=Path, default=ROOT / "artifacts/live-smoke/input.wav")
    args = parser.parse_args()
    if not 1 <= args.turns <= 100:
        parser.error("--turns must be between 1 and 100")
    with wave.open(str(args.fixture), "rb") as wav:
        if wav.getframerate() != 16000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("fixture must be mono PCM16 WAV at 16 kHz")
        fixture = wav.readframes(wav.getnframes())
    async with httpx.AsyncClient(timeout=10) as http:
        session_id = (await http.post(args.url + "/api/sessions")).json()["id"]
        started = time.monotonic()
        turns = []
        ws_url = args.url.replace("http://", "ws://").replace("https://", "wss://")
        try:
            async with websockets.connect(f"{ws_url}/ws/voice?session_id={session_id}", max_size=4_000_000) as ws:
                await ws.send(message("client-ready", {}, "ready"))
                await receive_until(ws, lambda event: event.get("type") == "bot-ready")
                for index in range(args.turns):
                    turn_started = time.monotonic()
                    if index == 0:
                        pcm = bytes(16000) + fixture + bytes(32000)
                        for offset in range(0, len(pcm), 1024):
                            frame = frames_pb2.Frame()
                            frame.audio.audio = pcm[offset:offset + 1024]
                            frame.audio.sample_rate = 16000
                            frame.audio.num_channels = 1
                            await ws.send(frame.SerializeToString())
                            await asyncio.sleep(len(frame.audio.audio) / 32000)
                    else:
                        await ws.send(message("send-text", {"content": f"换一个问题 {index}", "options": {"run_immediately": True, "audio_response": True}}, f"turn-{index}"))
                    events, audio_bytes = await receive_until(ws, lambda event: event.get("type") == "bot-stopped-speaking")
                    if audio_bytes == 0:
                        raise AssertionError(f"turn {index} produced no PCM audio")
                    if index == 0 and not any(e.get("type") == "user-transcription" or (e.get("type") == "user-input" and e.get("data", {}).get("input_type") != "chat") for e in events):
                        raise AssertionError("first audio turn did not produce a user transcription")
                    turns.append({"index": index, "input": "real local ASR" if index == 0 else "RTVI text", "audio_bytes": audio_bytes, "seconds": round(time.monotonic() - turn_started, 3)})
                    print(json.dumps(turns[-1], ensure_ascii=False), flush=True)
            history = (await http.get(f"{args.url}/api/sessions/{session_id}/messages")).json()
            users = [item for item in history if item["role"] == "user"]
            assistants = [item for item in history if item["role"] == "assistant"]
            if len(users) != args.turns or len(assistants) != args.turns:
                raise AssertionError(f"history mismatch: {len(users)} user / {len(assistants)} assistant, expected {args.turns}")
            result = {"passed": True, "turns": turns, "history_counts": {"user": len(users), "assistant": len(assistants)},
                      "seconds": round(time.monotonic() - started, 3), "limitations": "Controlled LLM, local ASR/TTS, paced protobuf input; no physical microphone or cloud inference."}
            output = ROOT / "artifacts/pipecat-acceptance/stress.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False))
        finally:
            await http.delete(f"{args.url}/api/sessions/{session_id}")


if __name__ == "__main__":
    asyncio.run(main())
