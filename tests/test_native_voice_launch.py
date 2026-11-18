"""Deployment boundary checks for native CUDA and existing WSL launchers."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_spec = importlib.util.spec_from_file_location("optional_voice_launch", Path(__file__).resolve().parents[1] / "scripts/optional_voice.py")
launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launch)


def test_native_paths_and_secret_allowlist(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "os", SimpleNamespace(name="nt"))
    interpreter = tmp_path / "native python.exe"
    interpreter.touch()
    values = {"DAFEIYU_COSY_PYTHON": interpreter.name,
              "DAFEIYU_COSY_MODEL": "G:/models/voice",
              "DAFEIYU_COSY_PROMPT_TEXT": "reference text",
              "LLM_API_KEY": "must-not-be-copied"}
    specs, config_path, stop_path = launch.optional_specs(tmp_path, values, "test", ["cosyvoice"])
    command = specs[0][2]
    assert command[0] == str(interpreter)
    assert command[1] == str(tmp_path / "scripts/native_voice_service.py")
    assert str(stop_path) in command
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["cosyvoice"]["env"]["DAFEIYU_COSY_MODEL"] == "G:/models/voice"
    assert "must-not-be-copied" not in config_path.read_text(encoding="utf-8")


def test_wsl_fallback_keeps_linux_model_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "os", SimpleNamespace(name="nt"))
    specs, config_path, _ = launch.optional_specs(tmp_path, {"DAFEIYU_COSY_MODEL": "G:/models/voice"}, "test", ["cosyvoice"])
    assert specs[0][2][0] == "wsl.exe"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["cosyvoice"]["env"]["DAFEIYU_COSY_MODEL"] == "/mnt/g/models/voice"


def test_missing_native_runtime_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "os", SimpleNamespace(name="nt"))
    with pytest.raises(ValueError, match="Missing native CosyVoice Python"):
        launch.optional_specs(tmp_path, {"DAFEIYU_COSY_PYTHON": "missing.exe"}, "test", ["cosyvoice"])
