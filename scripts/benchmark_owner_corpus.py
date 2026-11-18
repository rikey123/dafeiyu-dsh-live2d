"""Evaluate labelled local owner/other WAVs without changing any enrollment.

Manifest: {provenance, enrollment: [relative.wav, ...], cases:
[{id, path, expected_owner: true|false}]}. Keep enrollment and test recordings
independent. Unknown/short owner trials count as effective rejections. This is
an offline evaluation, not an automatic threshold tuner or anti-replay test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from speech.server import read_wav
from speech.speaker import SpeakerQuality, THRESHOLD, speaker


def evaluate(manifest_path, output):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    enrollment, cases = manifest["enrollment"], manifest["cases"]
    if not 2 <= len(enrollment) <= 5 or not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Use 2–5 enrollment recordings and unique test IDs")
    if any(type(c.get("expected_owner")) is not bool for c in cases):
        raise ValueError("Every test needs an explicit Boolean owner label")
    if any(c.get("kind", "speech") not in {"speech", "noise", "silence"} or (c["expected_owner"] and c.get("kind", "speech") != "speech") for c in cases):
        raise ValueError("Use speech/noise/silence kinds; owner trials must be speech")
    speaker.initialize()
    vectors, enrollment_hashes = [], set()
    for name in enrollment:
        data = (manifest_path.parent / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in enrollment_hashes:
            raise ValueError("Enrollment recordings must be independent files")
        enrollment_hashes.add(digest)
        vectors.append(speaker.embedding(read_wav(data))[0])
    pair_scores = [float(np.dot(a, b)) for i, a in enumerate(vectors) for b in vectors[:i]]
    if any(score < THRESHOLD for score in pair_scores):
        raise ValueError("Enrollment voices fail the production consistency gate")
    reference = np.mean(vectors, axis=0)
    reference /= np.linalg.norm(reference)
    rows, seen = [], set()
    for case in cases:
        data = (manifest_path.parent / case["path"]).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in enrollment_hashes or digest in seen:
            raise ValueError("Test audio cannot duplicate enrollment or another test")
        seen.add(digest)
        started = time.perf_counter()
        try:
            vector, voiced = speaker.embedding(read_wav(data))
            score = float(np.dot(reference, vector))
            accepted, reason = score >= THRESHOLD, "scored"
        except SpeakerQuality as exc:
            accepted, score, voiced, reason = None, None, exc.voiced_seconds, "insufficient_speech"
        rows.append({"id": case["id"], "kind": case.get("kind", "speech"), "expected_owner": case["expected_owner"], "accepted": accepted,
                     "score": score, "reason": reason, "voiced_seconds": voiced,
                     "audio_sha256": digest, "processing_seconds": time.perf_counter() - started})
    owners = [r for r in rows if r["expected_owner"]]
    others = [r for r in rows if not r["expected_owner"] and r["kind"] == "speech"]
    non_speech = [r for r in rows if r["kind"] != "speech"]
    false_accepts = sum(r["accepted"] is True for r in others)
    effective_rejects = sum(r["accepted"] is not True for r in owners)
    scored_owners = [r for r in owners if r["accepted"] is not None]
    scored_rejects = sum(r["accepted"] is False for r in scored_owners)
    report = {"provenance": manifest.get("provenance", "unspecified; not human acceptance"),
              "threshold": THRESHOLD, "threshold_tuned": False, "production_profile_modified": False,
              "enrollment_sha256": sorted(enrollment_hashes), "enrollment_pair_scores": pair_scores,
              "results": rows, "summary": {
                  "owner_trials": len(owners), "other_trials": len(others),
                  "false_accepts": false_accepts, "far": false_accepts / len(others) if others else None,
                  "non_speech_trials": len(non_speech), "non_speech_false_accepts": sum(r["accepted"] is True for r in non_speech),
                  "effective_owner_rejections": effective_rejects,
                  "effective_frr": effective_rejects / len(owners) if owners else None,
                  "scored_owner_trials": len(scored_owners), "scored_owner_rejections": scored_rejects,
                  "scored_frr": scored_rejects / len(scored_owners) if scored_owners else None,
                  "uncertain_trials": sum(r["accepted"] is None for r in rows)},
              "limitations": "Short/unknown owner trials count as effective rejection. Scored-only FRR has a separate denominator. Non-speech trials are excluded from impostor FAR. No threshold fitting, identity cache bypass, online overlapping separation, physical AEC or replay resistance inferred. Synthetic trials do not establish human FAR/FRR."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/owner-corpus/results.json")
    args = parser.parse_args()
    evaluate(args.manifest.resolve(), args.output)
