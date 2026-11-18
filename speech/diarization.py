"""Offline speaker clustering diagnostic; labels do not identify a person."""

import argparse
import json
import time
from pathlib import Path

from dafeiyu_paths import models_dir

from .server import read_wav


def diarize(wav_path, segmentation_path, embedding_path, speakers=-1):
    import sherpa_onnx
    audio = read_wav(Path(wav_path).read_bytes())
    duration = len(audio) / 16000
    if speakers == 0 or speakers < -1 or speakers > 10:
        raise ValueError("speakers must be -1 or between 1 and 10")
    if not Path(segmentation_path).is_file() or not Path(embedding_path).is_file():
        raise ValueError("segmentation or embedding model missing")
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation_path), window_shift_ratio=0.1), num_threads=2, provider="cpu"),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding_path), num_threads=2, provider="cpu"),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=speakers, threshold=0.5), min_duration_on=0.3, min_duration_off=0.5,
    )
    if not config.validate():
        raise ValueError("invalid diarization model configuration")
    start = time.perf_counter()
    model = sherpa_onnx.OfflineSpeakerDiarization(config)
    segments = model.process(audio).sort_by_start_time()
    return {"mode": "offline_diagnostic", "device": "CPU", "identity_verified": False, "duration_s": duration, "elapsed_s": time.perf_counter() - start, "segments": [{"start_s": s.start, "end_s": s.end, "speaker": s.speaker} for s in segments]}


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Offline speaker clustering diagnostic, not identity verification")
    parser.add_argument("wav")
    parser.add_argument("--speakers", type=int, default=-1)
    parser.add_argument("--segmentation", default=str(models_dir(root) / "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"))
    parser.add_argument("--embedding", default=str(models_dir(root) / "speaker-eres2net/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"))
    args = parser.parse_args()
    print(json.dumps(diarize(args.wav, args.segmentation, args.embedding, args.speakers), ensure_ascii=False))


if __name__ == "__main__":
    main()
