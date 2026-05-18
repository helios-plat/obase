"""Stratum structured logging module."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_logger = logging.getLogger("stratum")
_initialized = False


def setup_logging(level: str = "INFO") -> None:
    global _initialized
    if _initialized:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    _initialized = True


def _payload(event_type: str, **kwargs: object) -> str:
    return json.dumps(
        {"event": event_type, "ts": datetime.now(UTC).isoformat(), **kwargs},
        default=str,
    )


def emit(event_type: str, **kwargs: object) -> None:
    _logger.info(_payload(event_type, **kwargs))


def error(msg: str, **kwargs: object) -> None:
    _logger.error(_payload("error", msg=msg, **kwargs))


def warning(msg: str, **kwargs: object) -> None:
    _logger.warning(_payload("warning", msg=msg, **kwargs))


def info(msg: str, **kwargs: object) -> None:
    _logger.info(_payload("info", msg=msg, **kwargs))
