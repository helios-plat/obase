"""audit.writer — AuditWriter Protocol.

obase ships the contract only; concrete implementations (DB, file, webhook)
live in consuming services.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from obase.audit.formatter import AuditEntry


@runtime_checkable
class AuditWriter(Protocol):
    """Protocol for async audit log persistence.

    Implementors receive :class:`~obase.audit.AuditEntry` objects and are
    responsible for durably storing or forwarding them.  obase does not ship
    any concrete implementation — services provide their own.

    Example::

        class PostgresAuditWriter:
            def __init__(self, db: AsyncEngine) -> None:
                self._db = db

            async def write(self, entry: AuditEntry) -> None:
                async with self._db.begin() as conn:
                    await conn.execute(INSERT_SQL, entry.model_dump())
    """

    async def write(self, entry: AuditEntry) -> None:
        """Persist or forward an AuditEntry.

        Args:
            entry: The validated audit event to record.
        """
        ...
