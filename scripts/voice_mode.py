"""Resolve model service lifecycle from the same saved policy as the gateway."""
from __future__ import annotations


def configure_voice_mode(env: dict[str, str], kinds: set[str], *, external=False, settings=None) -> str:
    from server.tts_policy import resolve_tts_mode
    env.setdefault("DAFEIYU_VOICE_MODE", "auto")
    mode = resolve_tts_mode(settings or {}, env)
    # Explicit GPU mode reserves the selected model, including reference/cache
    # warmup, for the lifetime of the mode. Auto remains demand-driven.
    env["DAFEIYU_GPU_PRELOAD"] = "1" if mode == "gpu" else "0"
    env["DAFEIYU_GPU_TTS_MODEL"] = (settings or {}).get("gpu_tts_model", "index_tts")
    env.update(DAFEIYU_ASR_DEVICE="CPU", DAFEIYU_ASR_BACKEND="sensevoice", DAFEIYU_TTS_BACKEND="disabled")
    kinds.difference_update({"cosyvoice", "index_tts", "moss_tts"})
    for kind, wanted, port, key in (("index_tts", mode in {"gpu", "auto"}, 8770, "index_tts_url"),
                                     ("moss_tts", mode in {"cpu", "auto"}, 8772, "moss_tts_url")):
        address = (settings or {}).get(key, f"http://127.0.0.1:{port}").rstrip("/")
        if wanted and not external and address in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            kinds.add(kind)
    return mode
