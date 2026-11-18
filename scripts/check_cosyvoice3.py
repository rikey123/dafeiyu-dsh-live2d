"""Probe real CosyVoice3 streaming, warm reuse and cancellation without a mic."""
from __future__ import annotations

import argparse
import asyncio
import io
from difflib import SequenceMatcher
import json
from pathlib import Path
import time
import unicodedata
import wave

import httpx
import websockets
from pipecat.audio.resamplers.soxr_resampler import SOXRAudioResampler


async def cancel_model(client, url, health_url, text, *, after_audio):
    async with websockets.connect(url) as socket:
        await socket.send(json.dumps({"type": "init"}))
        event = json.loads(await asyncio.wait_for(socket.recv(), 300))
        if event.get("type") != "ready" or not event.get("worker_pid"):
            raise RuntimeError(f"Expected identifiable real worker: {event}")
        worker_pid = event["worker_pid"]
        await socket.send(json.dumps({"type": "text", "text": text}))
        async with asyncio.timeout(120):
            while True:
                message = await socket.recv()
                if isinstance(message, bytes):
                    if after_audio:
                        break
                else:
                    event = json.loads(message)
                    if event.get("type") == "error":
                        raise RuntimeError(str(event))
                    if not after_audio and event.get("type") == "text_ack":
                        break
        started = time.monotonic()
        await socket.send(json.dumps({"type": "cancel"}))
    while True:
        response = await client.get(health_url)
        response.raise_for_status()
        health = response.json()
        if not health["busy"]:
            if not health["loaded"] or health.get("worker_pid") != worker_pid:
                raise RuntimeError("Cancellation discarded a responsive warm worker")
            return {"release_seconds": time.monotonic() - started, "worker_pid": worker_pid,
                    "after_audio": after_audio, "model_retained": True}
        if time.monotonic() - started > 15:
            raise RuntimeError("Cancelled worker did not finish cleanup")
        await asyncio.sleep(.1)


async def session(url, text, wav_path):
    started = time.monotonic()
    audio = bytearray()
    first = None
    acknowledgments = []
    async with websockets.connect(url, max_size=8 * 1024 * 1024, open_timeout=20) as socket:
        await socket.send(json.dumps({"type": "init"}))
        ready = json.loads(await asyncio.wait_for(socket.recv(), 300))
        if ready.get("type") != "ready" or str(ready.get("model_version")) != "3":
            raise RuntimeError(f"Expected real third-generation ready: {ready}")
        ready_seconds = time.monotonic() - started
        fragments = [text[:len(text) // 2], text[len(text) // 2:]]
        await socket.send(json.dumps({"type": "text", "text": fragments[0]}))
        async with asyncio.timeout(600):
            async for message in socket:
                if isinstance(message, bytes):
                    if not message or len(message) % 2:
                        raise RuntimeError("Invalid PCM")
                    first = first if first is not None else time.monotonic() - started
                    audio.extend(message)
                else:
                    event = json.loads(message)
                    if event.get("type") == "text_ack":
                        sequence = event["sequence"]
                        acknowledgments.append(sequence)
                        if sequence == 1:
                            await socket.send(json.dumps({"type": "text", "text": fragments[1]}))
                        elif sequence == 2:
                            await socket.send(json.dumps({"type": "end"}))
                    elif event.get("type") == "done":
                        break
                    elif event.get("type") == "error":
                        raise RuntimeError(str(event))
        if not audio or acknowledgments != [1, 2]:
            raise RuntimeError("Missing real audio or text-consumption acknowledgments")
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as output:
        output.setparams((1, 2, ready["sample_rate"], 0, "NONE", "not compressed"))
        output.writeframes(audio)
    return {"ready": ready, "ready_seconds": ready_seconds, "first_audio_seconds": first,
            "total_seconds": time.monotonic() - started,
            "audio_seconds": len(audio) / 2 / ready["sample_rate"], "text_ack": acknowledgments,
            "wav": str(wav_path)}


async def run(args):
    report = {"method": "Actual model WebSocket PCM; no microphone; actual device from worker", "text": args.text}
    health_url = args.url.replace("ws://", "http://").replace("wss://", "https://").split("/v1/")[0] + "/health"
    async with httpx.AsyncClient(timeout=20) as client:
        health = (await client.get(health_url)).json()
        if health["busy"]:
            raise RuntimeError("Probe requires an idle isolated model service")
        report["initially_loaded"] = health["loaded"]
    report["first"] = await session(args.url, args.text, args.output.with_suffix(".wav"))
    report["warm"] = await session(args.url, args.text, args.output.with_name(args.output.stem + "-warm.wav"))
    async with httpx.AsyncClient(timeout=120) as client:
        with wave.open(str(args.output.with_suffix(".wav")), "rb") as source:
            rate = source.getframerate()
            audio = source.readframes(source.getnframes())
        # Local ASR deliberately accepts only mono PCM16 at 16kHz.
        audio = await SOXRAudioResampler().resample(audio, rate, 16000)
        asr_wav = io.BytesIO()
        with wave.open(asr_wav, "wb") as output:
            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            output.writeframes(audio)
        response = await client.post(args.speech_url + "/v1/audio/transcriptions",
                                     files={"file": ("probe.wav", asr_wav.getvalue(), "audio/wav")})
        response.raise_for_status()
        report["asr_readback"] = response.json()
        normalize = lambda value: "".join(c for c in unicodedata.normalize("NFKC", value) if c.isalnum())
        similarity = SequenceMatcher(None, normalize(args.text), normalize(report["asr_readback"].get("text", ""))).ratio()
        report["readback_similarity"] = similarity
        if similarity < .75:
            raise RuntimeError(f"Synthetic speech failed ASR intelligibility gate: {report['asr_readback']}")
        report["cancel_checks"] = []
        for after_audio in (False, True):
            check = await cancel_model(client, args.url, health_url, args.text, after_audio=after_audio)
            resumed = await session(args.url, args.text, args.output.with_name(args.output.stem + f"-resumed-{int(after_audio)}.wav"))
            if resumed["ready"].get("worker_pid") != check["worker_pid"]:
                raise RuntimeError("Next response reloaded the model after interruption")
            check["resumed"] = resumed
            report["cancel_checks"].append(check)
    report["passed"] = True
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8770/v1/tts/bistream")
    parser.add_argument("--speech-url", default="http://127.0.0.1:8766")
    parser.add_argument("--text", default="你好，我是大肥鱼。我们可以慢慢聊。")
    parser.add_argument("--output", type=Path, default=Path("artifacts/cosyvoice3-acceptance.json"))
    asyncio.run(run(parser.parse_args()))
