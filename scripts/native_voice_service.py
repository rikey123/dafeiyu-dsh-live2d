"""Run native Windows speech sidecars and dispose their inference workers."""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import sys
import threading

# Avoid slow first-run bytecode writes on removable/exFAT project volumes.
sys.dont_write_bytecode = True


def prepare_torch() -> None:
    """Load PyTorch DLLs in a deterministic order on Windows.

    PyTorch 2.7 enumerates its DLLs in filesystem order. On this exFAT volume,
    loading torch_cpu before the CUDA dependencies hangs inside LoadLibraryExW.
    Sort only that enumeration, then restore glob before serving any requests.
    Spawned inference workers need the same bootstrap.
    """
    original = glob.glob

    def ordered(pattern, *args, **kwargs):
        matches = original(pattern, *args, **kwargs)
        return sorted(matches) if str(pattern).replace("\\", "/").endswith("torch/lib/*.dll") else matches

    glob.glob = ordered
    try:
        import torch  # noqa: F401
    finally:
        glob.glob = original


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--kind", choices=("cosyvoice", "index_tts", "moss_tts"), default="cosyvoice")
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    sys.path.insert(0, str(project))
    from dafeiyu_paths import runtime_dir
    config_path = args.config.resolve(strict=True)
    stop_path = args.stop_file.resolve()
    directory = runtime_dir(project)
    if not config_path.is_relative_to(directory) or not stop_path.is_relative_to(directory):
        raise ValueError("Lifecycle files must belong to this project's .runtime")
    config = json.loads(config_path.read_text(encoding="utf-8"))[args.kind]
    os.environ.update(config["env"])
    sys.path.insert(0, str(project))
    if args.kind == "cosyvoice":
        prepare_torch()
    import uvicorn
    if args.kind == "cosyvoice":
        from server.cosyvoice_sidecar import app
    else:
        from server.model_tts_sidecar import create_app
        app = create_app(os.environ.get("DAFEIYU_MODEL_SERVICE", args.kind))

    port = {"moss_tts": 8772}.get(args.kind, 8770)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, timeout_graceful_shutdown=3))
    finished = threading.Event()

    def watch():
        while not finished.wait(.25):
            if stop_path.exists() or not config_path.exists():
                server.should_exit = True
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        server.run()
    finally:
        finished.set()
        watcher.join(timeout=1)
    return 0


if __name__ == "__mp_main__" and os.getenv("DAFEIYU_MODEL_SERVICE") != "moss_tts":
    prepare_torch()


if __name__ == "__main__":
    raise SystemExit(main())
