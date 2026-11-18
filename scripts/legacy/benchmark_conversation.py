"""Twenty real local voice turns; reports submitted-audio -> first received WAV.

Does NOT include VAD endpoint delay, browser decoding, physical speaker latency,
or a human microphone. Playback acknowledgement is simulated for this harness.
"""
from __future__ import annotations
import asyncio
import base64
import io
import json
from pathlib import Path
import statistics
import time
import wave
import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ["你好，请用一句话介绍你自己。", "我今天心情很好。", "我有点累了，想听一句鼓励。", "你喜欢晴天还是雨天？", "请给我一个休息的小建议。", "我喜欢音乐，你呢？", "你能听懂我说的话吗？", "请用一句话祝我晚安。", "谢谢你陪我聊天。", "我准备去散步，你有什么建议？"]


async def main():
    turns = []
    async with httpx.AsyncClient(timeout=120) as client:
        inputs = []
        for prompt in PROMPTS:
            response = await client.post("http://127.0.0.1:8766/v1/audio/speech", json={"input": prompt, "response_format": "wav"})
            response.raise_for_status()
            with wave.open(io.BytesIO(response.content), "rb") as audio:
                assert audio.getframerate() == 16000
                inputs.append(base64.b64encode(audio.readframes(audio.getnframes())).decode())
        async with websockets.connect("ws://127.0.0.1:8765/ws/chat", max_size=20_000_000) as ws:
            session_id = json.loads(await ws.recv())["session_id"]
            for index in range(20):
                row = {"round": index+1, "input": PROMPTS[index % len(PROMPTS)], "transcript": "", "reply": "", "first_wav_ms": None, "errors": []}
                started = time.perf_counter()
                await ws.send(json.dumps({"type": "audio", "audio": inputs[index % len(inputs)], "sample_rate": 16000}))
                done = False
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), 120))
                    kind = event["type"]
                    if kind == "audio":
                        if row["first_wav_ms"] is None:
                            row["first_wav_ms"] = round((time.perf_counter()-started)*1000, 1)
                        await ws.send(json.dumps({"type": "playback.ack", "epoch": event["epoch"], "segment_id": event["segment_id"]}))
                    elif kind == "transcript":
                        row["transcript"] = event["text"]
                    elif kind == "response.done":
                        row["reply"] = event["text"]
                        done = True
                    elif kind == "error":
                        row["errors"].append(event)
                        raise RuntimeError(event)
                    elif kind == "state" and event["state"] == "listening" and done:
                        break
                assert row["first_wav_ms"] is not None
                turns.append(row)
                print(json.dumps({"round": index+1, "first_wav_ms": row["first_wav_ms"]}), flush=True)
        await client.delete(f"http://127.0.0.1:8765/api/sessions/{session_id}")
    values = sorted(row["first_wav_ms"] for row in turns)
    report = {"method": __doc__, "rounds": len(turns), "first_wav_p50_ms": statistics.median(values), "first_wav_p95_ms": values[18], "first_wav_max_ms": max(values), "turns": turns}
    out = ROOT / "artifacts/conversation-benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: val for key, val in report.items() if key not in {"turns", "method"}}))


if __name__ == "__main__":
    asyncio.run(main())
