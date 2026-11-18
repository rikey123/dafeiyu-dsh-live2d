"""Download official/community models separately from server startup."""

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from dafeiyu_paths import models_dir, home_dir
import os

ROOT = Path(__file__).resolve().parent.parent
VAD_URL = "https://unpkg.com/@ricky0123/vad-web@0.0.24/dist/silero_vad_v5.onnx"
VAD_SHA256 = "2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f"
MODELS = {
    "asr": ("Systran/faster-whisper-base", "faster-whisper-base"),
    "sensevoice": ("csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17", "sensevoice"),
    "openvino": ("OpenVINO/whisper-base-int8-ov", "whisper-base-openvino"),
    "tts": ("csukuangfj/sherpa-onnx-vits-zh-ll", "sherpa-onnx-vits-zh-ll"),
    "speaker": ("onemira/eres2net-base-3dspeaker-onnx", "speaker-eres2net"),
    "streaming-asr": ("csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20", "streaming-zipformer-zh-en"),
    "zipvoice": ("sherpa-onnx ZipVoice release", "zipvoice-zh-en"),
    "kokoro": ("csukuangfj/kokoro-int8-multi-lang-v1_0", "kokoro-int8-multi-lang-v1_0"),
    "forced-aligner": ("Qwen/Qwen3-ForcedAligner-0.6B", "qwen3-forced-aligner-0.6b"),
}

KOKORO_HASHES = {
    "model.int8.onnx": "75635ea3b85a32d00094dcdd61a258aba87c160f7c264c304a7b3ae9d734195e",
    "voices.bin": "1c5a5b983d3d50d8586d437a51f3faa2da7919ce76a013c081e65671a3447c29",
    "tokens.txt": "6ebb6bb288f20f3ae8d004d3c2ca27697da27c037d75e81a60e2a6a663f95425",
    "lexicon-us-en.txt": "7daaab53a181be9885b853a8582bf1838186317e5dadacbcef9c426d6fa0da14",
    "lexicon-zh.txt": "902bc2d20ac7c449c5ecbbbb23c89d12119c03ed5b8ed27f114f0260c9e35229",
    "phone-zh.fst": "1ac2b6fa56b1442320c4de7db08353bab8963a2b57f365eebcdd3a2d3562f8d7",
    "date-zh.fst": "eb8aa079ae3cb81d8f4404992f39d61a0cb990947512b5b8d1e54d1f6980e718",
    "number-zh.fst": "743f402181fcfebf76cc2f0546b71fa26476e626fbe4e460fb7b4c3a7a8bd5bd",
}

ZIP_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
ZIP_ARCHIVE = "sherpa-onnx-zipvoice-distill-int8-zh-en-emilia.tar.bz2"
ZIP_DOWNLOADS = {
    ZIP_ARCHIVE: (ZIP_BASE + "tts-models/" + ZIP_ARCHIVE, "77219c8b40f4ee8d73a7f902305ff6c1128ef9b54461c41b4ca6ed890b6c2803"),
    "vocos_24khz.onnx": (ZIP_BASE + "vocoder-models/vocos_24khz.onnx", "bcb3b970e384161c4d634f0bb9e999ff1c471b34c9bc0b1049a5014065ed3cc0"),
    "lexicon-en-us.txt": (ZIP_BASE + "tts-models/lexicon-en-us.txt", "8b67ae549a465eee78f92ecb74644ad90c3c58ce65f19c68baf85878a10ef73a"),
}
ZIP_FILES = {
    "encoder.int8.onnx": "f2de9a761a85e5ddd125dee6e05bad1c7ee92c11b83b4d775dab216a6aa41379",
    "decoder.int8.onnx": "3cc2e08a96610d7ea1b227398e97cdbbe0414499741d3aec0b8113db2a2ab251",
    "tokens.txt": "ce98c1afc5f7a20c2484dffdd68a1fff0a4a2cc707328833750c4476c37cdbda",
    "lexicon.txt": "c94b049d970e971acdc2a7e5e7b23ca594222a9d640e417c711f2ad1e7bb7d46",
    **{name: value[1] for name, value in ZIP_DOWNLOADS.items() if name != ZIP_ARCHIVE},
}


def verify_hash(path, expected):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch: {path.name}")


def prepare_vad():
    """Fetch the pinned CPU VAD required by ASR gating and speaker enrollment."""
    public = home_dir(ROOT) / "public" if os.environ.get("DAFEIYU_HOME") else ROOT / "web/public"
    target = public / "vad/silero_vad_v5.onnx"
    if target.is_file():
        verify_hash(target, VAD_SHA256)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix="vad-prepare-") as tmp:
        download = Path(tmp) / target.name
        with urllib.request.urlopen(VAD_URL, timeout=60) as response, download.open("wb") as output:
            shutil.copyfileobj(response, output)
        verify_hash(download, VAD_SHA256)
        download.replace(target)
    target.with_suffix(".source.json").write_text(json.dumps({"url": VAD_URL, "sha256": VAD_SHA256,
        "upstream": "snakers4/silero-vad", "license": "https://github.com/snakers4/silero-vad/blob/v5.1.2/LICENSE"}, indent=2), encoding="utf-8")
    return target


def prepare_zipvoice(target):
    if target.is_dir():
        try:
            for name, digest in ZIP_FILES.items():
                verify_hash(target / name, digest)
            return
        except (OSError, ValueError):
            raise ValueError(f"Existing ZipVoice directory is incomplete or modified: {target}") from None
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix="zipvoice-prepare-") as tmp:
        temp = Path(tmp)
        for name, (url, digest) in ZIP_DOWNLOADS.items():
            print(f"Downloading {name}", flush=True)
            urllib.request.urlretrieve(url, temp / name)
            verify_hash(temp / name, digest)
        staging = temp / "model"
        staging.mkdir()
        with tarfile.open(temp / ZIP_ARCHIVE, "r:bz2") as archive:
            for name in ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt", "lexicon.txt"):
                source = archive.extractfile(f"sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/{name}")
                if source is None:
                    raise ValueError(f"Missing model file: {name}")
                with source, (staging / name).open("wb") as output:
                    shutil.copyfileobj(source, output)
        for name in ("vocos_24khz.onnx", "lexicon-en-us.txt"):
            shutil.copyfile(temp / name, staging / name)
        for name, digest in ZIP_FILES.items():
            verify_hash(staging / name, digest)
        staging.rename(target)

STREAM_HASHES = {
    "tokens.txt": "a8e0e4ec53810e433789b54a5c0134a7eaa2ffca595a6334d54c00da858841d3",
    "encoder-epoch-99-avg-1.int8.onnx": "8fa764187a261844f859d7143ebaa563af5d10adfece4c18a8f414c88cba2a9b",
    "decoder-epoch-99-avg-1.onnx": "2e3b5ec371f8899ee6acd829fd753ba45772df57a91bdf37cde3136354e7db7d",
    "joiner-epoch-99-avg-1.int8.onnx": "1ed689c5ed19dbaa725d9d191bb4822b5f4855a39e1ffd28cbc1f340d25b2ee0",
}


def verify_streaming_model(target):
    for name, expected in STREAM_HASHES.items():
        digest = hashlib.sha256()
        with (target / name).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"SHA-256 mismatch: {name}")


def main():
    parser = argparse.ArgumentParser(description="Prepare local speech models; safe to rerun after an interrupted download.")
    parser.add_argument("models", nargs="+", choices=list(MODELS))
    args = parser.parse_args()
    for name in args.models:
        if name in {"sensevoice", "speaker", "streaming-asr"}:
            print(f"VAD ready: {prepare_vad()}", flush=True)
        repo, folder = MODELS[name]
        target = models_dir(ROOT) / folder
        print(f"Downloading {repo} to {target}", flush=True)
        if name == "zipvoice":
            prepare_zipvoice(target)
            print(f"Ready: {target}", flush=True)
            continue
        kwargs = {"allow_patterns": ["model.int8.onnx", "tokens.txt", "LICENSE", "README.md"]} if name == "sensevoice" else {}
        if name == "speaker":
            kwargs = {"revision": "94b441c56126883d212425ab108fa46f35775adf", "allow_patterns": ["*.onnx", "LICENSE*", "NOTICE", "README.md", "source-metadata.json"]}
        if name == "streaming-asr":
            kwargs = {"revision": "98590b7ed6443e77b714204da2757d75e1a642f4", "allow_patterns": [*STREAM_HASHES, "README.md", "LICENSE*"]}
        if name == "kokoro":
            kwargs = {"revision": "57adb37fc0e8d4bd430cfc1b8f8c2294945b9af2", "allow_patterns": [*KOKORO_HASHES, "README.md", "LICENSE"]}
        if name == "forced-aligner":
            kwargs = {"revision": "c7cbfc2048c462b0d63a45797104fc9db3ad62b7"}
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=repo, local_dir=target, max_workers=4, **kwargs)
        if name == "streaming-asr":
            verify_streaming_model(target)
        if name == "kokoro":
            for filename, expected in KOKORO_HASHES.items():
                verify_hash(target / filename, expected)
        if name == "forced-aligner":
            verify_hash(target / "model.safetensors", "47831d0e82f96b20e9034dba01a075ee06436654719f6a68289e49f1b65ce0e7")
        print(f"Ready: {target}", flush=True)


if __name__ == "__main__":
    main()
