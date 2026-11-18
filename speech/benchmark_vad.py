"""Local synthetic-fixture VAD check; no microphone or playback is used."""

import argparse
import asyncio
import io
import json
from pathlib import Path
import wave

import httpx
import numpy as np
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--speech-url", default="http://127.0.0.1:8766")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    samples = {"silence": bytes(16000 * 2 * 3)}
    rng = np.random.default_rng(7)
    samples["low_noise"] = (rng.normal(0, 0.003, 16000 * 3).clip(-1, 1) * 32767).astype("<i2").tobytes()
    async with httpx.AsyncClient(timeout=120) as client:
        for name, phrase in (("ack", "好的。"), ("interrupt", "等一下，我想换一个问题。")):
            response = await client.post(args.speech_url.rstrip("/") + "/v1/audio/speech", json={"input": phrase, "response_format": "wav"})
            response.raise_for_status()
            with wave.open(io.BytesIO(response.content)) as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                    raise ValueError("fixture must be 16k mono PCM16")
                samples[name] = bytes(8000) + wav.readframes(wav.getnframes()) + bytes(32000)
    results = []
    for minimum in (0.6, 0.3):
        for name, pcm in samples.items():
            vad = SileroVADAnalyzer(sample_rate=16000, params=VADParams(confidence=0.7, min_volume=minimum))
            vad.set_sample_rate(16000)
            states, probabilities, volumes = [], [], []
            original = vad.voice_confidence
            def capture(audio):
                result = original(audio)
                probabilities.append(np.asarray(result).item())
                return result
            vad.voice_confidence = capture
            for offset in range(0, len(pcm), 640):
                state = await vad.analyze_audio(pcm[offset:offset + 640])
                states.append(state.name)
                volumes.append(float(vad._prev_volume))
            results.append({"fixture": name, "min_volume": minimum, "peak_confidence": round(max(probabilities), 4),
                            "peak_smoothed_volume": round(max(volumes), 4), "states": sorted(set(states)),
                            "speaking_frames_20ms": states.count("SPEAKING")})
    output = {"method": "Pipecat Silero VAD, synthetic local VITS speech and seeded white noise; no physical microphone or loudspeaker", "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
