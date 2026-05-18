"""Stratum configuration module."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

_cfg: dict[str, object] = {}


def load_config(path: Path | None = None) -> dict[str, object]:
    global _cfg
    _cfg = {}
    if path is None:
        path = Path.home() / ".stratum" / "config.yaml"
    if path.exists():
        with open(path) as f:
            _cfg = yaml.safe_load(f) or {}
    # Env var overrides
    for key in ("DASHSCOPE_API_KEY", "ANTHROPIC_API_KEY"):
        if key in os.environ:
            _cfg[key] = os.environ[key]
    for k, v in os.environ.items():
        if k.startswith("STRATUM_"):
            _cfg[k] = v
    return _cfg


def get(key: str, default: object = None) -> object:
    return _cfg.get(key, os.environ.get(key, default))
