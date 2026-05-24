"""JSONL append-only store: append, read, and latest-entry-wins lookup.

Example:
    >>> await jsonl_append(path=Path("log.jsonl"), entry={"id": "x", "status": "done"})
    >>> entries = jsonl_read(path=Path("log.jsonl"))
    >>> latest = jsonl_latest(path=Path("log.jsonl"), by_key="id")

Raises:
    FileNotFoundError: When reading a non-existent file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


async def jsonl_append(
    *,
    path: Path,
    entry: dict[str, Any],
    create_parents: bool = True,
) -> None:
    """Append a single JSON entry to a JSONL file.

    Args:
        path: Target JSONL file (created if missing).
        entry: Dict to serialize as one JSON line.
        create_parents: Create parent directories if missing.

    Example:
        >>> await jsonl_append(path=Path("log.jsonl"), entry={"k": "v"})
    """
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def jsonl_read(
    *,
    path: Path,
    skip_malformed: bool = True,
) -> list[dict[str, Any]]:
    """Read all entries from a JSONL file.

    Args:
        path: JSONL file to read.
        skip_malformed: If True, skip lines that fail JSON parsing.

    Returns:
        List of parsed dicts.

    Raises:
        FileNotFoundError: If path does not exist.

    Example:
        >>> entries = jsonl_read(path=Path("log.jsonl"))
    """
    if not path.exists():
        raise FileNotFoundError(f"JSONL file not found: {path}")

    results: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                if not skip_malformed:
                    raise
    return results


def jsonl_latest(
    *,
    path: Path,
    by_key: str,
) -> dict[str, Any] | None:
    """Get the latest entry by key (last-entry-wins).

    Args:
        path: JSONL file to read.
        by_key: Key field to match — returns the last entry containing this key.

    Returns:
        The last entry with the given key, or None if file is empty/missing.

    Example:
        >>> latest = jsonl_latest(path=Path("log.jsonl"), by_key="id")
    """
    if not path.exists():
        return None

    latest: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if by_key in entry:
                    latest = entry
            except json.JSONDecodeError:
                continue
    return latest
