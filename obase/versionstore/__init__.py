"""obase.versionstore — JSONL append-only version store.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from obase.versionstore import jsonl_append, jsonl_read, jsonl_latest
    >>> asyncio.run(jsonl_append(path=Path("log.jsonl"), entry={"id": "a", "v": 1}))
    >>> entries = jsonl_read(path=Path("log.jsonl"))
    >>> latest = jsonl_latest(path=Path("log.jsonl"), by_key="id")
"""

from obase.versionstore._store import jsonl_append, jsonl_latest, jsonl_read

__all__ = ["jsonl_append", "jsonl_latest", "jsonl_read"]
