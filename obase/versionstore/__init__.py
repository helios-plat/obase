"""obase.versionstore — Agent 快照与配置版本持久化管理存储.

两层能力：
- jsonl_append / jsonl_read / jsonl_latest : JSONL append-only 基础存储
- VersionStore : 目录级快照版本库（snapshot / restore / list / delete）

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from obase.versionstore import jsonl_append, jsonl_read, jsonl_latest, VersionStore
    >>> asyncio.run(jsonl_append(path=Path("log.jsonl"), entry={"id": "a", "v": 1}))
    >>> entries = jsonl_read(path=Path("log.jsonl"))
    >>> latest = jsonl_latest(path=Path("log.jsonl"), by_key="id")
"""

from obase.versionstore._store import jsonl_append, jsonl_latest, jsonl_read
from obase.versionstore.snapshot import SnapshotMeta, VersionStore, VersionStoreError

__all__ = [
    "SnapshotMeta",
    "VersionStore",
    "VersionStoreError",
    "jsonl_append",
    "jsonl_latest",
    "jsonl_read",
]
