"""Explicit physical duplex AEC diagnostic, separate from browser production.

Reuses LiveKit's WebRTC APM and the single-PortAudio-stream approach reviewed
in Edge-Voice-Assistant. No device is opened by --help or --list-devices.
Run --capture to play a supplied WAV and record local mic/raw/processed taps.
Recordings stay in ignored artifacts/. Never sends audio to a cloud provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RATE, FRAME = 16000, 160


def read_pcm(path):
    with wave.open(str(path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Use mono PCM16 16000 Hz reference WAV")
        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").copy()


def save_pcm(path, data):
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(RATE)
        target.writeframes(np.asarray(data, dtype="<i2").tobytes())


def energy(samples):
    return float(np.mean(np.asarray(samples, dtype=np.float64) ** 2)) if len(samples) else 0.0


def analyze(raw, clean, render, far_region, near_region, double_region):
    """Energy attenuation alone cannot establish near-end preservation."""
    result = {}
    for name, region in [("far_only", far_region), ("near_only", near_region), ("double_talk", double_region)]:
        start, end = (round(t * RATE) for t in region)
        a, b = raw[start:end], clean[start:end]
        if end > len(raw) or start >= end or start < 0:
            raise ValueError(f"Invalid analysis interval: {name}")
        before, after = energy(a), energy(b)
        # This includes device noise/any unlabelled near speech; deliberately
        # not named ERLE, which would require an isolated echo component.
        result[name] = {
            "seconds": list(region), "raw_rms": before ** .5, "processed_rms": after ** .5,
            "total_energy_attenuation_db": 10 * float(np.log10(max(before, 1e-9) / max(after, 1e-9))),
            "raw_clipped_fraction": float(np.mean(np.abs(a.astype(np.float64)) >= 32767)),
            "processed_clipped_fraction": float(np.mean(np.abs(b.astype(np.float64)) >= 32767)),
            "render_rms": energy(render[start:end]) ** .5,
        }
    result["physical_acceptance"] = "pending human near-only/double-talk intelligibility and false-interruption evaluation"
    result["limitations"] = "Energy attenuation is not ERLE, intelligibility or target-speaker retention; ADC/DAC timestamps describe device scheduling, not a calibrated acoustic loop. Native APM experiment is separate from browser AEC."
    return result


def capture(args):
    import sounddevice as sd
    from livekit import rtc
    from livekit.rtc.apm import AudioProcessingModule

    reference = read_pcm(args.reference)
    if len(reference) < RATE:
        raise ValueError("Reference must contain at least one second of speech")
    target = args.output.resolve()
    if not target.is_relative_to((ROOT / "artifacts").resolve()):
        raise ValueError("Diagnostic recordings must stay inside this project's ignored artifacts directory")
    target.mkdir(parents=True, exist_ok=False)
    # Fixed labelled protocol: silence0-3, far-only3-13, near-only13-23,
    # double-talk23-33, tail33-36. Speak only during near/double phases.
    seconds = 36
    count = RATE * seconds
    render = np.zeros(count, dtype=np.int16)
    for start, end in [(3, 13), (23, 33)]:
        length = (end - start) * RATE
        tiled = np.tile(reference, 1 + length // len(reference))[:length]
        render[start * RATE:end * RATE] = np.clip(tiled.astype(np.float64) * args.gain, -32768, 32767).astype(np.int16)
    raw, clean = np.zeros(count, dtype=np.int16), np.zeros(count, dtype=np.int16)
    clocks = np.zeros((count // FRAME, 4), dtype=np.float64)
    apm = AudioProcessingModule(echo_cancellation=True, noise_suppression=False, auto_gain_control=False, high_pass_filter=False)
    state = {"offset": 0, "callback_errors": [], "status_frames": 0, "input_overflows": 0, "output_underflows": 0}

    def callback(indata, outdata, frames, clock, status):
        offset = state["offset"]
        outdata.fill(0)
        if frames != FRAME or offset + FRAME > count:
            raise sd.CallbackStop()
        try:
            if status:
                state["status_frames"] += 1
                state["input_overflows"] += int(status.input_overflow)
                state["output_underflows"] += int(status.output_underflow)
            audio = render[offset:offset + FRAME]
            outdata[:, 0] = audio
            raw[offset:offset + FRAME] = indata[:, 0]
            clocks[offset // FRAME] = (offset, clock.inputBufferAdcTime, clock.currentTime, clock.outputBufferDacTime)
            apm.process_reverse_stream(rtc.AudioFrame(data=audio.tobytes(), sample_rate=RATE, num_channels=1, samples_per_channel=FRAME))
            capture_frame = rtc.AudioFrame(data=indata[:, 0].tobytes(), sample_rate=RATE, num_channels=1, samples_per_channel=FRAME)
            apm.process_stream(capture_frame)
            clean[offset:offset + FRAME] = np.frombuffer(capture_frame.data, dtype=np.int16)
            state["offset"] += FRAME
        except Exception as exc:
            if len(state["callback_errors"]) < 5:
                state["callback_errors"].append(type(exc).__name__ + ": " + str(exc))
            raise sd.CallbackAbort() from exc

    print("36秒本地设备测试：0–3秒安静；3–13秒只听；13–23秒只说；23–33秒边听边说；33–36秒安静。", flush=True)
    print("仅用于原生APM诊断；不要同时在应用中开麦。录音目录：", target, flush=True)
    with sd.Stream(samplerate=RATE, blocksize=FRAME, channels=1, dtype="int16", device=(args.input_device, args.output_device), callback=callback) as stream:
        delay_ms = int(round(sum(stream.latency) * 1000))
        apm.set_stream_delay_ms(delay_ms)
        started = time.monotonic()
        phase = None
        while stream.active and time.monotonic() - started < seconds + 10:
            elapsed = state["offset"] / RATE
            next_phase = "安静" if elapsed < 3 or elapsed >= 33 else "只听" if elapsed < 13 else "只说" if elapsed < 23 else "边听边说"
            if phase != next_phase:
                phase = next_phase
                print(f"{elapsed:.1f}s {phase}", flush=True)
            time.sleep(.05)
    actual = state.pop("offset")
    save_pcm(target / "render.wav", render[:actual])
    save_pcm(target / "microphone-raw.wav", raw[:actual])
    save_pcm(target / "microphone-apm.wav", clean[:actual])
    np.save(target / "adc-dac-clock.npy", clocks[:actual // FRAME])
    report = {"mode": "physical-native-duplex-apm", "sample_rate": RATE, "frame_ms": 10, "recorded_seconds": actual / RATE, "device_names": {"input": sd.query_devices(args.input_device, "input")["name"], "output": sd.query_devices(args.output_device, "output")["name"]}, "stream_delay_ms": delay_ms,
              "source_reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(), "gain": args.gain, **state,
              "analysis": analyze(raw[:actual], clean[:actual], render[:actual], (6, 12), (15, 22), (26, 32)) if actual >= 33 * RATE else {"incomplete": True},
              "production_aec_enabled": False}
    (target / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if actual == count and not state["callback_errors"] and not state["status_frames"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int)
    parser.add_argument("--gain", type=float, default=.35)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / ("physical-aec-" + time.strftime("%Y%m%d-%H%M%S")))
    args = parser.parse_args()
    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0
    if not args.capture:
        parser.print_help()
        return 0
    if not args.reference or not .01 <= args.gain <= 1:
        parser.error("--capture requires --reference and gain between .01 and 1")
    return capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
