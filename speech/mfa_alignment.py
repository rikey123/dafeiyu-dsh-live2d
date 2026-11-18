"""Offline MFA word and phone alignment in an isolated native or Linux runtime."""

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

from dafeiyu_paths import cache_dir

from .forced_alignment import read_audio


def intervals(entries, duration, unit):
    result = []
    last = 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("invalid audio duration")
    for item in entries:
        if not item.label or not math.isfinite(item.start) or not math.isfinite(item.end) or item.start < last or not 0 <= item.start <= item.end <= duration + 0.02:
            raise ValueError(f"invalid {unit} interval")
        end = min(item.end, duration)
        if item.start >= end:
            raise ValueError(f"invalid {unit} interval")
        result.append({"text": item.label, "start_s": item.start, "end_s": end, "unit": unit})
        last = end
    if not result:
        raise ValueError(f"MFA returned empty {unit} tier")
    return result


def model_cache_key(dictionary, acoustic_model):
    """Never reuse a lexicon compiled against different phones/models/versions."""
    h = hashlib.sha256(version("montreal-forced-aligner").encode("utf-8"))
    for path in (dictionary, acoustic_model):
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                h.update(block)
    return h.hexdigest()


def align(wav_path, text, dictionary, acoustic_model, output_grid=None, timeout=300):
    if not text.strip() or len(text) > 1000:
        raise ValueError("text must contain 1 to 1000 characters")
    audio_path = Path(wav_path).resolve(strict=True)
    _, duration = read_audio(audio_path)
    dictionary = Path(dictionary).resolve(strict=True)
    acoustic_model = Path(acoustic_model).resolve(strict=True)
    from praatio import textgrid
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="dafeiyu-mfa-") as temporary:
        root = Path(temporary)
        corpus = root / "corpus"
        output = root / "output"
        corpus.mkdir()
        shutil.copyfile(audio_path, corpus / "input.wav")
        (corpus / "input.lab").write_text(text.strip(), encoding="utf-8")
        grid_path = output / "input.TextGrid"
        work = root / "work"
        env = dict(os.environ, MFA_ROOT_DIR=str(work))
        single_file = os.environ.get("DAFEIYU_MFA_SINGLE_FILE") == "1"
        cache = None
        if single_file:
            # Use MFA's maintained single-utterance path instead of constructing
            # a corpus/SQLite database and adapting a speaker for every sentence.
            # Each request owns a private workspace. Publish only successful
            # compiled-model artifacts, so cancelled jobs cannot poison reuse.
            cache_root = Path(os.environ.get("DAFEIYU_MFA_CACHE", str(cache_dir() / "mfa"))) / "compiled"
            cache_root.mkdir(parents=True, exist_ok=True)
            cache = cache_root / model_cache_key(dictionary, acoustic_model)
            if cache.is_dir():
                shutil.copytree(cache, work)
            command = ["mfa", "align_one", str(corpus / "input.wav"), str(corpus / "input.lab"),
                       str(dictionary), str(acoustic_model), str(grid_path), "--num_jobs", "1", "--no_use_mp"]
        else:
            command = ["mfa", "align", str(corpus), str(dictionary), str(acoustic_model), str(output),
                       "--single_speaker", "--num_jobs", "1", "--no_use_mp"]
        subprocess.run(command, env=env, check=True, timeout=timeout, stdout=subprocess.DEVNULL)
        grid = textgrid.openTextgrid(str(grid_path), includeEmptyIntervals=False)
        tiers = {}
        for name in ("words", "phones"):
            tiers[name] = intervals(grid.getTier(name).entries, duration, "phoneme" if name == "phones" else "word")
        if cache is not None and not cache.exists():
            # Copy only compiled upstream models, never transcripts or audio.
            extracted = work / "extracted_models"
            if extracted.is_dir():
                staging = root / "publish"
                shutil.copytree(extracted, staging / "extracted_models")
                try:
                    staging.rename(cache)
                except FileExistsError:
                    pass  # Another independent CLI request published first.
        if output_grid is not None:
            output_grid = Path(output_grid)
            if output_grid.exists():
                raise FileExistsError(f"output already exists: {output_grid}")
            shutil.copyfile(grid_path, output_grid)
    return {"engine": "Montreal Forced Aligner", "method": "align_one" if single_file else "corpus", "device": "CPU", "audio_sha256": hashlib.sha256(audio_path.read_bytes()).hexdigest(), "sample_rate": 16000, "audio_duration_s": duration, "elapsed_s": time.perf_counter() - start, "words": tiers["words"], "phones": tiers["phones"]}


def main():
    parser = argparse.ArgumentParser(description="Offline Mandarin word and phone alignment")
    parser.add_argument("wav")
    parser.add_argument("text")
    parser.add_argument("--dictionary", required=True)
    parser.add_argument("--acoustic-model", required=True)
    parser.add_argument("--textgrid")
    parser.add_argument("--output-json", type=Path, help="Machine result separated from dependency diagnostics")
    args = parser.parse_args()
    result = json.dumps(align(args.wav, args.text, args.dictionary, args.acoustic_model, args.textgrid), ensure_ascii=False)
    if args.output_json:
        args.output_json.write_text(result, encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
