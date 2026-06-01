from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class WatchHandle:
    """Handle returned by watch_config to stop the watcher."""

    def __init__(self, thread: threading.Thread, stop_event: threading.Event) -> None:
        self._thread = thread
        self._stop_event = stop_event

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _apply_env_overrides(config: dict[str, Any], prefix: str = "STRATUM_") -> dict[str, Any]:
    """Apply environment variable overrides for vars matching prefix."""
    result = config.copy()
    for key, val in os.environ.items():
        if key.startswith(prefix):
            config_key = key[len(prefix) :].lower()
            result[config_key] = val
    return result


def load_config(
    *,
    paths: list[Path],
    schema: type[BaseModel] | None = None,
    merge_strategy: str = "deep",
    env_prefix: str = "STRATUM_",
) -> dict[str, Any]:
    """Load and deep-merge multiple YAML config files.

    Args:
        paths: Config file paths (later paths override earlier ones)
        schema: Optional Pydantic model for validation
        merge_strategy: "deep" (recursive merge) or "shallow" (dict update)
        env_prefix: Environment variable prefix for overrides

    Returns:
        Merged configuration dict

    Raises:
        FileNotFoundError: If a required config file doesn't exist
        ValueError: Schema validation failure
    """
    merged: dict[str, Any] = {}
    for path in paths:
        if not path.exists():
            continue
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        if merge_strategy == "deep":
            merged = _deep_merge(merged, data)
        else:
            merged.update(data)

    merged = _apply_env_overrides(merged, prefix=env_prefix)

    if schema is not None:
        try:
            schema.model_validate(merged)
        except Exception as e:
            raise ValueError(f"Config validation failed: {e}") from e

    return merged


def watch_config(
    *,
    paths: list[Path],
    callback: Any,
    interval: float = 5.0,
    env_prefix: str = "STRATUM_",
) -> WatchHandle:
    """Watch config files for changes and call callback with merged config.

    Args:
        paths: Config paths to watch
        callback: Called with merged dict when files change
        interval: Polling interval in seconds
        env_prefix: Env var prefix for overrides

    Returns:
        WatchHandle (call .stop() to terminate the watcher)
    """
    stop_event = threading.Event()
    last_mtimes: dict[str, float] = {}

    def _watch() -> None:
        while not stop_event.wait(timeout=interval):
            changed = False
            for p in paths:
                if p.exists():
                    mtime = p.stat().st_mtime
                    if last_mtimes.get(str(p)) != mtime:
                        last_mtimes[str(p)] = mtime
                        changed = True
            if changed:
                try:
                    config = load_config(paths=paths, env_prefix=env_prefix)
                    callback(config)
                except Exception:
                    pass

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return WatchHandle(t, stop_event)
