"""Distribution path contracts without model downloads, services or credentials."""
import json
import importlib
from pathlib import Path

from dafeiyu_paths import data_dir, models_dir, cache_dir, runtime_dir, home_dir, environment_dir


def test_source_layout_and_explicit_home_paths(tmp_path):
    code = tmp_path / "code"
    home = tmp_path / "chosen-home"
    for function, child in ((data_dir, "data"), (models_dir, "models"),
                            (cache_dir, "cache"), (runtime_dir, ".runtime")):
        assert function(code, {}) == code / child
        assert function(code, {"DAFEIYU_HOME": str(home)}) == home / child
    assert environment_dir(".venv-voice", code, {"DAFEIYU_HOME": str(home)}) == home / ".venv-voice"
    assert home_dir(code, {"DAFEIYU_HOME": "relative-home"}) == code / "relative-home"
    assert data_dir(code, {"DAFEIYU_HOME": str(home), "DAFEIYU_DATA_DIR": "custom"}) == code / "custom"
    assert not code.exists() and not home.exists()


def test_native_tts_lifecycle_and_caches_stay_in_explicit_home(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    launch = importlib.import_module("optional_voice")
    code = tmp_path / "immutable-code"
    home = tmp_path / "home"
    code.mkdir()
    interpreter = home / "runtimes/moss-tts/Scripts/python.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    env = {"DAFEIYU_HOME": str(home), "LLM_API_KEY": "never-copy-this"}
    specs, config, stop = launch.optional_specs(code, env, "fixture", ["moss_tts"])
    assert config.parent == stop.parent == home / ".runtime"
    assert specs[0][2][0] == str(interpreter)
    body = json.loads(config.read_text(encoding="utf8"))
    assert Path(body["moss_tts"]["env"]["HF_HOME"]) == home / "cache/huggingface"
    assert "never-copy-this" not in config.read_text(encoding="utf8")
    assert list(code.iterdir()) == []


def test_saved_policy_reads_same_home_database_as_gateway(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    launch = importlib.import_module("voice_services")
    home = tmp_path / "home"
    (home / "data").mkdir(parents=True)
    with sqlite3.connect(home / "data/companion.sqlite3") as db:
        db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO settings VALUES('tts_mode','\"api\"')")
    assert launch.saved_voice_settings(tmp_path / "code", {"DAFEIYU_HOME": str(home)}) == {"tts_mode": "api"}


def test_wsl_receives_converted_home_and_runtime_paths(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    launch = importlib.import_module("optional_voice")
    home = tmp_path / "chosen home"
    specs, config, _ = launch.optional_specs(tmp_path / "code", {"DAFEIYU_HOME": str(home)}, "wsl-fixture", ["cosyvoice"])
    command = specs[0][2]
    assert command[command.index("--home") + 1] == launch.wsl_path(str(home))
    assert command[command.index("--runtime-dir") + 1] == launch.wsl_path(str(home / ".runtime"))
    assert config.parent == home / ".runtime"


def test_gpt_sovits_preparation_honors_separate_model_directory(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    monkeypatch.setenv("DAFEIYU_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("DAFEIYU_MODELS_DIR", str(tmp_path / "large-drive-models"))
    prepare = importlib.import_module("prepare_gpt_sovits")
    try:
        importlib.reload(prepare)
        assert prepare.MODEL == tmp_path / "large-drive-models/gpt-sovits-v5"
    finally:
        monkeypatch.delenv("DAFEIYU_HOME", raising=False)
        monkeypatch.delenv("DAFEIYU_MODELS_DIR", raising=False)
        importlib.reload(prepare)
