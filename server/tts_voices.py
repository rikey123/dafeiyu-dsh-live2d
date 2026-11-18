"""Public MOSS preset metadata; never imports/starts an inference runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dafeiyu_paths import models_dir

MAX_CATALOG_BYTES = 2 * 1024 * 1024
MODEL = "MOSS-TTS-Nano"


class VoiceCatalogUnavailable(ValueError):
    pass


def public_voices(rows, *, manifest=False):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise VoiceCatalogUnavailable("MOSS 音色清单为空或格式无效")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise VoiceCatalogUnavailable("MOSS 音色条目无效")
        identifier = row.get("voice" if manifest else "id")
        name = row.get("display_name" if manifest else "name")
        group = row.get("group")
        if (any(not isinstance(v, str) or not v.strip() or len(v) > 200
                or any(ord(c) < 32 for c in v) for v in (identifier, name, group))
                or identifier in seen or identifier == "default"):
            raise VoiceCatalogUnavailable("MOSS 音色 ID、名称或分组无效")
        if manifest and (not isinstance(row.get("prompt_audio_codes"), list) or not row["prompt_audio_codes"]):
            raise VoiceCatalogUnavailable("MOSS 预置音色缺少参考编码")
        seen.add(identifier)
        # Allowlist only: never send audio codes, filenames or local paths.
        result.append({"id": identifier, "name": name, "group": group})
    return result


def installed_catalog(model_dir: str | Path | None = None):
    base = Path(model_dir if model_dir is not None else os.environ.get(
        "DAFEIYU_MOSS_MODEL", str(models_dir() / "moss-tts-nano")))
    candidates = (base / "browser_poc_manifest.json", base / "MOSS-TTS-Nano-100M-ONNX/browser_poc_manifest.json")
    path = next((p for p in candidates if p.is_file()), None)
    try:
        if path is None:
            raise VoiceCatalogUnavailable("未找到本机 MOSS 模型的音色清单，请先准备模型")
        with path.open("rb") as handle:
            raw = handle.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            raise VoiceCatalogUnavailable("MOSS 音色清单过大")
        data = json.loads(raw)
        voices = public_voices(data.get("builtin_voices"), manifest=True)
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        raise VoiceCatalogUnavailable("无法读取本机 MOSS 音色清单，请检查模型安装") from exc
    return {"model": MODEL, "source": "installed_manifest", "default_voice": voices[0]["id"], "voices": voices}


def service_catalog(data):
    if not isinstance(data, dict) or data.get("model") != MODEL:
        raise VoiceCatalogUnavailable("音色服务不是 MOSS-TTS-Nano")
    voices = public_voices(data.get("voices"))
    if data.get("default_voice") not in {voice["id"] for voice in voices}:
        raise VoiceCatalogUnavailable("MOSS 服务的默认音色无效")
    return {"model": MODEL, "source": "service", "default_voice": data["default_voice"], "voices": voices}
