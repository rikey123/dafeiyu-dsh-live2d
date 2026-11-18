"""Prepare isolated speech runtimes and verified official model assets in DAFEIYU_HOME.

Usage: .venv/Scripts/python scripts/prepare_tts_models.py --kind moss
       .venv/Scripts/python scripts/prepare_tts_models.py --kind index
No inference starts and no API credentials are required. Downloads are explicit.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.parse
import urllib.request
import time
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dafeiyu_paths import home_dir, models_dir as user_models_dir, cache_dir as user_cache_dir
BASE = home_dir(ROOT)
SOURCES = {
    "moss": ("OpenMOSS/MOSS-TTS-Nano", "8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb", "moss-tts-nano", "moss-tts"),
    "index": ("index-tts/index-tts", "d9e41aac89fd00b3d71497fddb287b7f24613712", "index-tts-2.5", "index-tts-py311"),
}


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Dafeiyu-local-model-setup/1.0"}), timeout=60)


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for data in iter(lambda: handle.read(4*1024*1024), b""):
            digest.update(data)
    return digest.hexdigest()


def download(url, path, expected=None, size=None):
    """Resume bounded HTTP ranges; always verify complete files before promotion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and (size is None or path.stat().st_size == size) and (expected is None or checksum(path) == expected):
        return
    part = path.with_name(path.name + ".part")
    if size and part.is_file() and part.stat().st_size > size:
        part.unlink()
    last_report = time.monotonic()
    for attempt in range(5):
        try:
            if size and size > 16 * 1024 * 1024:
                offset = part.stat().st_size if part.exists() else 0
                ranges = path.with_name(path.name + ".ranges")
                ranges.mkdir(exist_ok=True)
                blocks = [(start, min(start + 8 * 1024 * 1024, size) - 1)
                          for start in range(offset, size, 8 * 1024 * 1024)]
                def fetch_range(block):
                    start, end = block
                    target = ranges / str(start)
                    length = end - start + 1
                    if target.is_file() and target.stat().st_size == length:
                        return target
                    for retry in range(5):
                        try:
                            req = urllib.request.Request(url, headers={
                                "User-Agent": "Dafeiyu-local-model-setup/1.0",
                                "Range": f"bytes={start}-{end}"})
                            with urllib.request.urlopen(req, timeout=20) as response:
                                if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-{end}/"):
                                    raise ValueError("Server does not honor bounded HTTP ranges")
                                with target.open("wb") as output:
                                    remaining = length
                                    deadline = time.monotonic() + 90
                                    while remaining:
                                        if time.monotonic() > deadline:
                                            raise TimeoutError("Download range exceeded its deadline")
                                        chunk = response.read1(min(1024 * 1024, remaining))
                                        if not chunk:
                                            raise IOError("Download range ended early")
                                        output.write(chunk)
                                        remaining -= len(chunk)
                            return target
                        except (OSError, ValueError):
                            target.unlink(missing_ok=True)
                            if retry == 4:
                                raise
                            time.sleep(min(2 ** retry, 8))
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for target in pool.map(fetch_range, blocks):
                        with target.open("rb") as data, part.open("ab") as output:
                            shutil.copyfileobj(data, output, 1024 * 1024)
                        target.unlink()
                        if time.monotonic() - last_report > 15:
                            print(f"Downloading {path.name}: {part.stat().st_size:,}/{size:,}", flush=True)
                            last_report = time.monotonic()
                # Interrupted runs may leave obsolete range offsets. Only this
                # file's private staging directory is eligible for cleanup.
                for stale in ranges.iterdir():
                    if stale.is_file() and stale.name.isdecimal():
                        stale.unlink()
                ranges.rmdir()
            else:
                with request(url) as response, part.open("wb") as output:
                    shutil.copyfileobj(response, output, 1024 * 1024)
            if (size is not None and part.stat().st_size != size) or (expected and checksum(part) != expected):
                part.unlink(missing_ok=True)
                raise ValueError(f"Incomplete or corrupted download: {path.name}")
            part.replace(path)
            print(f"Downloaded {path.name} ({path.stat().st_size:,} bytes)", flush=True)
            return
        except (OSError, ValueError) as exc:
            if attempt == 4:
                raise
            print(f"Retry {attempt + 1}/4 for {path.name}: {type(exc).__name__}", flush=True)
            time.sleep(min(2 ** attempt, 8))


def modelscope_snapshot(repo, directory, allow=None):
    with request(f"https://modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true") as response:
        payload = json.load(response)
    if payload.get("Code") != 200:
        raise RuntimeError(f"ModelScope file listing failed: {repo}")
    files = [row for row in payload["Data"]["Files"] if row["Type"] == "blob" and row["Path"] != ".gitattributes"
             and (allow is None or row["Path"] in allow)]
    if allow is not None and set(allow) - {row["Path"] for row in files}:
        raise ValueError(f"Required model files missing from {repo}")
    def fetch(row):
        target = (directory / row["Path"]).resolve()
        if not target.is_relative_to(directory.resolve()):
            raise ValueError("Unsafe repository file path")
        query = urllib.parse.urlencode({"Revision": row["Revision"], "FilePath": row["Path"]})
        download(f"https://modelscope.cn/api/v1/models/{repo}/repo?{query}", target, row.get("Sha256"), row["Size"])
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch, files))
    (directory / "dafeiyu-download.json").write_text(json.dumps({"repository": repo, "files": files}, ensure_ascii=False, indent=2), encoding="utf-8")


def huggingface_mirror_files(repo, directory, allow):
    # The official NVIDIA BigVGAN repo has no ModelScope counterpart. Preserve
    # the upstream revision and LFS digest when using the reachable HF mirror.
    endpoint = "https://hf-mirror.com"
    with request(f"{endpoint}/api/models/{repo}") as response:
        revision = json.load(response)["sha"]
    with request(f"{endpoint}/api/models/{repo}/tree/{revision}?recursive=true") as response:
        rows = json.load(response)
    selected = [row for row in rows if row["path"] in allow]
    if {row["path"] for row in selected} != set(allow):
        raise ValueError("Missing required HuggingFace files")
    for row in selected:
        expected = row.get("lfs", {}).get("oid")
        download(f"{endpoint}/{repo}/resolve/{revision}/{row['path']}?download=true",
                 directory/row["path"], expected, row["size"])
    (directory/"dafeiyu-download.json").write_text(json.dumps({
        "repository": repo, "revision": revision, "mirror": endpoint, "files": selected}, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=SOURCES, required=True)
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--index-url", default="https://mirrors.aliyun.com/pypi/simple")
    args = parser.parse_args()
    repo, revision, folder, runtime_name = SOURCES[args.kind]
    cache = user_cache_dir(ROOT)
    for path in (cache / "tmp", cache / "uv", cache / "huggingface", cache / "torch"):
        path.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(cache/"tmp"), "TMP": str(cache/"tmp"), "UV_CACHE_DIR": str(cache/"uv"),
           "UV_PYTHON_INSTALL_DIR": str(BASE/"runtimes/python"), "UV_HTTP_TIMEOUT": "60",
           "HF_HOME": str(cache/"huggingface"), "TORCH_HOME": str(cache/"torch"),
           "NLTK_DATA": str(cache/"nltk"), "XDG_CACHE_HOME": str(cache), "PYTHONUTF8": "1"}
    source = BASE / "source" / folder
    runtime = BASE / "runtimes" / runtime_name
    interpreter = runtime / "Scripts/python.exe"
    uv = os.environ.get("DAFEIYU_UV") or shutil.which("uv")
    if not uv:
        raise FileNotFoundError("Install uv or set DAFEIYU_UV to its executable path")
    source.mkdir(parents=True, exist_ok=True)
    if args.kind == "moss":
        # Only the maintained standalone CPU runtime is needed, not torch demos.
        for name in ("ort_cpu_runtime.py", "LICENSE", "README.md"):
            download(f"https://raw.githubusercontent.com/{repo}/{revision}/{name}", source/name)
    else:
        archive = cache / f"index-tts-{revision}.tar.gz"
        download(f"https://codeload.github.com/{repo}/tar.gz/{revision}", archive)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts[1:]
                if not parts:
                    continue
                target = source.joinpath(*parts).resolve()
                if not target.is_relative_to(source.resolve()) or member.issym() or member.islnk():
                    raise ValueError("Unsafe upstream archive")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as data, target.open("wb") as out:
                        import shutil
                        shutil.copyfileobj(data, out)
    (source/"dafeiyu-source.json").write_text(json.dumps({"repo": repo, "revision": revision}), encoding="utf-8")
    if not args.skip_runtime:
        if not interpreter.exists():
            python = "3.11" if args.kind == "index" else "3.12"
            subprocess.run([str(uv), "venv", str(runtime), "--python", python], env=env, check=True)
        if args.kind == "index":
            # Match upstream's explicit CUDA 12.8 source rather than accidentally
            # installing a CPU-only PyTorch distribution from the general index.
            wheel = cache / "wheels/torch-2.8.0+cu128-cp311-cp311-win_amd64.whl"
            download("https://download.pytorch.org/whl/cu128/torch-2.8.0%2Bcu128-cp311-cp311-win_amd64.whl", wheel,
                     "34c55443aafd31046a7963b63d30bc3b628ee4a704f826796c865fdfd05bb596", 3461420395)
            subprocess.run([str(uv), "pip", "install", "--python", str(interpreter), "--link-mode", "copy",
                            "--index-url", "https://download.pytorch.org/whl/cu128", str(wheel), "torchaudio==2.8.0"], env=env, check=True)
        package_args = ["-r", str(ROOT/"requirements-tts-moss.txt")] if args.kind == "moss" else ["-e", str(source), "fastapi>=0.115,<1", "uvicorn>=0.34,<1", "soxr>=0.5,<2"]
        subprocess.run([str(uv), "pip", "install", "--python", str(interpreter), "--link-mode", "copy",
                        "--index-url", args.index_url, *package_args], env=env, check=True)
        if args.kind == "index":
            # g2p_en imports otherwise attempt implicit network downloads during
            # first inference. Prepare both legacy and current NLTK tagger data
            # explicitly, with all files kept on the data drive.
            language_setup = (
                "import os,nltk; "
                "[nltk.download(name,download_dir=os.environ['NLTK_DATA'],raise_on_error=True) "
                "for name in ('cmudict','averaged_perceptron_tagger','averaged_perceptron_tagger_eng')]; "
                "from wetext import Normalizer; "
                "Normalizer(lang='zh',operator='tn',remove_erhua=False).normalize('123'); "
                "Normalizer(lang='en',operator='tn').normalize('123')"
            )
            subprocess.run([str(interpreter), "-c", language_setup], env=env, check=True)
        frozen = subprocess.check_output([str(uv), "pip", "freeze", "--python", str(interpreter)], env=env, text=True)
        (runtime/"dafeiyu-requirements.lock.txt").write_text(frozen, encoding="utf-8")
    if not args.skip_models:
        model = user_models_dir(ROOT) / folder
        if args.kind == "moss":
            modelscope_snapshot("OpenMOSS/MOSS-TTS-Nano-100M-ONNX", model/"MOSS-TTS-Nano-100M-ONNX")
            modelscope_snapshot("OpenMOSS/MOSS-Audio-Tokenizer-Nano-ONNX", model/"MOSS-Audio-Tokenizer-Nano-ONNX")
        else:
            modelscope_snapshot("IndexTeam/IndexTTS-2.5", model, {
                "LICENSE", "README.md", "config.yaml", "configuration.json", "codec.pth", "gpt.pth", "s2mel.pth",
                "feat1.pt", "feat2.pt", "wav2vec2bert_stats.pt", "multilingual_zh_ja_yue_char_del.tiktoken"})
            cache_dir = model / "hf_cache"
            modelscope_snapshot("AI-ModelScope/w2v-bert-2.0", cache_dir/"w2v-bert-2.0",
                                {"config.json", "preprocessor_config.json", "model.safetensors"})
            modelscope_snapshot("iic/speech_campplus_sv_zh-cn_16k-common", cache_dir,
                                {"campplus_cn_common.bin"})
            huggingface_mirror_files("nvidia/bigvgan_v2_22khz_80band_256x", cache_dir/"bigvgan",
                                     {"config.json", "bigvgan_generator.pt"})

    print(f"Prepared {args.kind}: {runtime}. Models require a real synthesis check before ready.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
