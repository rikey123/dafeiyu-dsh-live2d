"""Build explicit, local-only optional voice service commands for the supervisor."""
from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dafeiyu_paths import runtime_dir, home_dir, cache_dir


def wsl_path(value: str) -> str:
    """Translate drive paths without shell interpolation; retain Linux paths."""
    path = PureWindowsPath(value)
    if path.drive and len(path.drive) == 2 and path.drive[1] == ":":
        return "/mnt/" + path.drive[0].lower() + "/" + "/".join(path.parts[1:])
    return value


def optional_specs(root: Path, values: dict, token: str, kinds: list[str]):
    if not kinds:
        return [], None, None
    if os.name != "nt":
        raise ValueError("Bundled optional model launch currently expects Windows")
    directory = runtime_dir(root, values)
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / f"voice-{token}.json"
    stop_path = directory / f"voice-stop-{token}"
    project = wsl_path(str(root))
    config = {}
    specs = []
    for kind in kinds:
        if kind in {"index_tts", "moss_tts"}:
            gsv = kind == "index_tts" and values.get("DAFEIYU_GPU_TTS_MODEL") == "gpt_sovits"
            prefix = "DAFEIYU_INDEX_" if kind == "index_tts" else "DAFEIYU_MOSS_"
            runtime_name = "index-tts-py311" if kind == "index_tts" else "moss-tts"
            if gsv:
                prefix, runtime_name = "DAFEIYU_GSV_", "gpt-sovits-py311"
            interpreter = Path(values.get(prefix + "PYTHON", str(home_dir(root, values) / "runtimes" / runtime_name / "Scripts/python.exe")))
            if not interpreter.is_file():
                raise ValueError(f"Missing {kind} runtime; run scripts/prepare_tts_models.py")
            env = {key: str(values[key]) for key in (prefix+suffix for suffix in (
                "SOURCE", "MODEL", "PROMPT_WAV", "PROMPT_TEXT", "THREADS", "IDLE_SECONDS")) if values.get(key)}
            cache = str(cache_dir(root, values))
            env.update(DAFEIYU_MODEL_SERVICE="gpt_sovits" if gsv else kind, HF_HOME=cache+"/huggingface", HF_HUB_OFFLINE="1",
                       TORCH_HOME=cache+"/torch", NLTK_DATA=cache+"/nltk", XDG_CACHE_HOME=cache, TEMP=cache+"/tmp", TMP=cache+"/tmp",
                       MPLCONFIGDIR=cache+"/matplotlib", NUMBA_CACHE_DIR=cache+"/numba",
                       TORCHINDUCTOR_CACHE_DIR=cache+"/torchinductor", TRITON_CACHE_DIR=cache+"/triton",
                       PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            if kind == "index_tts":
                env["DAFEIYU_GPU_PRELOAD"] = str(values.get("DAFEIYU_GPU_PRELOAD", "1"))
            config[kind] = {"env": env}
            specs.append((8770 if kind == "index_tts" else 8772, "/health", [str(interpreter),
                          str(root / "scripts/native_voice_service.py"), "--project", str(root),
                          "--config", str(config_path), "--stop-file", str(stop_path), "--kind", kind]))
            continue
        if kind != "cosyvoice":
            raise ValueError(f"Unknown voice service: {kind}")
        native_python = values.get("DAFEIYU_COSY_PYTHON") if kind == "cosyvoice" else None
        if kind == "cosyvoice":
            env = {key: str(values[key]) for key in (
                "DAFEIYU_COSY_MODEL", "DAFEIYU_COSY_SOURCE", "DAFEIYU_COSY_MATCHA",
                "DAFEIYU_COSY_PROMPT_WAV", "DAFEIYU_COSY_PROMPT_TEXT", "DAFEIYU_COSY_DEVICE",
                "DAFEIYU_COSY_VERSION", "DAFEIYU_COSY_PRECISION",
                "DAFEIYU_COSY_MIN_FREE_GIB", "DAFEIYU_COSY_MIN_TOTAL_GIB") if values.get(key)}
            for key in ("DAFEIYU_COSY_MODEL", "DAFEIYU_COSY_SOURCE", "DAFEIYU_COSY_MATCHA", "DAFEIYU_COSY_PROMPT_WAV"):
                if key in env and not native_python:
                    env[key] = wsl_path(env[key])
            env.setdefault("DAFEIYU_COSY_DEVICE", "cpu")
            env.update(OMP_NUM_THREADS=str(values.get("DAFEIYU_COSY_THREADS", "4")),
                       MKL_NUM_THREADS=str(values.get("DAFEIYU_COSY_THREADS", "4")))
            runtime = values.get("DAFEIYU_COSY_RUNTIME", "~/.local/share/dafeiyu-runtimes/cosy")
            port = 8770
        config[kind] = {"runtime": wsl_path(str(runtime)), "env": env}
        command = ["wsl.exe", "-d", str(values.get("DAFEIYU_VOICE_WSL_DISTRO", "Ubuntu")), "--exec", "python3",
                   project + "/scripts/wsl_voice_service.py", "--project", project,
                   "--home", wsl_path(str(home_dir(root, values))), "--runtime-dir", wsl_path(str(directory)),
                   "--config", wsl_path(str(config_path)), "--stop-file", wsl_path(str(stop_path)), "--kind", kind]
        if native_python:
            interpreter = Path(str(native_python)).expanduser()
            if not interpreter.is_absolute():
                interpreter = root / interpreter
            if not interpreter.is_file():
                raise ValueError(f"Missing native CosyVoice Python: {interpreter}")
            command = [str(interpreter), str(root / "scripts/native_voice_service.py"),
                       "--project", str(root), "--config", str(config_path),
                       "--stop-file", str(stop_path)]
        specs.append((port, "/health", command))
    # Only model-local allowlisted fields; never copy LLM credentials into service configuration.
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return specs, config_path, stop_path
