"""Offline WebRTC APM experiment; no device access or production integration."""
import argparse
import json
import time
import wave

import numpy as np
from livekit import rtc
from livekit.rtc.apm import AudioProcessingModule

RATE, FRAME, SECONDS = 16000, 160, 12
parser = argparse.ArgumentParser(description="Offline AEC experiment using two 16 kHz mono PCM16 WAV speech files")
parser.add_argument("far")
parser.add_argument("near")
args = parser.parse_args()

def load(path):
    with wave.open(path, "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Input must be 16 kHz mono PCM16 WAV")
        data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float64)
    if len(data) < RATE:
        raise ValueError("Input must contain at least one second")
    data = np.tile(data, (RATE * SECONDS // len(data)) + 1)[:RATE * SECONDS]
    return data * (3500 / max(np.sqrt(np.mean(data ** 2)), 1))

far = load(args.far).clip(-16000, 16000).astype(np.int16)
near = load(args.near).clip(-16000, 16000)
echo = np.zeros_like(near)
for delay, gain in [(640, .55), (752, .20), (928, -.12)]:
    echo[delay:] += far[:-delay].astype(np.float64) * gain
apm = AudioProcessingModule(echo_cancellation=True, noise_suppression=False, auto_gain_control=False, high_pass_filter=False)
apm.set_stream_delay_ms(40)
output = []
start = time.perf_counter()
for offset in range(0, len(far), FRAME):
    render = rtc.AudioFrame(data=far[offset:offset + FRAME].tobytes(), sample_rate=RATE, num_channels=1, samples_per_channel=FRAME)
    mixed = echo[offset:offset + FRAME] + (near[offset:offset + FRAME] if offset >= 8 * RATE else 0)
    capture = rtc.AudioFrame(data=mixed.clip(-32768, 32767).astype(np.int16).tobytes(), sample_rate=RATE, num_channels=1, samples_per_channel=FRAME)
    apm.process_reverse_stream(render)
    apm.process_stream(capture)
    output.append(np.frombuffer(capture.data, dtype=np.int16).copy())
elapsed = time.perf_counter() - start
clean = np.concatenate(output).astype(np.float64)
region = slice(5 * RATE, 8 * RATE)
erle = 10 * np.log10(np.mean(echo[region] ** 2) / max(np.mean(clean[region] ** 2), 1e-12))
region = slice(9 * RATE, 11 * RATE)
target = near[region]
start = 9 * RATE
lags = range(-800, 801)
lag = max(lags, key=lambda shift: np.dot(clean[start + shift:start + shift + len(target)], target))
aligned = clean[start + lag:start + lag + len(target)]
near_gain = np.dot(aligned, target) / np.dot(target, target)
correlation = np.dot(aligned, target) / max(np.linalg.norm(aligned) * np.linalg.norm(target), 1e-12)
print(json.dumps({"sample_rate": RATE, "frame_ms": 10, "audio_seconds": SECONDS,
                  "processing_seconds": round(elapsed, 4), "realtime_factor": round(elapsed / SECONDS, 5),
                  "echo_only_erle_db": round(float(erle), 2), "double_talk_near_projection_gain": round(float(near_gain), 3),
                  "double_talk_near_correlation": round(float(correlation), 3),
                  "best_alignment_lag_samples": lag,
                  "limitations": "Two speech recordings and simulated fixed multipath; no real room, devices, browser, or perceptual quality assessment."}))
