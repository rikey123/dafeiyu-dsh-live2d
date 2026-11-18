"""Prepare pinned GPT-SoVITS v5 turbo and an isolated CUDA runtime in DAFEIYU_HOME."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile
import base64

from prepare_tts_models import BASE, ROOT, download, request
from dafeiyu_paths import models_dir, cache_dir

REVISION = "6d51ffceafbf240145619af4c92408a6e54b7924"
SOURCE = BASE / "source/gpt-sovits-v5"
MODEL = models_dir(ROOT) / "gpt-sovits-v5"
RUNTIME = BASE / "runtimes/gpt-sovits-py311"


def junction(link, target):
    # Both source and preservation target must stay within our chosen source
    # tree before a directory is renamed. Do not move across shell boundaries.
    source_root = SOURCE.resolve()
    if not link.parent.resolve().is_relative_to(source_root):
        raise ValueError("Junction must belong to the configured GPT-SoVITS source")
    if link.exists():
        if link.resolve() != target.resolve():
            # Upstream ships small example files here. Do not remove them.
            for child in link.iterdir():
                destination = target / child.name
                if child.is_file() and not destination.exists():
                    shutil.copy2(child, destination)
            if any(link.iterdir()):
                backup = link.with_name(link.name + "-upstream")
                if not link.resolve().is_relative_to(source_root) or not backup.resolve().is_relative_to(source_root):
                    raise ValueError("Preserved source directory escapes the configured source")
                if backup.exists():
                    raise ValueError(f"Cannot preserve existing directory: {link}")
                link.rename(backup)
            else:
                link.rmdir()
        else:
            return
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path " + quote(link) + " -Target " + quote(target) + " | Out-Null"
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], check=True)


def prepare_models():
    endpoint = "https://hf-mirror.com"
    with request(endpoint + "/api/models/lj1995/GPT-SoVITS") as response:
        revision = json.load(response)["sha"]
    with request(endpoint + f"/api/models/lj1995/GPT-SoVITS/tree/{revision}?recursive=true&limit=1000") as response:
        rows = json.load(response)
    allow = {"s1v3.ckpt", "gsv-v5-pretrained/s2Gv5turbo.pth", "gsv-v5-pretrained/vocoder.pth"}
    allow.update(row["path"] for row in rows if row["type"] == "file" and row["path"].startswith(
        ("chinese-hubert-base/", "chinese-roberta-wwm-ext-large/")))
    selected = [row for row in rows if row["path"] in allow]
    if {row["path"] for row in selected} != allow:
        raise ValueError("Required GPT-SoVITS assets are missing")
    def fetch(row):
        download(endpoint + f"/lj1995/GPT-SoVITS/resolve/{revision}/{row['path']}?download=true",
                 MODEL / row["path"], row.get("lfs", {}).get("oid"), row["size"])
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch, selected))
    with request("https://modelscope.cn/api/v1/models/XXXXRT/GPT-SoVITS-Pretrained/repo/files?Revision=master&Recursive=true") as response:
        data = json.load(response)
    row = next(row for row in data["Data"]["Files"] if row["Path"] == "G2PWModel.zip")
    archive = cache_dir(ROOT) / "G2PWModel.zip"
    download("https://modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/" + row["Revision"] + "/G2PWModel.zip",
             archive, row["Sha256"], row["Size"])
    target = MODEL / "g2pw"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            if member.is_dir():
                continue
            parts = Path(member.filename.replace("\\", "/")).parts
            if parts[0].lower().startswith("g2pw"):
                parts = parts[1:]
            output = target.joinpath(*parts).resolve()
            if not output.is_relative_to(target.resolve()):
                raise ValueError("Unsafe G2PW archive")
            output.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as data, output.open("wb") as out:
                shutil.copyfileobj(data, out)
    junction(SOURCE / "GPT_SoVITS/pretrained_models", MODEL)
    junction(SOURCE / "GPT_SoVITS/text/G2PWModel", target)
    (MODEL / "dafeiyu-download.json").write_text(json.dumps({
        "repository": "lj1995/GPT-SoVITS", "revision": revision, "mirror": endpoint,
        "files": selected, "g2pw": row}, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--skip-models", action="store_true")
    args = parser.parse_args()
    cache = cache_dir(ROOT)
    for path in (cache / "tmp", cache / "uv", MODEL, SOURCE):
        path.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(cache / "tmp"), "TMP": str(cache / "tmp"),
           "UV_CACHE_DIR": str(cache / "uv"), "UV_PYTHON_INSTALL_DIR": str(BASE / "runtimes/python"),
           "UV_HTTP_TIMEOUT": "120", "PYTHONUTF8": "1", "NLTK_DATA": str(cache / "nltk")}
    archive = cache / f"gpt-sovits-{REVISION}.tar.gz"
    download(f"https://codeload.github.com/RVC-Boss/GPT-SoVITS/tar.gz/{REVISION}", archive)
    marker = SOURCE / "dafeiyu-source.json"
    if marker.is_file() and json.loads(marker.read_text(encoding="utf-8")).get("revision") != REVISION:
        raise ValueError("GPT-SoVITS source revision differs; use a separate source directory")
    if not marker.is_file():
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts[1:]
                if not parts:
                    continue
                target = SOURCE.joinpath(*parts).resolve()
                if not target.is_relative_to(SOURCE.resolve()) or member.issym() or member.islnk():
                    raise ValueError("Unsafe source archive")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as data, target.open("wb") as out:
                        shutil.copyfileobj(data, out)
        marker.write_text(json.dumps({"repo": "RVC-Boss/GPT-SoVITS", "revision": REVISION}), encoding="utf-8")
    if not args.skip_models:
        prepare_models()
    if not args.skip_runtime:
        uv = os.environ.get("DAFEIYU_UV") or shutil.which("uv")
        if not uv:
            raise FileNotFoundError("Install uv or set DAFEIYU_UV to its executable path")
        python = RUNTIME / "Scripts/python.exe"
        if not python.is_file():
            subprocess.run([uv, "venv", str(RUNTIME), "--python", "3.11"], env=env, check=True)
        torch = cache / "wheels/torch-2.8.0+cu128-cp311-cp311-win_amd64.whl"
        download("https://download.pytorch.org/whl/cu128/torch-2.8.0%2Bcu128-cp311-cp311-win_amd64.whl", torch,
                 "34c55443aafd31046a7963b63d30bc3b628ee4a704f826796c865fdfd05bb596", 3461420395)
        subprocess.run([uv, "pip", "install", "--python", str(python), "--link-mode", "copy",
                        "--index-url", "https://download.pytorch.org/whl/cu128", str(torch), "torchaudio==2.8.0"], env=env, check=True)
        subprocess.run([uv, "pip", "install", "--python", str(python), "--link-mode", "copy",
                        "--index-url", "https://mirrors.aliyun.com/pypi/simple", "-r", str(ROOT / "requirements-tts-gpt-sovits.txt")], env=env, check=True)
        locked = subprocess.check_output([uv, "pip", "freeze", "--python", str(python)], env=env, text=True)
        (RUNTIME / "dafeiyu-requirements.lock.txt").write_text(locked, encoding="utf-8")
    print("GPT-SoVITS v5 turbo preparation complete; no inference started.", flush=True)


if __name__ == "__main__":
    main()
