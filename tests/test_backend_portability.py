"""Backend paths remain relocatable without writing into the application payload."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from dafeiyu_paths import data_dir, home_dir, models_dir
from server.model_tts_sidecar import model_config
from server.tts_voices import installed_catalog


def test_directory_defaults_and_overrides(tmp_path):
    root = tmp_path / "payload"
    home = tmp_path / "home"
    assert data_dir(root, {}) == root / "data"
    assert models_dir(root, {}) == root / "models"
    assert home_dir(root, {}) == root
    env = {"DAFEIYU_HOME": str(home), "DAFEIYU_DATA_DIR": "state", "DAFEIYU_MODELS_DIR": "weights"}
    assert data_dir(root, env) == root / "state"
    assert models_dir(root, env) == root / "weights"
    assert home_dir(root, env) == home


def test_model_paths_follow_home_and_overrides(monkeypatch, tmp_path):
    home, weights = tmp_path / "home", tmp_path / "weights"
    monkeypatch.setenv("DAFEIYU_HOME", str(home))
    monkeypatch.setenv("DAFEIYU_MODELS_DIR", str(weights))
    for name in ("DAFEIYU_INDEX_SOURCE", "DAFEIYU_INDEX_MODEL", "DAFEIYU_MOSS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    config = model_config("index_tts")
    assert Path(config["source"]) == home / "source" / "index-tts-2.5"
    assert Path(config["model"]) == weights / "index-tts-2.5"
    model = weights / "moss-tts-nano"
    model.mkdir(parents=True)
    (model / "browser_poc_manifest.json").write_text(json.dumps({"builtin_voices": [{"voice": "one", "display_name": "One", "group": "A", "prompt_audio_codes": [1]}]}), encoding="utf-8")
    assert installed_catalog()["default_voice"] == "one"
    monkeypatch.setenv("DAFEIYU_INDEX_MODEL", str(home / "custom"))
    assert Path(model_config("index_tts")["model"]) == home / "custom"


def test_store_writes_only_to_external_home(tmp_path):
    root = Path(__file__).resolve().parents[1]
    payload = tmp_path / "payload"
    (payload / "server").mkdir(parents=True)
    for name in ("__init__.py", "storage.py", "dsh.py"):
        shutil.copyfile(root / "server" / name, payload / "server" / name)
    shutil.copyfile(root / "dafeiyu_paths.py", payload / "dafeiyu_paths.py")
    before = {p.relative_to(payload): p.read_bytes() for p in payload.rglob("*") if p.is_file()}
    env = os.environ.copy()
    for key in ("DAFEIYU_DATA_DIR", "DAFEIYU_MODELS_DIR", "DAFEIYU_HARNESS"):
        env.pop(key, None)
    env.update(DAFEIYU_HOME=str(tmp_path / "user"), PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(payload))
    code = "from server.storage import Store; s=Store(); s.update_settings({\"tts_api_key\":\"test-secret\"}); s.db.close()"
    subprocess.run([sys.executable, "-c", code], cwd=payload, env=env, check=True)
    assert (tmp_path / "user" / "data" / "companion.sqlite3").is_file()
    assert {p.relative_to(payload): p.read_bytes() for p in payload.rglob("*") if p.is_file()} == before
