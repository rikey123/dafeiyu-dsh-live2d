"""One routing contract for configuration, status, launcher and speech pipeline.

An explicit saved mode wins over deployment defaults. Legacy settings retain
DAFEIYU_VOICE_MODE and tts_engine behavior until the user chooses a mode.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

MODES = ("auto", "cpu", "gpu", "api")
GPU_MODELS = {"index_tts": "IndexTTS-2.5", "gpt_sovits": "GPT-SoVITS-v5-turbo"}


def gpu_model_name(settings: Mapping) -> str:
    return GPU_MODELS[settings.get("gpu_tts_model", "index_tts")]


def resolve_tts_mode(settings: Mapping, environ: Mapping | None = None) -> str:
    selected = settings.get("tts_mode", "legacy")
    if selected in MODES:
        return selected
    if selected != "legacy":
        raise ValueError("invalid tts_mode")
    policy = (os.environ if environ is None else environ).get("DAFEIYU_VOICE_MODE", "manual").strip().lower()
    if policy in MODES:
        return policy
    if policy != "manual":
        raise ValueError("invalid DAFEIYU_VOICE_MODE")
    return "gpu" if settings.get("tts_engine") == "cosyvoice" else "cpu"


def api_configured(settings: Mapping) -> bool:
    fields = ["tts_api_base_url", "tts_api_voice", "tts_api_key"]
    if settings.get("tts_api_provider", "deepseek") == "deepseek":
        if settings.get("tts_api_voice") not in {"stella", "tide"}:
            return False
    else:
        fields.append("tts_api_model")
    return all(str(settings.get(key, "")).strip() for key in fields)
