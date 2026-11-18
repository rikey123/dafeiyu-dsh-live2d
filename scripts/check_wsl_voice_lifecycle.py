"""Linux integration check: stopping the wrapper must also stop descendants."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def main():
    wrapper = Path(__file__).with_name("wsl_voice_service.py").resolve()
    with tempfile.TemporaryDirectory(prefix="dafeiyu-lifecycle-") as temp:
        root = Path(temp)
        runtime = root / "fake-runtime"
        (runtime / "bin").mkdir(parents=True)
        state = root / ".runtime"
        state.mkdir()
        executable = runtime / "bin/python"
        executable.write_text("#!/usr/bin/python3\nimport os,subprocess,time,json\nfrom pathlib import Path\np=subprocess.Popen(['sleep','300'],start_new_session=True)\nPath(os.environ['PID_OUTPUT']).write_text(json.dumps([os.getpid(),p.pid]))\ntime.sleep(300)\n")
        executable.chmod(0o755)
        pids_path = root / "pids.json"
        config = state / "test.json"
        config.write_text(json.dumps({"cosyvoice": {"runtime": str(runtime), "env": {"PID_OUTPUT": str(pids_path)}}}))
        stop_file = state / "stop"
        process = subprocess.Popen([sys.executable, str(wrapper), "--project", str(root), "--config", str(config),
                                    "--stop-file", str(stop_file), "--kind", "cosyvoice"])
        try:
            deadline = time.monotonic() + 10
            while not pids_path.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("wrapper exited before starting child")
                time.sleep(.05)
            pids = json.loads(pids_path.read_text())
            assert all(alive(pid) for pid in pids), "children did not start"
            stop_file.touch()
            assert process.wait(timeout=12) == 0
            assert not any(alive(pid) for pid in pids), "model descendant survived shutdown"
            print(json.dumps({"passed": True, "model_and_descendant_reaped": True, "physical_microphone": False}))
        finally:
            if pids_path.exists():
                for pid in json.loads(pids_path.read_text()):
                    if alive(pid):
                        os.kill(pid, 9)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=12)


if __name__ == "__main__":
    main()
