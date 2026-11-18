"""Read-only, truthful runtime report. Does not install or download anything."""
from __future__ import annotations
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
report: dict = {"python": sys.version, "platform": platform.platform(), "frontend_built": (root / "web/dist/index.html").exists(), "packages": {}, "services": {}}
voice_python = root / '.venv-voice' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
if voice_python.is_file():
    try:
        result = subprocess.run([str(voice_python), '-c', 'import importlib.metadata; print(importlib.metadata.version("pipecat-ai"))'], capture_output=True, text=True, timeout=10)
        report['voice_environment'] = {'path': str(voice_python), 'pipecat': result.stdout.strip(), 'ready': result.returncode == 0}
    except (OSError, subprocess.TimeoutExpired) as exc:
        report['voice_environment'] = {'ready': False, 'detail': str(exc)}
else:
    report['voice_environment'] = {'ready': False, 'detail': 'Run setup.ps1 to install .venv-voice'}
for package in ("fastapi", "httpx", "openvino", "optimum-intel", "faster-whisper", "pywin32"):
    try:
        report["packages"][package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        report["packages"][package] = None
try:
    import openvino as ov
    core = ov.Core()
    report["openvino_devices"] = [{"id": device, "name": core.get_property(device, "FULL_DEVICE_NAME")} for device in core.available_devices]
except Exception as exc:
    report["openvino_error"] = str(exc)
for port, path in ((8765, "/api/status"), (8765, "/api/voice/config"), (8766, "/health")):
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
            report["services"][f'{port}{path}'] = json.load(response)
    except Exception as exc:
        report["services"][f'{port}{path}'] = {"reachable": False, "detail": str(exc)}
print(json.dumps(report, ensure_ascii=False, indent=2))
