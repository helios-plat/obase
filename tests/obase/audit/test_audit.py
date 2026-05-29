"""Tests for obase.audit (format_audit_entry + AuditWriter protocol)."""

from __future__ import annotations

import re
from datetime import timezone

import pytest

from obase.audit import AuditEntry, AuditWriter, format_audit_entry

_UUID7_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


# ── format_audit_entry ────────────────────────────────────────────────────────


class TestFormatAuditEntry:
    def test_returns_audit_entry_instance(self):
        entry = format_audit_entry(
            actor="user_1", action="create", resource_type="trade", resource_id="t_001"
        )
        assert isinstance(entry, AuditEntry)

    def test_all_caller_fields_preserved(self):
        entry = format_audit_entry(
            actor="svc",
            action="delete",
            resource_type="alert",
            resource_id="a_99",
            detail={"reason": "expired"},
        )
        assert entry.actor == "svc"
        assert entry.action == "delete"
        assert entry.resource_type == "alert"
        assert entry.resource_id == "a_99"
        assert entry.detail == {"reason": "expired"}

    def test_id_is_uuid7_format(self):
        entry = format_audit_entry(actor="a", action="b", resource_type="c", resource_id="d")
        assert _UUID7_RE.match(entry.id), f"Not uuid7: {entry.id!r}"

    def test_timestamp_is_utc(self):
        entry = format_audit_entry(actor="a", action="b", resource_type="c", resource_id="d")
        assert entry.timestamp.tzinfo is not None
        assert entry.timestamp.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_detail_defaults_to_empty_dict(self):
        entry = format_audit_entry(actor="a", action="b", resource_type="c", resource_id="d")
        assert entry.detail == {}

    def test_unique_ids_across_calls(self):
        a = format_audit_entry(actor="a", action="b", resource_type="c", resource_id="d")
        b = format_audit_entry(actor="a", action="b", resource_type="c", resource_id="d")
        assert a.id != b.id

    def test_nested_detail_dict_accepted(self):
        entry = format_audit_entry(
            actor="sys",
            action="update",
            resource_type="config",
            resource_id="cfg_1",
            detail={"before": {"x": 1}, "after": {"x": 2}},
        )
        assert entry.detail["before"]["x"] == 1


# ── AuditEntry validation ─────────────────────────────────────────────────────


class TestAuditEntry:
    def test_empty_actor_raises(self):
        from datetime import datetime

        with pytest.raises(Exception):
            AuditEntry(
                id="01927f4e-0000-7000-8000-000000000001",
                actor="",
                action="x",
                resource_type="y",
                resource_id="z",
                timestamp=datetime.now(tz=timezone.utc),
            )

    def test_id_length_enforced(self):
        from datetime import datetime

        with pytest.raises(Exception):
            AuditEntry(
                id="short",
                actor="a",
                action="b",
                resource_type="c",
                resource_id="d",
                timestamp=datetime.now(tz=timezone.utc),
            )


# ── AuditWriter Protocol ──────────────────────────────────────────────────────


class TestAuditWriterProtocol:
    def test_concrete_impl_satisfies_protocol(self):
        class MockWriter:
            async def write(self, entry: AuditEntry) -> None:
                pass

        assert isinstance(MockWriter(), AuditWriter)

    def test_missing_write_method_fails_isinstance(self):
        class NotAWriter:
            pass

        assert not isinstance(NotAWriter(), AuditWriter)

    def test_wrong_method_name_fails(self):
        class WrongWriter:
            async def save(self, entry: AuditEntry) -> None:
                pass

        assert not isinstance(WrongWriter(), AuditWriter)

    async def test_concrete_writer_can_be_called(self):
        received: list[AuditEntry] = []

        class CollectingWriter:
            async def write(self, entry: AuditEntry) -> None:
                received.append(entry)

        entry = format_audit_entry(
            actor="test", action="verify", resource_type="audit", resource_id="r_1"
        )
        writer = CollectingWriter()
        await writer.write(entry)
        assert len(received) == 1
        assert received[0].actor == "test"
