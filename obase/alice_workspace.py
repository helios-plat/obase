"""Durable research-workspace artifacts with Git provenance.

This module intentionally stores user-authored material as ordinary files and an
append-only JSONL manifest. It never initializes Git, commits, pushes, or executes
research agents on the caller's behalf.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

_SCHEMA_VERSION = 1
_WORKSPACE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_RESERVED_TOP_LEVEL = {".git", ".alice"}


class WorkspaceError(ValueError):
    """Invalid workspace metadata or an unsafe artifact path."""


def _utc_iso(value: datetime | None = None) -> str:
    moment = value or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise WorkspaceError("timestamps must include a timezone")
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _git_head(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", value) else None


class ResearchWorkspace:
    """Filesystem-backed research workspace with content hashes and commit lineage."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.state_dir = self.root / ".alice"
        self.metadata_path = self.state_dir / "workspace.json"
        self.artifact_log = self.state_dir / "artifacts.jsonl"

    def initialize(self, workspace_id: str, title: str, *, created_at: datetime | None = None) -> dict[str, Any]:
        workspace_id = workspace_id.strip() if isinstance(workspace_id, str) else ""
        title = title.strip() if isinstance(title, str) else ""
        if not _WORKSPACE_ID.fullmatch(workspace_id):
            raise WorkspaceError("workspace_id must be a lowercase path-safe slug")
        if not title or len(title) > 200:
            raise WorkspaceError("title must contain 1..200 characters")
        if self.state_dir.is_symlink() or not self.state_dir.resolve().is_relative_to(self.root):
            raise WorkspaceError("workspace state directory escapes the workspace root")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.metadata_path.is_symlink():
            raise WorkspaceError("workspace metadata must not be a symbolic link")
        if self.metadata_path.exists():
            try:
                existing = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkspaceError("existing workspace metadata is unreadable") from exc
            if existing.get("workspace_id") != workspace_id:
                raise WorkspaceError("workspace already initialized with a different id")
            if existing.get("title") != title:
                raise WorkspaceError("workspace title is immutable after initialization")
            return existing
        metadata = {
            "schema_version": _SCHEMA_VERSION,
            "workspace_id": workspace_id,
            "title": title,
            "created_at": _utc_iso(created_at),
        }
        _atomic_write(self.metadata_path, (_canonical_json(metadata) + "\n").encode("utf-8"))
        return metadata

    def save_document(
        self,
        relative_path: str,
        title: str,
        content: str,
        *,
        kind: str = "report",
        source_refs: tuple[str, ...] | list[str] = (),
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically persist a document and append verifiable manifest metadata."""
        if not self.metadata_path.is_file():
            raise WorkspaceError("initialize the research workspace before saving documents")
        if not isinstance(relative_path, str) or "\\" in relative_path or "\x00" in relative_path:
            raise WorkspaceError("artifact path must be a relative POSIX path")
        requested = PurePosixPath(relative_path)
        if requested.is_absolute() or not requested.parts or any(part in {"", ".", ".."} for part in requested.parts):
            raise WorkspaceError("artifact path must not be absolute or traverse parent directories")
        if requested.parts[0] in _RESERVED_TOP_LEVEL:
            raise WorkspaceError("artifact path uses a reserved workspace directory")
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise WorkspaceError("artifact title must contain 1..300 characters")
        if not isinstance(content, str):
            raise WorkspaceError("artifact content must be text")
        if len(content.encode("utf-8")) > 8 * 1024 * 1024:
            raise WorkspaceError("artifact exceeds the 8 MiB safety limit")
        if not isinstance(kind, str) or not kind.strip() or len(kind) > 40:
            raise WorkspaceError("artifact kind must be a short non-empty string")
        refs = list(source_refs)
        if any(not isinstance(ref, str) or not ref.strip() or len(ref) > 2000 for ref in refs):
            raise WorkspaceError("source_refs must contain non-empty strings up to 2000 characters")

        destination = self.root.joinpath(*requested.parts).resolve()
        if not destination.is_relative_to(self.root):
            raise WorkspaceError("artifact path escapes the workspace root")
        if destination == self.root or destination in {self.metadata_path.resolve(), self.artifact_log.resolve()}:
            raise WorkspaceError("artifact path collides with workspace metadata")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = destination.resolve()
        if not destination.is_relative_to(self.root) or destination.is_symlink():
            raise WorkspaceError("artifact path changed to an unsafe location")

        encoded = content.encode("utf-8")
        _atomic_write(destination, encoded)
        record: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "workspace_id": json.loads(self.metadata_path.read_text(encoding="utf-8"))["workspace_id"],
            "artifact_path": destination.relative_to(self.root).as_posix(),
            "title": title.strip(),
            "kind": kind.strip(),
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "source_refs": refs,
            "created_at": _utc_iso(created_at),
            "git_head": _git_head(self.root),
        }
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.artifact_log.is_symlink() or not self.artifact_log.resolve().is_relative_to(self.root):
            raise WorkspaceError("artifact manifest path escapes the workspace root")
        with self.artifact_log.open("ab") as stream:
            stream.write((_canonical_json(record) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        return record

    def list_artifacts(self) -> list[dict[str, Any]]:
        if not self.artifact_log.exists():
            return []
        if self.artifact_log.is_symlink() or not self.artifact_log.resolve().is_relative_to(self.root):
            raise WorkspaceError("artifact manifest path escapes the workspace root")
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.artifact_log.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WorkspaceError(f"invalid artifact manifest line {line_number}") from exc
            if record.get("schema_version") != _SCHEMA_VERSION or record.get("workspace_id") is None:
                raise WorkspaceError(f"unsupported artifact manifest record at line {line_number}")
            records.append(record)
        return records
