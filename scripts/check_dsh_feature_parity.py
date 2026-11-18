#!/usr/bin/env python3
"""Offline structural parity audit; never imports application code or reads data/config."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Explicit source allowlist: never traverse data/, logs, model assets or configuration.
PY_FILES = {
    "server/main.py": ("SettingsUpdate",),
    "server/storage.py": ("Store",), "server/pipecat_voice.py": ("PriorityRTVIProcessor", "run_voice"),
    "server/playback.py": ("PlaybackLedger", "ConfirmedContext", "PlaybackStart", "PlaybackBoundary"),
    "server/moss_live.py": ("MossLiveBridge", "run_moss_voice"),
    "server/systemone.py": ("SystemOneClient",), "server/systemone_pipeline.py": (),
    "server/systemone_initiative.py": (), "server/tts_policy.py": ("resolve_tts_mode",),
    "server/tts_voices.py": (), "server/model_tts_sidecar.py": ("ModelHost",),
    "speech/server.py": ("Engine",), "speech/streaming_asr.py": ("stream_asr",),
    "speech/pipecat_services.py": ("LocalSpeechSTT", "LocalSpeechTTS"),
    "speech/pipecat_turns.py": ("ChineseTurnStartStrategy", "ChineseBackchannelFilter"),
    "speech/api_tts.py": (), "speech/model_engines.py": (),
}
# Frontend differences need review: authorized memory removal may change shared files.
UI_FILES = ("web/src/App.tsx", "web/src/style.css", "web/src/Avatar.tsx", "web/src/voice.ts",
            "web/src/playback.ts", "web/src/OwnerVoice.tsx", "web/src/systemoneSettings.tsx",
            "web/src/ttsSettings.tsx", "web/src/MossVoicePicker.tsx", "web/src/ui/WardrobePanel.tsx",
            "web/src/ui/Backdrop.tsx", "web/src/ui/theme.ts", "web/src/avatar/wardrobe.ts")
INITIATIVE = {"systemone_initiative_threshold", "systemone_initiative_min_speech_ms",
 "systemone_initiative_cooldown_s", "systemone_initiative_wait_threshold",
 "systemone_initiative_max_reply_chars", "systemone_initiative_probe_interval_ms", "systemone_initiative_max_probes"}

# Only the old application's manual-memory API and storage are exempt.
MEMORY_SYMBOL_EXCEPTIONS = {
    "server/main.py": {"MemoryInput", "memories", "add_memory", "delete_memory"},
    "server/storage.py": {"Store.memories", "Store.add_memory", "Store.delete_memory"},
}
MEMORY_ROUTE_EXCEPTIONS = {
    ("GET", "/api/memories"), ("POST", "/api/memories"),
    ("DELETE", "/api/memories/{memory_id}"),
}

def parse(root, relative, gaps):
    path = root / relative
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as exc:
        gaps.append({"check": "python_parse", "path": relative, "detail": type(exc).__name__})
        return None

def signatures(tree):
    result = set()
    if tree is None:
        return result
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.add(node.name)
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        result.add(node.name + "." + item.target.id)
                    elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        result.add(node.name + "." + item.name)
    return result

def routes(tree):
    result = set()
    if tree is None:
        return result
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in {"get", "post", "put", "delete", "websocket"}
                and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str)):
                result.add((dec.func.attr.upper(), dec.args[0].value))
    return result

def literals(tree):
    if tree is None:
        return set()
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("voice.") and len(n.value) < 80}

def digest(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None

def audit(baseline, target):
    gaps, reviews, checked, trees = [], [], [], {}
    for relative, required in PY_FILES.items():
        old = parse(baseline, relative, gaps)
        new = parse(target, relative, gaps)
        trees[relative] = (old, new)
        if old is None or new is None:
            continue
        before, after = signatures(old), signatures(new)
        missing = (before | set(required)) - after - MEMORY_SYMBOL_EXCEPTIONS.get(relative, set())
        for item in sorted(missing):
            gaps.append({"check": "python_symbol", "path": relative, "detail": item})
        route_exceptions = MEMORY_ROUTE_EXCEPTIONS if relative == "server/main.py" else set()
        for method, path in sorted(routes(old) - routes(new) - route_exceptions):
            gaps.append({"check": "route", "path": relative, "detail": method + " " + path})
        for event in sorted(literals(old) - literals(new)):
            gaps.append({"check": "protocol_event", "path": relative, "detail": event})
        checked.append(relative)
    old, new = trees["server/main.py"]
    if old is not None and new is not None:
        for field in sorted(INITIATIVE):
            key = "SettingsUpdate." + field
            if key not in signatures(old) or key not in signatures(new):
                gaps.append({"check": "initiative_setting", "path": "server/main.py", "detail": field})
    for relative in UI_FILES:
        a, b = digest(baseline / relative), digest(target / relative)
        if a is None or b is None:
            gaps.append({"check": "frontend_review", "path": relative,
                         "detail": "missing file"})
        elif a != b:
            reviews.append({"check": "frontend_review", "path": relative,
                            "detail": "content differs; review non-memory appearance and interactions; authorized manual-memory removal is exempt"})
        else:
            checked.append(relative)
    return {"baseline": str(baseline), "target": str(target), "checked_files": checked,
            "gaps": gaps, "reviews": reviews,
            "static_status": "gaps" if gaps else "review_required" if reviews else "no_structural_gaps_detected",
            "runtime_acceptance": "not_run", "note": "Structural evidence only; matching symbols, routes, events and hashes do not prove behavior or migration."}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=Path("G:/dafeiyu"), help="current source tree (read only)")
    parser.add_argument("--target", type=Path, default=ROOT, help="migration tree (read only)")
    args = parser.parse_args()
    result = audit(args.baseline.resolve(), args.target.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["gaps"] or result["reviews"] else 0

if __name__ == "__main__":
    sys.exit(main())
