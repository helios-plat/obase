"""SQLite-backed asynchronous KV store preserving the legacy 3O API."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from obase.contracts import IKV_Store


class SQLiteKVStore(IKV_Store):
    def __init__(self, db_path: str | Path):
        raw_path = str(db_path)
        if not raw_path.strip():
            raise ValueError("database_path must be a non-empty path")
        if raw_path != ":memory:":
            path = Path(raw_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            raw_path = str(path)
        self.db_path = raw_path
        self.database_path = raw_path
        self._lock = RLock()
        self._connection = sqlite3.connect(raw_path, timeout=30.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self._connection:
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    value_json TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(kv_store)")}
            if "value" not in columns:
                self._connection.execute("ALTER TABLE kv_store ADD COLUMN value TEXT")
            if "value_json" not in columns:
                self._connection.execute("ALTER TABLE kv_store ADD COLUMN value_json TEXT")
            if "updated_at" not in columns:
                self._connection.execute("ALTER TABLE kv_store ADD COLUMN updated_at TEXT")
            self._connection.execute(
                "UPDATE kv_store SET value_json=COALESCE(value_json, value), "
                "value=COALESCE(value, value_json), updated_at=COALESCE(updated_at, CURRENT_TIMESTAMP)"
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
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        key = self._validate_key(key)
        encoded = self._serialize(value)
        def write() -> None:
            with self._lock, self._connection:
                self._connection.execute(
                    """INSERT INTO kv_store(key, value, value_json, updated_at)
                       VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(key) DO UPDATE SET
                         value=excluded.value,
                         value_json=excluded.value_json,
                         updated_at=CURRENT_TIMESTAMP""",
                    (key, encoded, encoded),
                )
        await asyncio.to_thread(write)

    async def get(self, key: str) -> dict[str, Any] | None:
        key = self._validate_key(key)
        def read() -> dict[str, Any] | None:
            with self._lock:
                row = self._connection.execute(
                    "SELECT COALESCE(value_json, value) AS stored_value FROM kv_store WHERE key=?",
                    (key,),
                ).fetchone()
            if row is None or row["stored_value"] is None:
                return None
            result = json.loads(row["stored_value"])
            if not isinstance(result, dict):
                raise ValueError(f"stored value for {key!r} is not a JSON object")
            return result
        return await asyncio.to_thread(read)

    async def list_prefix(self, prefix: str) -> list[dict]:
        if not isinstance(prefix, str):
            raise TypeError("prefix must be a string")
        def read() -> list[dict]:
            with self._lock:
                rows = self._connection.execute(
                    "SELECT COALESCE(value_json, value) AS stored_value FROM kv_store WHERE key LIKE ? ORDER BY key",
                    (f"{prefix}%",),
                ).fetchall()
            return [json.loads(row["stored_value"]) for row in rows if row["stored_value"] is not None]
        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> bool:
        key = self._validate_key(key)
        def remove() -> bool:
            with self._lock, self._connection:
                cur = self._connection.execute("DELETE FROM kv_store WHERE key=?", (key,))
                return cur.rowcount > 0
        return await asyncio.to_thread(remove)

    async def count(self) -> int:
        def read() -> int:
            with self._lock:
                return int(self._connection.execute("SELECT COUNT(*) FROM kv_store").fetchone()[0])
        return await asyncio.to_thread(read)

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._lock:
            self._connection.close()

    async def __aenter__(self) -> "SQLiteKVStore":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
