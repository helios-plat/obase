"""audit_logger — Structured decision audit logging."""
from __future__ import annotations

import json
import time
from typing import Any


class AuditLoggerError(Exception):
    """Base error for audit_logger."""


class AuditLogger:
    """Append-only audit logger for decision tracking.

    Example:
        >>> logger = AuditLogger()
        >>> logger.log_decision(fingerprint="abc", action="approve", actor="system")
        >>> len(logger.entries)
        1
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    def log_decision(
        self,
        *,
        fingerprint: str,
        action: str,
        actor: str,
        diff: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Log a decision event.

        Args:
            fingerprint: Decision fingerprint (64-char SHA-256).
            action: Action taken (approve/reject/override).
            actor: Who made the decision.
            diff: Optional before/after diff.
            metadata: Optional extra metadata.
        """
        self._entries.append({
            "timestamp": time.time(),
            "fingerprint": fingerprint,
            "action": action,
            "actor": actor,
            "diff": diff,
            "metadata": metadata,
        })

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Get all audit entries."""
        return self._entries

    def to_json(self) -> str:
        """Serialize entries to JSON."""
        return json.dumps(self._entries, default=str)
