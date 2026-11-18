"""Supervise local services. Ctrl+C shuts down only our children."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import time
import threading
from urllib.error import URLError
from urllib.request import Request, urlopen
import webbrowser
import uuid
from dotenv import dotenv_values
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dafeiyu_paths import data_dir, models_dir, runtime_dir as user_runtime_dir, home_dir, environment_dir
from voice_services import VoiceServiceManager, saved_voice_settings, desired_voice_services


def healthy(port: int, path: str) -> bool:
    try:
        headers = {}
        if port == int(os.environ.get("DAFEIYU_GATEWAY_PORT", "8765")) and os.environ.get("DAFEIYU_HARNESS") == "dsh":
            headers["X-Dafeiyu-Plugin-Token"] = os.environ.get("DAFEIYU_PLUGIN_TOKEN", "")
        with urlopen(Request(f"http://127.0.0.1:{port}{path}", headers=headers), timeout=1) as response:
            return response.status == 200
    except (URLError, TimeoutError, OSError):
        return False


def using_local_llm() -> bool:
    values = {**dotenv_values(home_dir(ROOT) / ".env"), **os.environ}
    address = values.get("LLM_BASE_URL", "http://127.0.0.1:8767/v1")
    database = data_dir(ROOT) / "companion.sqlite3"
    if database.exists():
        try:
            with sqlite3.connect(database, timeout=1) as connection:
                row = connection.execute("SELECT value FROM settings WHERE key='llm_base_url'").fetchone()
                if row:
                    address = json.loads(row[0])
        except (sqlite3.Error, ValueError):
            pass
    return str(address).rstrip("/") in {"http://127.0.0.1:8767/v1", "http://localhost:8767/v1"}


def start_owned_process(command, *, cwd, env, log):
    if os.name == "nt":
        from windows_process import start_native_process
        # CreateProcess needs an executable for batch entry points such as npm.
        if Path(command[0]).suffix.lower() in {".cmd", ".bat"}:
            command = [env.get("COMSPEC", "C:/Windows/System32/cmd.exe"),
                       "/d", "/s", "/c", subprocess.list2cmdline(command)]
        return start_native_process(command, cwd=cwd, env=env, log=log)
    return subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT), None


def close_owned_processes(processes, jobs):
    # The venv launcher may have exited while its interpreter is still alive.
    # Closing every owned job is required even when its launcher's poll() is set.
    try:
        for job in reversed(jobs):
            try:
                job.Close()
            except OSError:
                print("Could not close a service process job.", file=sys.stderr)
    finally:
        # Job termination is asynchronous. Waiting before another TerminateProcess
        # avoids racing an already-terminating Windows launcher (access denied).
        if not jobs:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
        for proc in reversed(processes):
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=8)



def main() -> int:
    parser = argparse.ArgumentParser(description="大飞鱼 · 本地数字人助手")
    parser.add_argument("--open", action="store_true", help="Open the application in your default browser")
    parser.add_argument("--dev", action="store_true", help="Also run the Vite frontend development server")
    parser.add_argument("--no-speech", action="store_true", help="Use an already configured external speech service")
    parser.add_argument("--local-llm", action="store_true", help="Run the optional downloaded OpenVINO language model on port 8767")
    parser.add_argument("--no-local-llm", action="store_true", help="Do not automatically launch the downloaded local language model")
    parser.add_argument("--index-tts", action="store_true", help="Start the IndexTTS-2.5 GPU sidecar when GPU policy is selected")
    parser.add_argument("--no-optional-voice", action="store_true", help="Use externally managed optional voice services")
    parser.add_argument("--stop", action="store_true", help="Ask the project supervisor to stop its own services")
    parser.add_argument("--runtime-name", choices=("standalone", "dsh"), default="standalone", help="Isolate plugin supervisor ownership")
    parser.add_argument("--parent-stdin", action="store_true", help="Stop owned services when the plugin host closes stdin")
    parser.add_argument("--gateway-port", type=int, default=int(os.environ.get("DAFEIYU_GATEWAY_PORT", "8765")))
    parser.add_argument("--speech-port", type=int, default=int(os.environ.get("DAFEIYU_SPEECH_PORT", "8766")))
    args = parser.parse_args()
    gateway_port, speech_port = args.gateway_port, args.speech_port
    if not all(1024 <= port <= 65535 for port in (gateway_port, speech_port)) or gateway_port == speech_port:
        parser.error("Gateway and speech ports must be distinct numbers between 1024 and 65535")
    os.environ["DAFEIYU_GATEWAY_PORT"] = str(gateway_port)
    os.environ["DAFEIYU_SPEECH_PORT"] = str(speech_port)
    runtime_dir = user_runtime_dir(ROOT)
    runner_file = runtime_dir / ("runner-dsh.json" if args.runtime_name == "dsh" else "runner.json")
    if args.stop:
        if not runner_file.exists():
            print("No project supervisor is running.")
            return 0
        token = json.loads(runner_file.read_text(encoding="utf-8"))["token"]
        (runtime_dir / f"stop-{token}").touch()
        print("Stop requested. The supervisor will shut down its own services.")
        return 0
    if runner_file.exists() and healthy(gateway_port, "/api/health"):
        address = "http://127.0.0.1:5173" if args.dev else f"http://127.0.0.1:{gateway_port}"
        print(f"The project is already running: {address}")
        if args.open:
            webbrowser.open(address)
        return 0
    if not args.dev and args.runtime_name != "dsh" and not (ROOT / "web/dist/index.html").exists():
        print("Missing frontend build. Run .\\setup.ps1 first.", file=sys.stderr)
        return 1
    voice_python = environment_dir(".venv-voice", ROOT) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not voice_python.is_file():
        print("Missing Pipecat voice environment. Run setup.ps1 to install requirements-voice-lock.txt.", file=sys.stderr)
        return 1
    specs = [(gateway_port, "/api/health", [str(voice_python), "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)])]
    if not args.no_speech:
        specs.insert(0, (speech_port, "/health", [sys.executable, "-m", "uvicorn", "speech.server:app", "--host", "127.0.0.1", "--port", str(speech_port)]))
    if os.environ.get("DAFEIYU_HARNESS") != "dsh" and (args.local_llm or (not args.no_local_llm and using_local_llm() and (ROOT / "models/qwen3-1.7b-int4/openvino_model.xml").is_file())):
        specs.insert(0, (8767, "/health", [sys.executable, "-m", "uvicorn", "inference.app:app", "--host", "127.0.0.1", "--port", "8767"]))
    processes = []  # Popen on POSIX, contained NativeProcess on Windows.
    jobs = []
    log_handles = []
    logs = data_dir(ROOT) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = {**{key: value for key, value in dotenv_values(home_dir(ROOT) / ".env").items() if value is not None},
           **os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
    # HTTPX reads Windows system proxies but not the registry's bypass list.
    # Keep local ASR/LLM/TTS direct without disabling proxies for cloud models.
    bypass = ",".join(filter(None, (env.get("NO_PROXY", ""), env.get("no_proxy", ""), "127.0.0.1,localhost,::1")))
    env["NO_PROXY"] = env["no_proxy"] = bypass
    env.setdefault("SPEECH_BASE_URL", f"http://127.0.0.1:{speech_port}")
    online_model = models_dir(ROOT, env) / "streaming-zipformer-zh-en"
    online_files = ("tokens.txt", "encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.onnx", "joiner-epoch-99-avg-1.int8.onnx")
    # Model availability enables the local capability, not early interruption.
    # The explicit per-user streaming_asr_preview setting remains off by default.
    if all((online_model / name).is_file() for name in online_files):
        env.setdefault("DAFEIYU_STREAM_ASR", "1")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    manager = VoiceServiceManager(ROOT, healthy)
    forced = {"index_tts"} if args.index_tts else set()
    base_env = env.copy()
    settings = saved_voice_settings(ROOT, env)
    mode, kinds = desired_voice_services(settings, env, external=args.no_optional_voice, forced=forced)
    print(f"Voice policy: {mode}; saved mode takes precedence over launch defaults.", flush=True)
    stop_file = runtime_dir / f"stop-{token}"
    runner_file.write_text(json.dumps({"pid": os.getpid(), "token": token}), encoding="utf-8")
    parent_gone = threading.Event()
    if args.parent_stdin:
        def watch_parent():
            try:
                # Raw OS reads do not hold a Python buffered-IO lock while a
                # daemon waits at interpreter shutdown (Windows pipe lifetime).
                while os.read(sys.stdin.fileno(), 1):
                    pass
            finally:
                parent_gone.set()
        threading.Thread(target=watch_parent, daemon=True, name="plugin-parent-lifetime").start()
    # Model weights and secrets never leave the project because of an unexpected cwd.
    try:
        manager.sync(env, kinds)
        for port, path, command in specs:
            if healthy(port, path):
                print(f"Reusing existing service on 127.0.0.1:{port}")
                continue
            log = (logs / f"{port}.log").open("a", encoding="utf-8")
            log_handles.append(log)
            # Only this supervisor owns the plugin-host liveness pipe. Service
            # launchers must not inherit a handle another thread is blocking on.
            proc, job = start_owned_process(command, cwd=ROOT, env=env, log=log)
            processes.append(proc)
            if job is not None:
                jobs.append(job)
        if args.dev:
            log = (logs / "5173.log").open("a", encoding="utf-8")
            log_handles.append(log)
            proc, job = start_owned_process(["npm.cmd" if os.name == "nt" else "npm", "run", "dev", "--", "--host", "127.0.0.1"],
                                            cwd=ROOT / "web", env=env, log=log)
            processes.append(proc)
            if job is not None:
                jobs.append(job)
        deadline = time.monotonic() + 90
        while not healthy(gateway_port, "/api/health"):
            if parent_gone.is_set() or stop_file.exists():
                return 0
            failed = next((p for p in processes if p.poll() is not None), None)
            if failed is not None or time.monotonic() > deadline:
                print(f"Service did not start. Inspect {logs}", file=sys.stderr)
                return 1
            time.sleep(0.25)
        address = "http://127.0.0.1:5173" if args.dev else f"http://127.0.0.1:{gateway_port}"
        print(f"\n大飞鱼 is running: {address}\nLogs: {logs}\nPress Ctrl+C to stop.\n", flush=True)
        if args.open:
            webbrowser.open(address)
        while True:
            if stop_file.exists() or parent_gone.is_set():
                return 0
            for proc in processes:
                if proc.poll() is not None:
                    print(f"A service exited ({proc.returncode}). Inspect {logs}", file=sys.stderr)
                    return 1
            try:
                settings = saved_voice_settings(ROOT, base_env)
                updated_env = base_env.copy()
                _, kinds = desired_voice_services(settings, updated_env, external=args.no_optional_voice, forced=forced)
                manager.sync(updated_env, kinds)
            except (sqlite3.Error, ValueError, OSError):
                # Keep the last valid deployment during a transient settings read failure.
                pass
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            try:
                manager.close()
            finally:
                close_owned_processes(processes, jobs)
        finally:
            for handle in log_handles:
                handle.close()
            stop_file.unlink(missing_ok=True)
            try:
                if json.loads(runner_file.read_text(encoding="utf-8")).get("token") == token:
                    runner_file.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
