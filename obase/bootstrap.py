from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import structlog

from obase.exceptions import EnvLoadError, FSError, ProviderDiscoveryError
from obase.fs import FS

_URL_KEY_RE = re.compile(r"(_URL|_BASE_URL)$")


def load_env(path: Path = Path(".env"), strict: bool = True) -> dict[str, str]:
    """Safely load a .env file into os.environ.

    - Strips inline # comments
    - Empty values are not injected
    - Keys matching *_URL or *_BASE_URL must have a valid scheme+host
    """
    if not path.exists():
        if strict:
            raise EnvLoadError(f".env file not found: {path}")
        return {}

    log = structlog.get_logger()
    injected: dict[str, str] = {}

    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, raw_val = line.partition("=")
            key = key.strip()
            raw_val = raw_val.strip()

            # Strip inline comments: split on ' #' or '\t#'
            value = re.split(r"\s+#", raw_val, maxsplit=1)[0].strip()
            # Remove surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]

            if not key:
                continue
            if not value:
                continue

            if _URL_KEY_RE.search(key):
                parsed = urlparse(value)
                if not parsed.scheme or not parsed.netloc:
                    msg = f"Invalid URL for {key!r}: {value!r} (must have scheme and host)"
                    if strict:
                        raise EnvLoadError(msg)
                    log.warning("obase.bootstrap.invalid_url", key=key, value=value)

            os.environ[key] = value
            injected[key] = value

    return injected


def bootstrap(
    env_path: Path | None = None,
    working_dir: Path | None = None,
    auto_discover_providers: bool = True,
    logger_level: str = "INFO",
) -> None:
    """One-shot initializer for obase-based applications."""
    from obase.provider_registry import ProviderRegistry

    _configure_structlog(logger_level)
    log = structlog.get_logger()

    if env_path is not None:
        load_env(env_path)

    if working_dir is not None:
        try:
            FS.set_default_working_dir(working_dir)
        except FSError:
            raise

    if auto_discover_providers:
        try:
            ProviderRegistry.auto_discover()
        except ProviderDiscoveryError:
            raise

    log.info("obase.bootstrap.ready", working_dir=str(FS.working_dir()))


def _configure_structlog(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric)

    is_tty = os.isatty(1) if hasattr(os, "isatty") else False
    renderer: structlog.types.Processor
    if is_tty:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
