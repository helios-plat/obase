"""Shared Action Gateway value types.

This module deliberately contains data and redaction helpers only.  It has no
knowledge of policy engines, services, Veya tasks, or persistence backends.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

ActionEffect = Literal[
    "read",
    "local_write",
    "process",
    "network",
    "remote",
    "destructive",
]
ActionVerdict = Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]

_SECRET_WORDS = frozenset(
    {
        "authorization",
        "credential",
        "password",
        "private_key",
        "secret",
        "token",
    }
)


def _is_secret_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SECRET_WORDS or any(
        part in normalized for part in ("token", "password", "secret", "credential")
    )


def redact_value(value: Any) -> Any:
    """Return a JSON-safe value with credential-like fields removed."""
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_secret_key(key) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass(frozen=True)
class ActionRequest:
    """A provider/tool-independent request crossing the governance boundary."""

    action: str
    effect: ActionEffect = "read"
    resource: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    actor: str = "system"
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source: str = ""
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        args = redact_value(self.arguments) if redact else dict(self.arguments)
        context = redact_value(self.context) if redact else dict(self.context)
        return {
            "action": self.action,
            "effect": self.effect,
            "resource": self.resource,
            "arguments": args,
            "actor": self.actor,
            "request_id": self.request_id,
            "source": self.source,
            "context": context,
        }

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class ActionDecision:
    """The only decision states understood by the Action Gateway."""

    verdict: ActionVerdict
    reason: str = ""
    policy_id: str | None = None
    approved: bool = False
    request_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "approved": self.approved,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class PolicyRule:
    """Declarative rule data consumed by a stateless policy evaluator."""

    rule_id: str
    decision: ActionVerdict
    action: str = "*"
    effect: str = "*"
    resource: str = "*"
    priority: int = 0


@dataclass(frozen=True)
class AuditRecord:
    """Redacted audit value handed to an injected persistence adapter."""

    event: str
    request_id: str
    action: str
    decision: ActionVerdict | None = None
    actor: str = "system"
    success: bool | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "request_id": self.request_id,
            "action": self.action,
            "decision": self.decision,
            "actor": self.actor,
            "success": self.success,
            "detail": redact_value(self.detail),
            "record_id": self.record_id,
            "timestamp": self.timestamp,
        }


__all__ = [
    "ActionDecision",
    "ActionEffect",
    "ActionRequest",
    "ActionVerdict",
    "AuditRecord",
    "PolicyRule",
    "redact_value",
]
