from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/mneme"
    REDIS_URL: str = "redis://localhost:6380/0"
    ANTHROPIC_API_KEY: str = "your_key_here"
    DEEPSEEK_API_KEY: str = "your_key_here"
    QWEN_API_KEY: str = "your_key_here"
    DASHSCOPE_API_KEY: str = "your_key_here"
    OPENAI_API_KEY: str = "your_key_here"
    GEMINI_API_KEY: str = "your_key_here"

    MINIO_ENDPOINT: str = "localhost:9002"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "mneme"

    JWT_SECRET: str = "mneme-dev-secret-change-in-prod!"
    JWT_EXPIRE_SECONDS: int = 86400 * 7  # 7 days

    ALIYUN_ACCESS_KEY_ID: str = ""
    ALIYUN_ACCESS_KEY_SECRET: str = ""
    ALIYUN_NLS_APP_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


# ---------------------------------------------------------------------------
# YAML config loader (load_config / watch_config)
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` (override wins). Returns a new dict."""
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def load_config(
    *,
    paths: Sequence[Path | str],
    schema: type[BaseModel] | None = None,
    env_prefix: str = "",
) -> dict[str, Any]:
    """Load and merge YAML config files, apply env overrides, optionally validate.

    - Files in ``paths`` are read in order; each deep-merges over the previous
      (later files win). Missing files are skipped.
    - When ``env_prefix`` is non-empty, environment variables named
      ``{env_prefix}{KEY}`` override the top-level ``key`` (lower-cased).
    - When ``schema`` is given, the merged config is validated against it; on
      failure a ``ValueError`` starting with ``"Config validation failed"`` is
      raised, and on success the validated/coerced data is returned.
    """
    merged: dict[str, Any] = {}
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Config file {p} must contain a mapping at top level")
        merged = _deep_merge(merged, data)

    if env_prefix:
        for env_key, env_val in os.environ.items():
            if env_key.startswith(env_prefix):
                key = env_key[len(env_prefix) :].lower()
                if key:
                    merged[key] = env_val

    if schema is not None:
        try:
            validated = schema(**merged)
        except Exception as exc:
            raise ValueError(f"Config validation failed: {exc}") from exc
        return validated.model_dump()

    return merged


class ConfigWatcher:
    """Handle for a running :func:`watch_config` poller."""

    def __init__(self, thread: threading.Thread, stop_event: threading.Event) -> None:
        self._thread = thread
        self._stop_event = stop_event

    def stop(self) -> None:
        """Stop polling and wait for the watcher thread to exit."""
        self._stop_event.set()
        self._thread.join(timeout=5.0)


def watch_config(
    *,
    paths: Sequence[Path | str],
    callback: Callable[[dict[str, Any]], None],
    interval: float = 1.0,
    schema: type[BaseModel] | None = None,
    env_prefix: str = "",
) -> ConfigWatcher:
    """Poll ``paths`` every ``interval`` seconds; on any change, reload and call ``callback``.

    Change detection is content-based (hash), so it is robust regardless of
    filesystem mtime resolution. Returns a :class:`ConfigWatcher` whose
    ``stop()`` method ends watching.
    """
    resolved = [Path(p) for p in paths]

    def _signature() -> dict[Path, str | None]:
        sig: dict[Path, str | None] = {}
        for p in resolved:
            try:
                sig[p] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                sig[p] = None
        return sig

    stop_event = threading.Event()
    last = _signature()

    def _run() -> None:
        nonlocal last
        while not stop_event.wait(interval):
            current = _signature()
            if current == last:
                continue
            last = current
            try:
                cfg = load_config(paths=paths, schema=schema, env_prefix=env_prefix)
            except Exception:
                continue
            callback(cfg)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return ConfigWatcher(thread, stop_event)
