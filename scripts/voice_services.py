"""Reconcile optional local services with saved TTS policy.

Only supervisor-owned processes are stopped. Separate lifecycle files per service
avoid interrupting unrelated models when the GPU route changes. Explicit GPU mode
preloads and warms its model on service startup; auto/CPU stay demand-driven.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid
from urllib.request import urlopen

from optional_voice import optional_specs
from voice_mode import configure_voice_mode
from dafeiyu_paths import data_dir

KEYS = ("gpu_tts_model", "conversation_mode", "tts_mode", "tts_engine", "cosyvoice_url", "index_tts_url", "moss_tts_url")


def saved_voice_settings(root, env):
    directory = data_dir(root, env)
    database = (root / directory).resolve() / "companion.sqlite3"
    if not database.is_file():
        return {}
    # A read-only connection must never create a second configuration database.
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1) as connection:
        return {key: json.loads(value) for key, value in connection.execute(
            "SELECT key,value FROM settings WHERE key IN (" + ",".join("?" for _ in KEYS) + ")", KEYS)}


def desired_voice_services(settings, env, *, external=False, forced=()):
    if settings.get("conversation_mode") == "moss_live":
        return "moss_live", set()
    kinds = set(forced) - {"mfa"}  # Retired alignment cannot be re-enabled by legacy callers.
    mode = configure_voice_mode(env, kinds, settings=settings, external=external)
    if external:
        return mode, set()
    if mode in {"cpu", "api"}:
        kinds.discard("cosyvoice")
    return mode, kinds


class VoiceServiceManager:
    def __init__(self, root, healthy):
        self.root = root
        self.healthy = healthy
        self.services = {}
        self.jobs = {}
        self.fingerprints = {}
        self.failed_until = {}

    def compatible(self, kind, port, env=None):
        if kind not in {"index_tts", "moss_tts"}:
            return True
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                health = json.loads(response.read(65536))
            expected = "IndexTTS-2.5" if kind == "index_tts" else "MOSS-TTS-Nano"
            if kind == "index_tts" and (env or {}).get("DAFEIYU_GPU_TTS_MODEL") == "gpt_sovits":
                expected = "GPT-SoVITS-v5-turbo"
            if health.get("model_name") != expected:
                return False
            if kind == "index_tts" and "DAFEIYU_GPU_PRELOAD" in (env or {}):
                return health.get("preload") is (env["DAFEIYU_GPU_PRELOAD"] == "1")
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def sync(self, env, kinds):
        fingerprints = {kind: tuple(sorted((key, value) for key, value in env.items()
                        if key.startswith({"cosyvoice": "DAFEIYU_COSY_", "index_tts": ("DAFEIYU_INDEX_", "DAFEIYU_GSV_", "DAFEIYU_GPU_"), "moss_tts": "DAFEIYU_MOSS_"}[kind]) or key == "DAFEIYU_VOICE_WSL_DISTRO"))
                        for kind in kinds}
        for kind in list(self.services):
            if kind not in kinds or self.fingerprints.get(kind) != fingerprints[kind]:
                self._stop(kind)
        for kind in sorted(kinds):
            if kind in self.services:
                proc = self.services[kind][0]
                if proc is None:
                    port = {"cosyvoice": 8770, "index_tts": 8770, "moss_tts": 8772}[kind]
                    if self.healthy(port, "/health") and self.compatible(kind, port, env):
                        continue
                    self._stop(kind)
                elif proc.poll() is None:
                    continue
                else:
                    self._stop(kind)
                    self.failed_until[kind] = time.monotonic() + 30
                    print(f"Optional {kind} exited; retrying in 30 seconds. Inspect data/logs.", flush=True)
            if time.monotonic() < self.failed_until.get(kind, 0):
                continue
            port = {"cosyvoice": 8770, "index_tts": 8770, "moss_tts": 8772}[kind]
            if self.healthy(port, "/health"):
                if not self.compatible(kind, port, env):
                    self.failed_until[kind] = time.monotonic() + 30
                    print(f"Optional {kind} blocked: loopback:{port} belongs to a different service. Its process is left running.", flush=True)
                    continue
                # Borrowed services have no lifecycle files and are never terminated.
                self.services[kind] = (None, None, None, None)
                self.fingerprints[kind] = fingerprints[kind]
                continue
            try:
                specs, config, stop = optional_specs(self.root, env, uuid.uuid4().hex, [kind])
                logs = data_dir(self.root, env) / "logs"
                logs.mkdir(parents=True, exist_ok=True)
                handle = (logs / f"{port}.log").open("a", encoding="utf-8")
                try:
                    child_env = {key: value for key, value in env.items()
                                 if not any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
                    command = specs[0][2]
                    if os.name == "nt" and len(command) > 1 and Path(command[1]).name == "native_voice_service.py":
                        try:
                            from windows_process import start_native_process
                            proc, self.jobs[kind] = start_native_process(command, cwd=self.root, env=child_env, log=handle)
                        except ImportError:
                            raise OSError("Native service requires pywin32 process containment") from None
                    else:
                        proc = subprocess.Popen(command, cwd=self.root, env=child_env,
                                                stdout=handle, stderr=subprocess.STDOUT,
                                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                except Exception:
                    handle.close()
                    config.unlink(missing_ok=True)
                    raise
                self.services[kind] = (proc, config, stop, handle)
                self.fingerprints[kind] = fingerprints[kind]
                lifecycle = "preloading and warming model" if kind == "index_tts" and env.get("DAFEIYU_GPU_PRELOAD", "1") == "1" else "model loads on demand"
                print(f"Optional {kind} starting on loopback:{port} ({lifecycle}).", flush=True)
            except (OSError, ValueError):
                self.failed_until[kind] = time.monotonic() + 30
                print(f"Optional {kind} could not start; check runtime configuration. Retrying in 30 seconds.", flush=True)

    def _stop(self, kind):
        proc, config, stop, handle = self.services.pop(kind)
        self.fingerprints.pop(kind, None)
        if proc is not None:
            try:
                stop.touch()
                try:
                    proc.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
            finally:
                job = self.jobs.pop(kind, None)
                if job is not None:
                    job.Close()
                handle.close()
                config.unlink(missing_ok=True)
                stop.unlink(missing_ok=True)
            print(f"Optional {kind} stopped; its model worker has been released.", flush=True)

    def close(self):
        for kind in list(self.services):
            self._stop(kind)
