"""Supervisor lifecycle fixtures: real Windows venv launchers, no services/models."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest


WORKTREE = Path(__file__).resolve().parents[1]
PROJECT = next((root for root in (WORKTREE, *WORKTREE.parents)
                if (root / '.venv').is_dir() and (root / '.venv-voice').is_dir()), WORKTREE)
SCRIPTS = WORKTREE / "scripts"


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("dsh_supervisor_fixture", SCRIPTS / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_posix_keeps_popen_with_null_stdin(runner, monkeypatch):
    calls = []
    process = object()
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="posix"))
    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return process
    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    log = object()
    assert runner.start_owned_process(["python", "service.py"], cwd="/fixture", env={}, log=log) == (process, None)
    assert calls == [(["python", "service.py"], {"cwd": "/fixture", "env": {},
                     "stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT})]


def test_windows_uses_native_containment_for_exe_and_batch(runner, monkeypatch):
    calls = []
    def start(command, **kwargs):
        calls.append((command, kwargs))
        return "process", "job"
    monkeypatch.setattr(runner, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "windows_process", SimpleNamespace(start_native_process=start))
    assert runner.start_owned_process(["G:/runtime/python.exe", "service.py"], cwd="G:/fixture", env={}, log=None) == ("process", "job")
    assert calls[0][0] == ["G:/runtime/python.exe", "service.py"]
    runner.start_owned_process(["npm.cmd", "run", "dev"], cwd="G:/fixture", env={"COMSPEC": "E:/Windows/cmd.exe"}, log=None)
    assert calls[1][0] == ["E:/Windows/cmd.exe", "/d", "/s", "/c", "npm.cmd run dev"]


def test_close_jobs_even_after_launcher_exit_and_reap_killed_process(runner):
    events = []
    class Process:
        def __init__(self, name, exited=False): self.name, self.exited, self.waits = name, exited, 0
        def poll(self): return 0 if self.exited else None
        def terminate(self): events.append((self.name, "terminate"))
        def kill(self): events.append((self.name, "kill"))
        def wait(self, timeout):
            self.waits += 1
            if self.name == "stubborn" and self.waits == 1:
                raise subprocess.TimeoutExpired(self.name, timeout)
            events.append((self.name, "wait"))
    class Job:
        def __init__(self, name): self.name = name
        def Close(self): events.append((self.name, "close"))
    runner.close_owned_processes([Process("exited", True), Process("stubborn")], [Job("exited"), Job("stubborn")])
    assert events[:2] == [("stubborn", "close"), ("exited", "close")]
    assert ("exited", "terminate") not in events
    assert ("stubborn", "kill") in events and ("stubborn", "wait") in events


SERVICE = r'''
import json
import os
from pathlib import Path
import subprocess
import sys
import time

port = sys.argv[sys.argv.index("--port") + 1]
root = Path.cwd()
eof = sys.stdin.buffer.read(1) == b""
child_code = "import json,os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'eof':sys.stdin.buffer.read(1)==b''})); time.sleep(120)"
child = subprocess.Popen([sys.executable, "-B", "-c", child_code, str(root / (port + ".child"))])
(root / (port + ".ready")).write_text(json.dumps({"pid": os.getpid(), "grandchild": child.pid, "eof": eof}))
time.sleep(120)
'''


BOOTSTRAP = r'''
import json
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
import run

root = Path(sys.argv[2])
mode = sys.argv[3]
run.ROOT = root
run.dotenv_values = lambda *args: {}  # Never load any installation's .env.
run.saved_voice_settings = lambda *args: {}
run.desired_voice_services = lambda *args, **kwargs: ("fixture", set())

class Manager:
    def __init__(self, *args): pass
    def sync(self, *args): pass
    def close(self):
        (root / "manager-closed").touch()
        if mode == "manager_failure":
            raise RuntimeError("synthetic manager close failure")

run.VoiceServiceManager = Manager
def healthy(port, path):
    if mode == "startup_eof" and port == 8765:
        return False
    return (root / (str(port) + ".ready")).exists()
run.healthy = healthy
original_start = run.start_owned_process
def start(command, **kwargs):
    proc, job = original_start(command, **kwargs)
    port = command[command.index("--port") + 1]
    (root / (port + ".launcher")).write_text(str(proc.pid))
    return proc, job
run.start_owned_process = start
sys.argv = ["run.py", "--runtime-name", "dsh", "--parent-stdin", "--no-local-llm", "--no-optional-voice"]
raise SystemExit(run.main())
'''


def wait_for(condition, message, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.025)
    pytest.fail(message)


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended launcher and job containment")
@pytest.mark.parametrize("mode,borrowed", [
    ("stop", False), ("eof", False), ("startup_eof", False),
    ("launcher_exit", False), ("eof", True), ("manager_failure", False),
    ("supervisor_kill", False), ("supervisor_kill", True),
])
def test_windows_supervisor_reaps_real_launcher_interpreter_and_grandchild(mode, borrowed):
    import _winapi

    # The supervisor runs in the existing speech environment with pywin32. The
    # pytest driver remains the required .venv-voice interpreter.
    supervisor_python = PROJECT / ".venv/Scripts/python.exe"
    voice_python = PROJECT / ".venv-voice/Scripts/python.exe"
    assert supervisor_python.is_file() and voice_python.is_file()
    temporary_root = WORKTREE / ".runtime/dsh-supervisor-tests"
    temporary_root.mkdir(parents=True, exist_ok=True)
    handles = []
    supervisor = external = None
    def open_process(pid):
        handle = _winapi.OpenProcess(0x100000 | 0x0001, False, pid)
        handles.append(handle)
        return handle
    def alive(handle): return _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_TIMEOUT

    with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
        root = Path(directory)
        assert root.resolve().is_relative_to(temporary_root.resolve())
        launcher = root / ".venv-voice/Scripts/python.exe"
        launcher.parent.mkdir(parents=True)
        shutil.copyfile(voice_python, launcher)
        (launcher.parent.parent / "pyvenv.cfg").write_text(
            "home = " + str(Path(sys._base_executable).parent) + "\ninclude-system-site-packages = false\n", encoding="utf-8")
        (root / "uvicorn.py").write_text(SERVICE, encoding="utf-8")
        bootstrap = root / "bootstrap.py"
        bootstrap.write_text(BOOTSTRAP, encoding="utf-8")
        # Only OS/runtime paths are copied. No environment credentials, dotenv,
        # user databases, model configuration or C-drive cache are used.
        env = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "COMSPEC", "PATH", "PATHEXT") if name in os.environ}
        env.update(TEMP=str(root), TMP=str(root), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", DAFEIYU_HARNESS="dsh")
        owned, borrowed_handles = [], []
        try:
            if borrowed:
                external = subprocess.Popen([sys._base_executable, "-B", "-m", "uvicorn", "--port", "8766"],
                    cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                wait_for(lambda: (root / "8766.ready").exists() and (root / "8766.child").exists(), "borrowed fixture did not start")
                borrowed_rows = json.loads((root / "8766.ready").read_text())
                borrowed_child = json.loads((root / "8766.child").read_text())
                borrowed_handles = [open_process(borrowed_rows["pid"]), open_process(borrowed_rows["grandchild"]),
                                    open_process(borrowed_child["pid"])]
            with (root / "supervisor.log").open("w", encoding="utf-8") as log:
                supervisor = subprocess.Popen([str(supervisor_python), "-B", str(bootstrap), str(SCRIPTS), str(root), mode],
                    cwd=root, env=env, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
            for port in ([8765] if borrowed else [8766, 8765]):
                wait_for(lambda: all((root / f"{port}.{suffix}").exists() for suffix in ("ready", "child", "launcher")),
                         f"service {port} did not start with null stdin")
                row = json.loads((root / f"{port}.ready").read_text())
                child = json.loads((root / f"{port}.child").read_text())
                assert row["eof"] is True and child["eof"] is True
                launcher_pid = int((root / f"{port}.launcher").read_text())
                if port == 8765:
                    assert launcher_pid != row["pid"], "fixture must exercise the real Windows venv redirector"
                owned.extend([open_process(launcher_pid), open_process(row["pid"]), open_process(row["grandchild"]), open_process(child["pid"])])
            runner_file = root / ".runtime/runner-dsh.json"
            assert runner_file.is_file()
            if mode in {"stop", "manager_failure"}:
                token = json.loads(runner_file.read_text())["token"]
                (root / ".runtime" / f"stop-{token}").touch()
            elif mode == "launcher_exit":
                _winapi.TerminateProcess(owned[-4], 17)
            elif mode == "supervisor_kill":
                # Kill the real interpreter, not its venv redirector. Keep
                # parent stdin open so neither EOF nor Python finally can
                # clean up: only OS job-handle closure can reap descendants.
                supervisor_pid = json.loads(runner_file.read_text())["pid"]
                assert supervisor_pid != supervisor.pid
                assert not supervisor.stdin.closed
                assert all(alive(handle) for handle in owned)
                _winapi.TerminateProcess(open_process(supervisor_pid), 23)
            else:
                supervisor.stdin.close()
            expected = 23 if mode == "supervisor_kill" else (1 if mode in {"launcher_exit", "manager_failure"} else 0)
            assert supervisor.wait(timeout=15) == expected, (root / "supervisor.log").read_text(encoding="utf-8")
            for handle in owned:
                assert _winapi.WaitForSingleObject(handle, 5000) == _winapi.WAIT_OBJECT_0, "owned descendant survived shutdown"
            assert all(alive(handle) for handle in borrowed_handles), "borrowed service was stopped"
            if mode == "supervisor_kill":
                assert not supervisor.stdin.closed
                assert not (root / "manager-closed").exists(), "crash fixture must bypass finally"
                assert runner_file.exists(), "crash fixture must not run lifecycle-file cleanup"
            else:
                assert (root / "manager-closed").exists()
                assert not runner_file.exists()
            assert not list(root.rglob("__pycache__"))
        finally:
            if supervisor is not None:
                if supervisor.stdin and not supervisor.stdin.closed:
                    supervisor.stdin.close()
                try:
                    supervisor.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    supervisor.kill()
                    supervisor.wait(timeout=5)
            for handle in reversed(handles):
                if alive(handle):
                    _winapi.TerminateProcess(handle, 1)
                    _winapi.WaitForSingleObject(handle, 5000)
                _winapi.CloseHandle(handle)
            if external is not None:
                if external.poll() is None:
                    external.terminate()
                external.wait(timeout=5)
