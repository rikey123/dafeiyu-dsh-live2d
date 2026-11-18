"""Download and verify pinned CosyVoice weights; does not install dependencies."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import urllib.request

REVISION = "eec1ae6c79877dbd9379285cf8789c9e0879293d"
FILES = {
    "llm.pt": (2023316821, "b144ef55b51ce8cfb79a73c90dbba0bdaba4e451c0ebcfab20f769264f84a608"),
    "flow.pt": (450575567, "ff4c2f867674411e0a08cee702996df13fa67c1cd864c06108da88d16d088541"),
    "hift.pt": (83390254, "3386cc880324d4e98e05987b99107f49e40ed925b8ecc87c1f4939432d429879"),
    "campplus.onnx": (28303423, "a6ac6a63997761ae2997373e2ee1c47040854b4b759ea41ec48e4e42df0f4d73"),
    "speech_tokenizer_v2.onnx": (496082973, "d43342aa12163a80bf07bffb94c9de2e120a8df2f9917cd2f642e7f4219c6f71"),
    "CosyVoice-BlankEN/model.safetensors": (988097824, "130282af0dfa9fe5840737cc49a0d339d06075f83c5a315c3372c9a0740d0b96"),
}
SMALL_FILES = {
    "cosyvoice2.yaml": (7330, "bc19267bbfd373c9a760b7667a74349ddd487db1"),
    "CosyVoice-BlankEN/config.json": (659, "463b055262b6c66c4629a74a4b300bfe2ed31d3c"),
    "CosyVoice-BlankEN/generation_config.json": (242, "dfc11073787daf1b0f9c0f1499487ab5f4c93738"),
    "CosyVoice-BlankEN/merges.txt": (1402109, "90d3d82d027eadcc6a5e77c38eb82d43fc51b53b"),
    "CosyVoice-BlankEN/tokenizer_config.json": (1287, "ff55d7b9eb1384e5d4d7e75dc0f564c1a8833d6e"),
    "CosyVoice-BlankEN/vocab.json": (2776833, "4783fe10ac3adce15ac8f358ef5462739852c569"),
}
V3_REVISION = "29e01c4e8d000f4bcd70751be16fa94bf3d85a18"
V3_FILES = {
    "llm.pt": (2024669519, "69f43bd545131c30e98947fb360ea8b4dc9916d8e83dded7757c7ea4f5a24970"),
    "flow.pt": (1329116148, "a6fab32a7825e5b0bc855ddd948f8db9370b0a786fbc249caa4595e95b608e4b"),
    "hift.pt": (83202622, "b279d7641eb97ae55b3b540cfba4f953c26492a2df758328a89a4d007ab87a65"),
    "speech_tokenizer_v3.onnx": (969451503, "23236a74175dbdda47afc66dbadd5bcb41303c467a57c261cb8539ad9db9208d"),
    "campplus.onnx": FILES["campplus.onnx"],
    "CosyVoice-BlankEN/model.safetensors": FILES["CosyVoice-BlankEN/model.safetensors"],
}
V3_SMALL_FILES = {**{name: spec for name, spec in SMALL_FILES.items() if name != "cosyvoice2.yaml"},
                  "cosyvoice3.yaml": (6934, "2eda7e5007d99f6b17fbe7bd751cf54e3cde29ea")}


def verify(path: Path, size: int, digest: str, *, git_blob=False) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    checksum = hashlib.sha1() if git_blob else hashlib.sha256()
    if git_blob:
        checksum.update(f"blob {size}\0".encode())
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest() == digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--version", choices=("2", "3"), default="3")
    args = parser.parse_args()
    files, small, revision, repo = ((FILES, SMALL_FILES, REVISION, "CosyVoice2-0.5B") if args.version == "2" else
                                    (V3_FILES, V3_SMALL_FILES, V3_REVISION, "Fun-CosyVoice3-0.5B-2512"))
    for name in (*files, *small):
        path = args.directory / name
        spec = files.get(name) or small[name]
        valid = verify(path, *spec, git_blob=name in small)
        if not valid and args.verify_only:
            raise SystemExit(f"Missing or invalid: {name}")
        if not valid:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".download")
            url = f"https://huggingface.co/FunAudioLLM/{repo}/resolve/{revision}/{name}"
            with urllib.request.urlopen(url, timeout=60) as source, temp.open("wb") as target:
                while block := source.read(1024 * 1024):
                    target.write(block)
            if not verify(temp, *spec, git_blob=name in small):
                raise SystemExit(f"Checksum mismatch: {name}")
            temp.replace(path)
        print(f"verified {name}")


if __name__ == "__main__":
    main()
