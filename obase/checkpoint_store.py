"""obase.checkpoint_store — SQLite WAL-backed durable checkpoint store.

Each checkpoint is a JSON snapshot keyed by session id.  SQLite's WAL journal
mode ensures atomic commits and concurrent reads during writes.  A crashed /
restarted agent can hydrate (restore) its full memory context from the store.

3O element: ``obase.checkpoint_store`` (``CheckpointStore`` class).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class CheckpointStore:
    """SQLite-backed checkpoint store with WAL mode for crash-safe persistence.

    Usage::

        store = CheckpointStore()
        store.save("session:abc", {"turns_done": 3, "goal": "..."})
        state = store.load("session:abc")  # resume after crash
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir else (Path.home() / ".veya" / "checkpoints")
        self._base.mkdir(parents=True, exist_ok=True)
        self._db_path = self._base / "checkpoints.db"
        self._init_db()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def save(self, key: str, state: dict[str, Any]) -> str:
        """Persist a snapshot. Returns the key."""
        safe = self._safe(key)
        payload = json.dumps(state, ensure_ascii=False, default=str)
        compressed = _compress(payload)
        row = _select_one(self._conn(), "SELECT key FROM checkpoints WHERE key = ?", (safe,))
        if row:
            self._conn().execute(
                "UPDATE checkpoints SET payload = ?, updated_at = strftime('%s','now') WHERE key = ?",
                (compressed, safe),
            )
        else:
            self._conn().execute(
                "INSERT INTO checkpoints (key, payload) VALUES (?, ?)",
                (safe, compressed),
            )
        self._conn().commit()
        return key

    def load(self, key: str) -> dict[str, Any] | None:
        """Load a checkpoint snapshot, or None if not found."""
        row = _select_one(self._conn(), "SELECT payload FROM checkpoints WHERE key = ?", (self._safe(key),))
        if row is None:
            return None
        try:
            return json.loads(_decompress(row[0]))
        except (json.JSONDecodeError, Exception):
            return None

    def keys(self) -> list[str]:
        """List all stored checkpoint keys."""
        rows = self._conn().execute("SELECT key FROM checkpoints").fetchall()
        return sorted(r[0] for r in rows)

    def reset(self, key: str | None = None) -> None:
        """Delete one or all checkpoints."""
        if key is None:
            self._conn().execute("DELETE FROM checkpoints")
        else:
            self._conn().execute("DELETE FROM checkpoints WHERE key = ?", (self._safe(key),))
        self._conn().commit()

    def count(self) -> int:
        """Number of stored snapshots."""
        row = self._conn().execute("SELECT COUNT(*) FROM checkpoints").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        c = self._conn()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute(
            """CREATE TABLE IF NOT EXISTS checkpoints (
                key        TEXT PRIMARY KEY,
                payload    BLOB NOT NULL,
                created_at TEXT DEFAULT (strftime('%s','now')),
                updated_at TEXT DEFAULT (strftime('%s','now'))
            )"""
        )
        c.commit()

    def _conn(self) -> sqlite3.Connection:
        try:
            return self.__conn
        except AttributeError:
            self.__conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            return self.__conn

    @staticmethod
    def _safe(key: str) -> str:
        return key.replace("/", "_").replace(":", "_")


# ---------------------------------------------------------------------------
# compression helpers (gzip — deterministic, no extra deps)
# ---------------------------------------------------------------------------


def _compress(payload: str) -> bytes:
    import gzip
    return gzip.compress(payload.encode("utf-8"))


def _decompress(data: bytes) -> str:
    import gzip
    return gzip.decompress(data).decode("utf-8")


def _select_one(conn: sqlite3.Connection, sql: str, params: tuple) -> Any:
    return conn.execute(sql, params).fetchone()
