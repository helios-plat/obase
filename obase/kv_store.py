"""SQLite-backed implementation of the 3O key/value storage contract."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any


class SQLiteKVStore:
    """Durable JSON KV store with async methods and transactional upserts.

    Connections remain open for the object's lifetime so in-memory databases
    work as expected. Blocking SQLite operations are delegated to a worker
    thread, and a lock serializes operations on the shared connection.
    """

    def __init__(self, database_path: str | Path):
        raw_path = str(database_path)
        if not raw_path.strip():
            raise ValueError("database_path must be a non-empty path")
        if raw_path != ":memory:":
            path = Path(raw_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            raw_path = str(path)
        self.database_path = raw_path
        self._lock = RLock()
        self._connection = sqlite3.connect(
            raw_path, timeout=30.0, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock, self._connection:
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )

    @staticmethod
    def _validate_key(key: str) -> str:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be a non-empty string")
        return key

    @staticmethod
    def _serialize(value: dict[str, Any]) -> str:
        if not isinstance(value, dict):
            raise TypeError("value must be a dictionary")
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, allow_nan=False,
            separators=(",", ":"),
        )

    def _put_sync(self, key: str, encoded: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO kv_store(key, value_json, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET
                     value_json=excluded.value_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (key, encoded),
            )

    async def put(self, key: str, value: dict[str, Any]) -> None:
        """Insert or atomically replace a value."""
        key = self._validate_key(key)
        encoded = self._serialize(value)
        await asyncio.to_thread(self._put_sync, key, encoded)

    def _get_sync(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value_json FROM kv_store WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        decoded = json.loads(row["value_json"])
        if not isinstance(decoded, dict):
            raise ValueError(f"stored value for {key!r} is not a JSON object")
        return decoded

    async def get(self, key: str) -> dict[str, Any] | None:
        """Read a value, returning None for absent keys."""
        key = self._validate_key(key)
        return await asyncio.to_thread(self._get_sync, key)

    def _delete_sync(self, key: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM kv_store WHERE key = ?", (key,)
            )
            return cursor.rowcount > 0

    async def delete(self, key: str) -> bool:
        """Delete a key and return whether a row existed."""
        key = self._validate_key(key)
        return await asyncio.to_thread(self._delete_sync, key)

    def _count_sync(self) -> int:
        with self._lock:
            return int(
                self._connection.execute("SELECT COUNT(*) FROM kv_store").fetchone()[0]
            )

    async def count(self) -> int:
        """Return the number of stored keys."""
        return await asyncio.to_thread(self._count_sync)

    async def close(self) -> None:
        """Close the underlying connection."""
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._lock:
            self._connection.close()

    async def __aenter__(self) -> SQLiteKVStore:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
