from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from obase.fs import FS

log = structlog.get_logger()


class Trail:
    """Append-only structured event log for a single pipeline run."""

    def __init__(self, run_id: str, run_dir: Path | None = None) -> None:
        self.run_id = run_id
        self._dir = run_dir or FS.run_dir(run_id)
        self._path = self._dir / "trail.jsonl"

    def emit(self, event: str, **kwargs: Any) -> None:
        """Append a structured event line. kwargs are flattened into the JSON object."""
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "event": event,
        }
        record.update(kwargs)
        line = json.dumps(record, default=str) + "\n"
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def save_stage_input(self, stage_name: str, data: dict[str, Any]) -> None:
        self.emit("stage_input", stage=stage_name, data=data)

    def save_stage_output(self, stage_name: str, data: dict[str, Any]) -> None:
        self.emit("stage_output", stage=stage_name, data=data)

    def finalize(self, state: str, **kwargs: Any) -> None:
        self.emit("finalize", state=state, **kwargs)

    @property
    def path(self) -> Path:
        return self._path


def load_trail(run_id: str, run_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load all events from a trail file as a list of dicts."""
    d = run_dir or FS.run_dir(run_id)
    path = d / "trail.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("obase.trail.bad_line", run_id=run_id, line=line[:120])
    return records


def query_trail(
    working_dir: Path | None = None,
    event_type: str | None = None,
    run_id_pattern: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
) -> list[dict[str, Any]]:
    """Scan all run trail files and return matching events."""
    base = working_dir or FS.working_dir()
    results: list[dict[str, Any]] = []
    compiled = re.compile(run_id_pattern) if run_id_pattern else None

    for run_dir in base.iterdir():
        if not run_dir.is_dir():
            continue
        trail_file = run_dir / "trail.jsonl"
        if not trail_file.exists():
            continue
        run_id = run_dir.name
        if compiled and not compiled.search(run_id):
            continue
        with trail_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event_type and record.get("event") != event_type:
                    continue
                if after or before:
                    ts_raw = record.get("ts")
                    if ts_raw:
                        try:
                            ts = datetime.fromisoformat(ts_raw)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=UTC)
                        except ValueError:
                            continue
                        if after and ts <= after:
                            continue
                        if before and ts >= before:
                            continue
                results.append(record)

    results.sort(key=lambda r: r.get("ts", ""))
    return results
