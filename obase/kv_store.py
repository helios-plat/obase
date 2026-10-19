"""持久化键值存储引擎 (3O 范式 Phase 1) — SQLite 后端.

自动建表 + 原子化 KV 读写 (INSERT OR REPLACE)。
"""

from __future__ import annotations

import asyncio
import json

import aiosqlite

from obase.contracts import IKV_Store


class SQLiteKVStore(IKV_Store):
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _init_db(self):
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kv_store (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                await db.commit()
            self._initialized = True

    async def put(self, key: str, value: dict) -> None:
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
            await db.commit()

    async def get(self, key: str) -> dict | None:
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT value FROM kv_store WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row[0])
                return None

    async def list_prefix(self, prefix: str) -> list[dict]:
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT value FROM kv_store WHERE key LIKE ?", (f"{prefix}%",)
            ) as cursor:
                rows = await cursor.fetchall()
                return [json.loads(row[0]) for row in rows]
