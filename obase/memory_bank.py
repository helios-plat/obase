"""3O 范式内化 — ReasoningBank 记忆库 (obase 基础设施).

经验三元组 (失败尝试 + 成功策略) 存 SQLite; 关键词 + 余弦向量双路检索。
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass, field
from typing import Any

import aiosqlite


@dataclass
class MemoryItem:
    """ReasoningBank 经验三元组 (与规范数据契约一致)。"""

    memory_id: str
    context_description: str
    failed_attempt: dict[str, str]
    successful_strategy: dict[str, str]
    context_vector: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "context_vector": self.context_vector,
            "context_description": self.context_description,
            "failed_attempt": self.failed_attempt,
            "successful_strategy": self.successful_strategy,
        }


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """纯 Python 余弦相似度 (零依赖)。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _keyword_score(signature: str, item: MemoryItem) -> float:
    """错误签名关键词命中打分 (0..N)。"""
    sig_words = set(w.lower() for w in signature.split() if len(w) > 2)
    if not sig_words:
        return 0.0
    haystack = (
        item.context_description
        + " "
        + item.failed_attempt.get("reason", "")
        + " "
        + item.successful_strategy.get("reason", "")
    ).lower()
    return sum(1 for w in sig_words if w in haystack)


class MemoryBank:
    """SQLite 持久化经验记忆库 (aiosqlite)。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def _init_db(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_items (
                        memory_id TEXT PRIMARY KEY,
                        context_vector TEXT NOT NULL DEFAULT '[]',
                        context_description TEXT NOT NULL,
                        failed_attempt TEXT NOT NULL,
                        successful_strategy TEXT NOT NULL
                    )
                    """
                )
                await db.commit()
            self._initialized = True

    async def add(self, item: MemoryItem) -> None:
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO memory_items VALUES (?, ?, ?, ?, ?)",
                (
                    item.memory_id,
                    json.dumps(item.context_vector),
                    item.context_description,
                    json.dumps(item.failed_attempt),
                    json.dumps(item.successful_strategy),
                ),
            )
            await db.commit()

    async def search_experience(
        self, error_signature: str, *, top_k: int = 3, query_vector: list[float] | None = None
    ) -> list[MemoryItem]:
        """双路检索: 关键词命中 + 可选向量余弦。"""
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM memory_items") as cursor:
                rows = await cursor.fetchall()
        items = [self._row_to_item(r) for r in rows]
        scored: list[tuple[float, MemoryItem]] = []
        for item in items:
            score = float(_keyword_score(error_signature, item))
            if query_vector:
                score += 0.5 * cosine_similarity(query_vector, item.context_vector)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    async def list_all(self) -> list[MemoryItem]:
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT * FROM memory_items") as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_item(r) for r in rows]

    async def delete(self, memory_id: str) -> bool:
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM memory_items WHERE memory_id = ?", (memory_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def count(self) -> int:
        return len(await self.list_all())

    @staticmethod
    def _row_to_item(row: tuple) -> MemoryItem:
        return MemoryItem(
            memory_id=row[0],
            context_vector=json.loads(row[1] or "[]"),
            context_description=row[2],
            failed_attempt=json.loads(row[3]),
            successful_strategy=json.loads(row[4]),
        )
