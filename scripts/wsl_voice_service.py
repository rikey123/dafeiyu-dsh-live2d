"""Own one optional Linux model service and reap its process group on shutdown.

Invoked by scripts/run.py through WSL; no shell command construction, microphone
access, API keys, or arbitrary client-supplied model paths are involved.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[1]), fields[19]  # ppid, start time; survives spaces in comm
    except (FileNotFoundError, ProcessLookupError):
        return None


def descendants(pid):
    processes = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            identity = process_identity(int(entry.name))
            if identity:
                processes[int(entry.name)] = identity
    owned = {pid}
    while True:
        extra = {child for child, (parent, _started) in processes.items() if parent in owned}
        if extra <= owned:
            return {child: processes[child][1] for child in owned if child in processes}
        owned |= extra


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--kind", choices=("cosyvoice",), required=True)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    if args.home:
        os.environ["DAFEIYU_HOME"] = str(args.home.resolve())
    if args.runtime_dir:
        os.environ["DAFEIYU_RUNTIME_DIR"] = str(args.runtime_dir.resolve())
    sys.path.insert(0, str(project))
    from dafeiyu_paths import runtime_dir as user_runtime_dir
    runtime_dir = user_runtime_dir(project)
    if not config_path.is_relative_to(runtime_dir) or not args.stop_file.resolve().is_relative_to(runtime_dir):
        raise ValueError("Lifecycle files must belong to this project's .runtime")
    config = json.loads(config_path.read_text(encoding="utf-8"))[args.kind]
    runtime = Path(config["runtime"]).expanduser().resolve(strict=True)
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
    env.update(config["env"])
    command = [str(runtime / "bin/python"), "-m", "server.cosyvoice_sidecar"]
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    child = subprocess.Popen(command, cwd=project, env=env, start_new_session=True)
    try:
        while child.poll() is None:
            if stopping or args.stop_file.exists() or not config_path.exists():
                return 0
            time.sleep(.25)
        return child.returncode
    finally:
        # A model may create a private process group for its workers. Keep
        # identities of our descendants too, so such a job cannot survive a
        # forced HTTP-server shutdown. Start times prevent killing reused PIDs.
        owned = descendants(child.pid)
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for pid, started in owned.items():
            current = process_identity(pid)
            if current and current[1] == started:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
