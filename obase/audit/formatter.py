"""audit.formatter — Pure factory for validated AuditEntry values."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from obase.uuid7 import uuid7


class AuditEntry(BaseModel):
    """Immutable audit event record.

    Attributes:
        id: UUIDv7 identifier — time-sortable, globally unique.
        actor: Who performed the action (user id, service name, ``"system"``).
        action: Verb describing the event (e.g. ``"create"``, ``"delete"``, ``"approve"``).
        resource_type: Logical category of the affected resource (e.g. ``"trade"``, ``"alert_rule"``).
        resource_id: Unique identifier of the affected resource.
        detail: Optional key-value metadata (must be JSON-serialisable).
        timestamp: UTC datetime of the event.

    Example:
        >>> from datetime import datetime, timezone
        >>> entry = AuditEntry(
        ...     id="01927f4e-0000-7000-8000-000000000001",
        ...     actor="user_42",
        ...     action="approve",
        ...     resource_type="trade",
        ...     resource_id="t_001",
        ...     timestamp=datetime.now(tz=timezone.utc),
        ... )
        >>> entry.action
        'approve'
    """

    id: str = Field(..., min_length=36, max_length=36)
    actor: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    resource_type: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    detail: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


def format_audit_entry(
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict[str, Any] | None = None,
) -> AuditEntry:
    """Build a validated :class:`AuditEntry` with a fresh uuid7 id and UTC timestamp.

    This is a pure factory — it assigns ``id`` and ``timestamp``; all other
    fields come from the caller.  No side effects, no I/O.

    Args:
        actor: Identity performing the action (user id, service name, or ``"system"``).
        action: Verb label for the event (e.g. ``"create"``, ``"approve"``, ``"delete"``).
        resource_type: Logical type of the resource (e.g. ``"trade"``, ``"alert_rule"``).
        resource_id: Unique identifier of the affected resource.
        detail: Optional free-form metadata dict (must be JSON-serialisable).
            Defaults to ``{}``.

    Returns:
        A validated :class:`AuditEntry` with ``id=uuid7()`` and ``timestamp=UTC now``.

    Example:
        >>> entry = format_audit_entry(
        ...     actor="user_42",
        ...     action="approve",
        ...     resource_type="trade",
        ...     resource_id="t_001",
        ...     detail={"amount": 100},
        ... )
        >>> entry.action
        'approve'
        >>> entry.detail
        {'amount': 100}
    """
    return AuditEntry(
        id=uuid7(),
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail or {},
        timestamp=datetime.now(tz=timezone.utc),
    )
