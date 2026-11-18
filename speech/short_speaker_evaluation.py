"""Offline short-window speaker evaluation; never used for production decisions."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .server import read_wav
from .speaker import SpeakerQuality, SpeakerService, THRESHOLD

WINDOWS = (0.5, 1.0, 1.5, 2.0)


def experimental_embedding(service, audio):
    """Score a short VAD-filtered sample without changing the production gate."""
    return service._embedding(audio, minimum_voiced_seconds=0.1)


def window_trials(service, audio, score_embedding):
    """Measure independent prefix lengths; caller supplies labels and statistics."""
    rows = []
    for seconds in WINDOWS:
        segment = audio[:round(seconds * 16000)]
        try:
            vector, voiced = experimental_embedding(service, segment)
            score, reason = float(score_embedding(vector)), "scored"
        except SpeakerQuality as exc:
            voiced, score, reason = exc.voiced_seconds, None, "insufficient_speech"
        if len(segment) < round(seconds * 16000):
            score, reason = None, "insufficient_recording"
        rows.append({"window_s": seconds, "actual_duration_s": len(segment) / 16000, "voiced_seconds": voiced, "score": score, "reason": reason})
    return rows


def evaluate(manifest_path, service=None):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    enrollment, cases = manifest["enrollment"], manifest["cases"]
    if not 2 <= len(enrollment) <= 5 or not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("requires 2-5 enrollment samples and unique labelled cases")
    if any(type(case.get("expected_owner")) is not bool or case.get("kind", "speech") not in {"speech", "noise", "silence"} or (case["expected_owner"] and case.get("kind", "speech") != "speech") for case in cases):
        raise ValueError("invalid expected_owner or kind")
    service = service or SpeakerService()
    service.initialize()
    vectors, seen = [], set()
    def load(name):
        data = (manifest_path.parent / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            raise ValueError("enrollment and test recordings must be independent")
        seen.add(digest)
        return read_wav(data), digest
    for name in enrollment:
        audio, _ = load(name)
        vectors.append(service.embedding(audio)[0])
    if any(float(np.dot(a, b)) < THRESHOLD for i, a in enumerate(vectors) for b in vectors[:i]):
        raise ValueError("enrollment fails production consistency gate")
    reference = np.mean(vectors, axis=0)
    norm = np.linalg.norm(reference)
    if not np.isfinite(norm) or norm <= 0:
        raise ValueError("invalid enrollment reference")
    reference /= norm
    rows = []
    for case in cases:
        audio, digest = load(case["path"])
        for trial in window_trials(service, audio, lambda vector: np.dot(reference, vector)):
            score = trial["score"]
            accepted = score >= THRESHOLD if score is not None else None
            rows.append({"id": case["id"], "kind": case.get("kind", "speech"),
                         "expected_owner": case["expected_owner"], "audio_sha256": digest,
                         **trial, "accepted": accepted})
    summaries = []
    for window in WINDOWS:
        selected = [r for r in rows if r["window_s"] == window]
        owners = [r for r in selected if r["expected_owner"]]
        others = [r for r in selected if not r["expected_owner"] and r["kind"] == "speech"]
        nonspeech = [r for r in selected if r["kind"] != "speech"]
        false_accepts = sum(r["accepted"] is True for r in others)
        rejected = sum(r["accepted"] is not True for r in owners)
        summaries.append({"window_s": window, "owner_trials": len(owners), "other_speech_trials": len(others), "nonspeech_trials": len(nonspeech), "false_accepts": false_accepts, "far": false_accepts / len(others) if others else None, "effective_owner_rejections": rejected, "effective_frr": rejected / len(owners) if owners else None, "nonspeech_false_accepts": sum(r["accepted"] is True for r in nonspeech), "uncertain": sum(r["accepted"] is None for r in selected)})
    return {"mode": "offline_experimental_short_window", "provenance": manifest.get("provenance", "unspecified"), "production_gate_changed": False, "threshold": THRESHOLD, "window_crop": "prefix from each independent test recording; not independent trials across windows", "limitations": "Exploratory only; synthetic samples do not establish human FAR/FRR, replay resistance, or production readiness. Short-window scores are not identity authentication.", "results": rows, "summary": summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
