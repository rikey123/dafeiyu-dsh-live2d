"""Download and verify sherpa's pyannote segmentation diagnostic model."""

import hashlib
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from dafeiyu_paths import models_dir

URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
SHA256 = "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488"


def main():
    root = Path(__file__).resolve().parent.parent
    target = models_dir(root) / "sherpa-onnx-pyannote-segmentation-3-0"
    if target.exists():
        raise ValueError(f"Model directory already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix="diarization-") as tmp:
        temp = Path(tmp)
        archive_path = temp / "model.tar.bz2"
        urllib.request.urlretrieve(URL, archive_path)
        digest = hashlib.sha256()
        with archive_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != SHA256:
            raise ValueError("diarization archive SHA-256 mismatch")
        staging = temp / "model"
        staging.mkdir()
        with tarfile.open(archive_path, "r:bz2") as archive:
            for name in ("model.onnx", "LICENSE", "README.md"):
                source = archive.extractfile(f"sherpa-onnx-pyannote-segmentation-3-0/{name}")
                if source is None:
                    raise ValueError(f"missing model file: {name}")
                with source, (staging / name).open("wb") as output:
                    shutil.copyfileobj(source, output)
        staging.rename(target)
    print(f"Ready: {target}")


if __name__ == "__main__":
    main()
