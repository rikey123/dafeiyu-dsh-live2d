"""Real Windows process containment with tiny CPU-only subprocesses."""
import importlib
import os
from pathlib import Path
import sys
import time

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows job API")
def test_closing_native_job_reaps_parent_and_child(monkeypatch, tmp_path):
    win32api = pytest.importorskip("win32api")
    win32event = pytest.importorskip("win32event")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    launcher = importlib.import_module("windows_process")
    child_file = tmp_path / "child-pid.txt"
    code = "import subprocess,sys,time; from pathlib import Path; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
    process, job, child_handle = None, None, None
    try:
        with (tmp_path / "output.log").open("w") as log:
            process, job = launcher.start_native_process([sys.executable, "-u", "-c", code, str(child_file)], cwd=tmp_path, env=os.environ, log=log)
        deadline = time.monotonic() + 5
        while not child_file.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline, "CPU subprocess did not start"
            time.sleep(.02)
        child_handle = win32api.OpenProcess(0x100000, False, int(child_file.read_text()))
        job.Close()
        job = None
        process.wait(timeout=5)
        assert win32event.WaitForSingleObject(child_handle, 5000) == win32event.WAIT_OBJECT_0
    finally:
        if job is not None:
            job.Close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        if child_handle is not None:
            child_handle.Close()
