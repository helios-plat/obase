"""audit — Audit entry formatting and writer protocol.

depends_on_external: (none — uses obase.uuid7)
"""

from __future__ import annotations

from obase.audit.formatter import AuditEntry, format_audit_entry
from obase.audit.writer import AuditWriter

__all__ = [
    "AuditEntry",
    "format_audit_entry",
    "AuditWriter",
]
