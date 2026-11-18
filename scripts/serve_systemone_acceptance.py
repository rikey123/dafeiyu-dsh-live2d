"""Loopback-only protocol fixtures for browser QA; no real cloud/model inference."""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("E:/Dafeiyu/verification/systemone")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["DAFEIYU_DATA_DIR"] = str(OUT / "fixture-import-store")
bypass = ",".join(filter(None, (os.environ.get("NO_PROXY", ""), os.environ.get("no_proxy", ""), "127.0.0.1,localhost,::1")))
os.environ["NO_PROXY"] = os.environ["no_proxy"] = bypass

import httpx
import uvicorn
from fastapi import Request
from scripts import serve_voice_acceptance as fixture
from server import main, systemone, systemone_initiative
from server.storage import Store
from pipecat.frames.frames import InputAudioRawFrame, TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame

state = {"mode": "success", "calls": 0, "audio_calls": 0, "providers": [], "initiative_calls": 0, "initiative_mode": "strong"}
initiatives = []
PARTIAL = "这件事情让我有点难过，我还想接着讲"
FINAL = PARTIAL + "，后来我的朋友来安慰我，现在已经好多了。"


class FixtureInitiative(systemone_initiative.SystemOneInitiative):
    def __init__(self, client, context, transcribe, settings, **kwargs):
        async def snapshot(_): return PARTIAL
        super().__init__(client, context, snapshot, settings, **kwargs)
        initiatives.append(self)

    async def cleanup(self):
        if self in initiatives:
            initiatives.remove(self)
        await super().cleanup()


systemone_initiative.SystemOneInitiative = FixtureInitiative


async def decisions(request):
    payload = json.loads(request.content)
    ark = request.url.host == "ark.cn-beijing.volces.com"
    assert str(request.url) == ("https://ark.cn-beijing.volces.com/api/v1/systemone" if ark else "https://api.tokentosea.com/v1/systemone")
    if ark:
        assert request.headers.get("ark-beta-systemone-api") == "true"
        assert set(payload) == {"model", "state", "questions"}
    state["providers"].append("ark" if ark else "tokentosea")
    state["providers"] = state["providers"][-64:]
    state["calls"] += 1
    state["audio_calls"] += bool(payload.get("audio")) or isinstance(payload.get("state"), list)
    initiative = "speak_now" in payload["questions"]
    if initiative:
        state["initiative_calls"] += 1
    if state["mode"] == "timeout":
        await asyncio.sleep(5)
    if state["mode"] == "region":
        return httpx.Response(403, json={"error": {"code": "model_not_supported_in_region", "message": "private fixture provider response"}})
    if state["mode"] == "invalid":
        return httpx.Response(200, json={"model": payload["model"], "answers": {}})
    await asyncio.sleep(.15)
    answers = {}
    selected = {"emotion": "sad", "expression": "tears", "gesture": "chest", "user_emotion": "sad", "intent": "empathize"}
    for key, question in payload["questions"].items():
        kind = question["type"]
        if kind == "noul":
            probability = .95 if key in {"interrupt", "speak_now"} else .03
            if initiative and state["initiative_mode"] == "wait":
                probability = .1 if key == "speak_now" else .95
            answers[key] = {"type": kind, "noul": probability}
        elif kind == "choice":
            value = selected[key]
            answers[key] = {"type": kind, "choice": value, "confidence": .95,
                            "probabilities": {v: 1 if v == value else 0 for v in question["criteria"]}}
        else:
            answers[key] = {"type": kind, "score": 0, "confidence": .95, "probabilities": {"0": 1, "1": 0, "2": 0}}
    return httpx.Response(200, json={"model": payload["model"], "answers": answers, "usage": {"input_tokens": 10}})


OriginalClient = systemone.SystemOneClient
class FixtureClient(OriginalClient):
    def __init__(self, settings, **kwargs):
        super().__init__(settings, transport=httpx.MockTransport(decisions), **kwargs)
systemone.SystemOneClient = FixtureClient


@fixture.provider.get('/test/decisions')
def current():
    return {**state, "fixture": True}


@fixture.provider.put('/test/decisions')
async def set_mode(request: Request):
    value = await request.json()
    mode = value.get("mode")
    if mode in {"success", "timeout", "invalid", "region"}:
        state["mode"] = mode
    if value.get("initiative_mode") in {"strong", "wait"}:
        state["initiative_mode"] = value["initiative_mode"]
    return current()


@fixture.provider.post('/test/initiative')
async def feed_initiative(request: Request):
    """Explicit test-frame injection, NOT microphone/VAD/real-ASR evidence."""
    from fastapi import HTTPException
    if not initiatives:
        raise HTTPException(409, "fixture initiative session not connected")
    control = initiatives[-1]
    action = (await request.json()).get("action")
    frames = {"start": lambda: VADUserStartedSpeakingFrame(),
              "probe": lambda: InputAudioRawFrame(audio=bytes(96000), sample_rate=16000, num_channels=1),
              "stop": lambda: VADUserStoppedSpeakingFrame(),
              "final": lambda: TranscriptionFrame(text=FINAL, user_id="fixture", timestamp="now", finalized=True)}
    if action not in frames:
        raise HTTPException(400, "unknown fixture action")
    if action == "start":
        await control.set_capture_active(True)  # Synthetic fixture, never a real microphone.
    await control.queue_frame(frames[action]())
    return {"fixture": True, "synthetic_frames": True}


async def run():
    pcm = OUT / "protocol-tone.wav"
    with wave.open(str(pcm), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(b"".join(struct.pack("<h", int(2000 * math.sin(i * 2 * math.pi * 220 / 24000))) for i in range(24000 * 4)))
    fixture.api_audio_fixture = pcm
    fixture.controlled_reply = "我今天不开心，希望有人理解。"
    with tempfile.TemporaryDirectory(prefix="browser-", dir=OUT) as directory:
        main.store = Store(Path(directory))
        main.store.update_settings({"llm_base_url": "http://127.0.0.1:8874/v1", "llm_model": "controlled-voice-test", "llm_api_key": "test-only",
                                    "tts_mode": "api", "tts_api_base_url": "http://127.0.0.1:8874/v1", "tts_api_key": "audit-tts-only",
                                    "systemone_provider": "ark", "systemone_api_key": "", "systemone_ark_api_key": "", "systemone_enabled": False})
        original_origin = main.trusted_origin
        main.trusted_origin = lambda origin: original_origin(origin) or origin == "http://127.0.0.1:8875"
        gateway = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=8875, log_level="warning"))
        provider = uvicorn.Server(uvicorn.Config(fixture.provider, host="127.0.0.1", port=8874, log_level="warning"))
        try:
            await asyncio.gather(gateway.serve(), provider.serve())
        finally:
            main.store.db.close()


if __name__ == "__main__":
    asyncio.run(run())
