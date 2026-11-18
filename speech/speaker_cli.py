"""Compare two local WAV files without storing audio or enrollment templates."""

import argparse
import json
from pathlib import Path

import numpy as np

from .server import read_wav
from .speaker import SpeakerQuality, speaker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    speaker.initialize()
    vectors = []
    for path in (args.first, args.second):
        audio = read_wav(path.read_bytes())
        vectors.append(speaker.embedding(audio))
    score = float(np.dot(vectors[0][0], vectors[1][0]))
    print(json.dumps({"similarity": round(score, 4), "voiced_seconds": [round(v[1], 2) for v in vectors], "not_authentication": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
