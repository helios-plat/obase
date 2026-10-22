"""Append-only, content-addressed evidence records for auditable research.

This module owns evidence serialization and persistence only. It deliberately
uses the standard library and does not import higher 3O layers.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_MAX_RECORD_BYTES = 1_000_000
_SECRET_QUERY_KEYS = {
    "access_token", "api_key", "apikey", "auth", "authorization", "password",
    "secret", "signature", "token",
}
_REQUIRED_FIELDS = {
    "schema_version", "evidence_id", "source_type", "source_uri",
    "retrieved_at_utc", "content_sha256", "payload", "metadata",
}


class EvidenceRecordError(ValueError):
    """Evidence is malformed, too large, unsafe, or cannot be verified."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceRecordError(f"value is not strict JSON: {exc}") from exc


def _utc_timestamp(value: str | datetime) -> str:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceRecordError("retrieved_at must be an ISO-8601 timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise EvidenceRecordError("retrieved_at must be a string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceRecordError("retrieved_at must include an explicit timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_source_uri(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceRecordError("source_uri is required")
    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"https", "http", "file", "artifact", "local"}:
        raise EvidenceRecordError("source_uri scheme must be http, https, file, artifact, or local")
    if scheme in {"http", "https"}:
        if not parts.hostname or parts.username is not None or parts.password is not None:
            raise EvidenceRecordError("source_uri must have a host and contain no user credentials")
        try:
            port = parts.port
        except ValueError as exc:
            raise EvidenceRecordError("source_uri has an invalid port") from exc
        host = parts.hostname.lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            host = f"{host}:{port}"
        for key, _ in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in _SECRET_QUERY_KEYS:
                raise EvidenceRecordError(f"source_uri contains a credential query parameter: {key}")
        query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
        return urlunsplit((scheme, host, parts.path or "/", query, ""))
    if parts.netloc and "@" in parts.netloc:
        raise EvidenceRecordError("source_uri must not contain credentials")
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, ""))


def build_evidence_record(
    *,
    source_type: str,
    source_uri: str,
    retrieved_at: str | datetime,
    payload: Any,
    query: str | None = None,
    tool_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic evidence record from a bounded, curated payload.

    Payloads are data-plane artifacts; callers should avoid passing credentials
    or unnecessary personal data. Identical content at the same canonical URI
    receives the same evidence ID regardless of retrieval time.
    """
    if not isinstance(source_type, str) or not source_type.strip() or len(source_type) > 80:
        raise EvidenceRecordError("source_type must be a non-empty string of at most 80 characters")
    if query is not None and (not isinstance(query, str) or len(query) > 4_000):
        raise EvidenceRecordError("query must be a string of at most 4000 characters")
    if tool_name is not None and (not isinstance(tool_name, str) or len(tool_name) > 160):
        raise EvidenceRecordError("tool_name must be a string of at most 160 characters")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise EvidenceRecordError("metadata must be a JSON object")
    canonical_payload = _canonical_json(payload)
    canonical_metadata = _canonical_json(metadata)
    if len(canonical_payload.encode("utf-8")) + len(canonical_metadata.encode("utf-8")) > _MAX_RECORD_BYTES:
        raise EvidenceRecordError(f"payload and metadata exceed {_MAX_RECORD_BYTES} bytes")
    source = _canonical_source_uri(source_uri)
    payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    identity = _canonical_json({"source_type": source_type.strip(), "source_uri": source, "content_sha256": payload_hash})
    evidence_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "source_type": source_type.strip(),
        "source_uri": source,
        "retrieved_at_utc": _utc_timestamp(retrieved_at),
        "content_sha256": payload_hash,
        "payload": json.loads(canonical_payload),
        "metadata": json.loads(canonical_metadata),
        "query": query,
        "tool_name": tool_name,
    }


def validate_evidence_record(record: Any) -> dict[str, Any]:
    """Verify a decoded record's required fields, payload digest and identity."""
    if not isinstance(record, dict) or not _REQUIRED_FIELDS.issubset(record):
        raise EvidenceRecordError("record is missing required evidence fields")
    rebuilt = build_evidence_record(
        source_type=record["source_type"], source_uri=record["source_uri"],
        retrieved_at=record["retrieved_at_utc"], payload=record["payload"],
        query=record.get("query"), tool_name=record.get("tool_name"),
        metadata=record["metadata"],
    )
    for field in ("schema_version", "source_uri", "content_sha256", "evidence_id"):
        if record[field] != rebuilt[field]:
            raise EvidenceRecordError(f"record integrity check failed for {field}")
    return record


def read_evidence_records(path: str | Path) -> list[dict[str, Any]]:
    """Read and verify each JSONL record; corruption fails closed with a line number."""
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    with ledger_path.open("r", encoding="utf-8") as stream:
        for line_no, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            try:
                record = validate_evidence_record(json.loads(raw))
            except (json.JSONDecodeError, EvidenceRecordError) as exc:
                raise EvidenceRecordError(f"invalid ledger record at line {line_no}: {exc}") from exc
            if record["evidence_id"] in seen:
                continue
            seen.add(record["evidence_id"])
            records.append(record)
    return records


def append_evidence_record(path: str | Path, record: dict[str, Any]) -> dict[str, Any]:
    """Append a verified record once, serializing concurrent writers on POSIX."""
    verified = validate_evidence_record(record)
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = _canonical_json(verified)
    with ledger_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        existing: set[str] = set()
        for line_no, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            try:
                parsed = validate_evidence_record(json.loads(raw))
            except (json.JSONDecodeError, EvidenceRecordError) as exc:
                raise EvidenceRecordError(f"invalid ledger record at line {line_no}: {exc}") from exc
            existing.add(parsed["evidence_id"])
        if verified["evidence_id"] in existing:
            return {"appended": False, "evidence_id": verified["evidence_id"]}
        stream.seek(0, 2)
        stream.write(serialized + "\n")
        stream.flush()
        return {"appended": True, "evidence_id": verified["evidence_id"]}
