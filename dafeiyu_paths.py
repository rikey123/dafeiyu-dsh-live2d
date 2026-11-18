"""Separate immutable application files from explicitly located user state.

DAFEIYU_HOME is the writable installation home for a distributed plugin. When
unset, source checkouts use a source-relative directory layout. Individual
directory overrides remain available to existing deployments.
"""
from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Mapping

ROOT = Path(__file__).resolve().parent


def _directory(name: str, relative: str, root: Path | None = None,
               env: Mapping[str, str] | None = None) -> Path:
    root = Path(root) if root is not None else ROOT
    values = os.environ if env is None else env
    home = Path(values.get("DAFEIYU_HOME") or root).expanduser()
    if not home.is_absolute():
        home = root / home
    target = Path(values.get(name) or home / relative).expanduser()
    return (target if target.is_absolute() else root / target).resolve()


def data_dir(root: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    return _directory("DAFEIYU_DATA_DIR", "data", root, env)


def models_dir(root: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    return _directory("DAFEIYU_MODELS_DIR", "models", root, env)


def runtime_dir(root: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    return _directory("DAFEIYU_RUNTIME_DIR", ".runtime", root, env)


def cache_dir(root: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    return _directory("DAFEIYU_CACHE_DIR", "cache", root, env)


def home_dir(root: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    return _directory("DAFEIYU_HOME", ".", root, env)


def environment_dir(name: str, root: Path | None = None,
                    env: Mapping[str, str] | None = None) -> Path:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("environment name must be a single directory name")
    return home_dir(root, env) / name
