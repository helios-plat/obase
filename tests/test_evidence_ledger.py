from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from obase.evidence_ledger import (
    EvidenceRecordError,
    append_evidence_record,
    build_evidence_record,
    read_evidence_records,
    validate_evidence_record,
)


def _record(**overrides):
    values = {
        "source_type": "market_api",
        "source_uri": "HTTPS://Example.COM:443/v1/candles?b=2&a=1#section",
        "retrieved_at": "2026-10-22T08:00:00+08:00",
        "payload": {"symbol": "BTC-USDT", "close": "67000.10"},
        "query": "BTC-USDT 1d candles",
        "tool_name": "public_market_candles",
        "metadata": {"provider": "example"},
    }
    values.update(overrides)
    return build_evidence_record(**values)


def test_record_canonicalizes_uri_and_timestamp():
    record = _record()
    assert record["source_uri"] == "https://example.com/v1/candles?a=1&b=2"
    assert record["retrieved_at_utc"] == "2026-10-22T00:00:00Z"


def test_identical_content_has_deterministic_id_across_retrieval_times():
    first = _record(retrieved_at="2026-10-22T00:00:00Z")
    later = _record(retrieved_at="2026-10-23T00:00:00Z")
    assert first["evidence_id"] == later["evidence_id"]


def test_changed_payload_changes_identity():
    assert _record()["evidence_id"] != _record(payload={"close": "67001.10"})["evidence_id"]


@pytest.mark.parametrize("timestamp", ["2026-10-22", "not-a-date", datetime(2026, 10, 22)])
def test_naive_or_invalid_timestamp_rejected(timestamp):
    with pytest.raises(EvidenceRecordError):
        _record(retrieved_at=timestamp)


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "https://user:pass@example.com/",
        "https://example.com/?" + "api_key" + "=" + "blocked",
    ],
)
def test_unsafe_source_uri_rejected(uri):
    with pytest.raises(EvidenceRecordError):
        _record(source_uri=uri)


def test_non_json_and_non_finite_payload_rejected():
    with pytest.raises(EvidenceRecordError):
        _record(payload={"bad": object()})
    with pytest.raises(EvidenceRecordError):
        _record(payload={"bad": float("nan")})


def test_append_is_idempotent_and_read_round_trips(tmp_path: Path):
    ledger = tmp_path / "evidence.jsonl"
    record = _record()
    first = append_evidence_record(ledger, record)
    second = append_evidence_record(ledger, record)
    assert first == {"appended": True, "evidence_id": record["evidence_id"]}
    assert second == {"appended": False, "evidence_id": record["evidence_id"]}
    assert read_evidence_records(ledger) == [record]


def test_tampered_payload_is_rejected():
    record = _record()
    record["payload"]["close"] = "0"
    with pytest.raises(EvidenceRecordError, match="content_sha256"):
        validate_evidence_record(record)


def test_corrupt_ledger_fails_closed_with_line_number(tmp_path: Path):
    ledger = tmp_path / "evidence.jsonl"
    ledger.write_text("{}\n", encoding="utf-8")
    with pytest.raises(EvidenceRecordError, match="line 1"):
        read_evidence_records(ledger)


def test_duplicate_lines_are_deduplicated_on_read(tmp_path: Path):
    ledger = tmp_path / "evidence.jsonl"
    line = json.dumps(_record())
    ledger.write_text(line + "\n" + line + "\n", encoding="utf-8")
    assert len(read_evidence_records(ledger)) == 1


def test_missing_ledger_returns_empty(tmp_path: Path):
    assert read_evidence_records(tmp_path / "missing.jsonl") == []


def test_record_size_is_bounded():
    with pytest.raises(EvidenceRecordError, match="exceed"):
        _record(payload={"large": "x" * 1_000_010})


def test_optional_fields_are_bounded_and_typed():
    with pytest.raises(EvidenceRecordError, match="query"):
        _record(query="q" * 4_001)
    with pytest.raises(EvidenceRecordError, match="metadata"):
        _record(metadata=[])
