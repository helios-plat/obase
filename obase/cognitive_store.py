"""obase.cognitive_store — 向量与文本混合存储适配器 (MemoryChunk; PgVector / SQLite).

定义 MemoryChunk 结构，提供两种后端接口：
- PgVectorMemoryStore : pgvector HNSW 近邻检索（经 obase.persistence.vector.vector_search）
- SqliteMemoryStore   : 零依赖 SQLite 落盘（JSON 序列化 embedding，余弦手工计算），
                        用于无 Postgres 的轻量/测试环境

Example:
    >>> store = SqliteMemoryStore("/tmp/mem.db", dim=4)
    >>> await store.upsert(MemoryChunk(chunk_id="c1", content="hello", embedding=[1.0, 0, 0, 0]))
    >>> hits = await store.search([1.0, 0, 0, 0], top_k=5)
    >>> hits[0][0].chunk_id
    'c1'
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "MemoryChunk",
    "MemoryStore",
    "PgVectorMemoryStore",
    "SqliteMemoryStore",
    "make_memory_store",
]


@dataclass
class MemoryChunk:
    """统一记忆块结构：文本 + 可选向量 + 元数据。"""

    chunk_id: str
    content: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    path: str | None = None
    created_at: float = field(default_factory=time.time)


@runtime_checkable
class MemoryStore(Protocol):
    """混合存储协议：upsert / search / delete / get / count。"""

    async def upsert(self, chunk: MemoryChunk) -> None: ...
    async def search(
        self, vector: list[float], *, top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]: ...
    async def delete(self, chunk_id: str) -> bool: ...
    async def get(self, chunk_id: str) -> MemoryChunk | None: ...
    async def count(self) -> int: ...


def _embedding_json(chunk: MemoryChunk) -> str | None:
    return json.dumps(chunk.embedding) if chunk.embedding is not None else None


def _metadata_json(chunk: MemoryChunk) -> str:
    return json.dumps(chunk.metadata, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# PgVector 后端
# ---------------------------------------------------------------------------


class PgVectorMemoryStore:
    """pgvector 后端：表结构由调用方保证（或经 ensure_table 建出）。

    Table schema 约定:
        chunk_id text primary key, content text, embedding vector(dim),
        metadata jsonb, path text, created_at timestamptz default now()
    """

    def __init__(
        self,
        pool: Any,
        *,
        table: str = "memory_chunk",
        vector_column: str = "embedding",
        dim: int = 1536,
    ) -> None:
        self.pool = pool
        self.table = table
        self.vector_column = vector_column
        self.dim = dim

    async def upsert(self, chunk: MemoryChunk) -> None:
        from obase.persistence import transaction

        vec = chunk.embedding
        if vec is not None and len(vec) != self.dim:
            raise ValueError(f"embedding dim {len(vec)} != configured {self.dim}")
        vec_sql = _fmt_vec(vec) if vec else "NULL"
        async with transaction(self.pool) as tx:
            await tx.execute(
                f"""
                INSERT INTO "{self.table}"
                (chunk_id, content, {self.vector_column}, metadata, path, created_at)
                VALUES ($1, $2, {vec_sql}, $3::jsonb, $4, NOW())
                ON CONFLICT (chunk_id) DO UPDATE SET
                    content = EXCLUDED.content,
                    {self.vector_column} = EXCLUDED.{self.vector_column},
                    metadata = EXCLUDED.metadata,
                    path = EXCLUDED.path
                """,
                chunk.chunk_id,
                chunk.content,
                _metadata_json(chunk),
                chunk.path,
            )

    async def search(
        self, vector: list[float], *, top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]:
        from obase.persistence import vector_search

        if len(vector) != self.dim:
            raise ValueError(f"query dim {len(vector)} != configured {self.dim}")
        rows = await vector_search(
            pool=self.pool,
            table=self.table,
            vector_column=self.vector_column,
            query_vector=vector,
            metric="cosine",
            top_k=top_k,
        )
        out: list[tuple[MemoryChunk, float]] = []
        for r in rows:
            meta = r.get("metadata")
            out.append(
                (
                    MemoryChunk(
                        chunk_id=r["chunk_id"],
                        content=r.get("content", ""),
                        metadata=meta if isinstance(meta, dict) else {},
                        path=r.get("path"),
                    ),
                    float(r.get("distance", 0.0)),
                )
            )
        return out

    async def delete(self, chunk_id: str) -> bool:
        from obase.persistence import transaction

        async with transaction(self.pool) as tx:
            res = await tx.execute(
                f'DELETE FROM "{self.table}" WHERE chunk_id = $1', chunk_id
            )
        return bool(res)

    async def get(self, chunk_id: str) -> MemoryChunk | None:
        from obase.persistence import transaction

        async with transaction(self.pool) as tx:
            row = await tx.fetchrow(
                f'SELECT * FROM "{self.table}" WHERE chunk_id = $1', chunk_id
            )
        if row is None:
            return None
        return MemoryChunk(
            chunk_id=row["chunk_id"],
            content=row.get("content", ""),
            metadata=row.get("metadata") or {},
            path=row.get("path"),
        )

    async def count(self) -> int:
        from obase.persistence import transaction

        async with transaction(self.pool) as tx:
            row = await tx.fetchrow(f'SELECT COUNT(*) AS n FROM "{self.table}"')
        return int(row["n"]) if row else 0


def _fmt_vec(v: list[float]) -> str:
    return "[" + ",".join(str(x) for x in v) + "]::vector"


# ---------------------------------------------------------------------------
# SQLite 后端（零依赖 fallback）
# ---------------------------------------------------------------------------


class SqliteMemoryStore:
    """SQLite 后端：embedding 以 JSON 文本存储，余弦距离手工计算。

    用于轻量部署 / 测试 / 无 Postgres 环境。线程安全：每操作独立连接。
    """

    def __init__(self, db_path: str | Path, *, dim: int = 1536) -> None:
        self.db_path = Path(db_path)
        self.dim = dim
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_chunk (
                    chunk_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    path TEXT,
                    created_at REAL NOT NULL
                )
                """
            )

    async def upsert(self, chunk: MemoryChunk) -> None:
        if chunk.embedding is not None and len(chunk.embedding) != self.dim:
            raise ValueError(f"embedding dim {len(chunk.embedding)} != configured {self.dim}")
        await asyncio.to_thread(self._upsert_sync, chunk)

    def _upsert_sync(self, chunk: MemoryChunk) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_chunk (chunk_id, content, embedding, metadata, path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    content = excluded.content,
                    embedding = excluded.embedding,
                    metadata = excluded.metadata,
                    path = excluded.path
                """,
                (
                    chunk.chunk_id,
                    chunk.content,
                    _embedding_json(chunk),
                    _metadata_json(chunk),
                    chunk.path,
                    chunk.created_at,
                ),
            )

    async def search(
        self, vector: list[float], *, top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]:
        if len(vector) != self.dim:
            raise ValueError(f"query dim {len(vector)} != configured {self.dim}")
        return await asyncio.to_thread(self._search_sync, vector, top_k)

    def _search_sync(
        self, vector: list[float], top_k: int
    ) -> list[tuple[MemoryChunk, float]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_chunk WHERE embedding IS NOT NULL"
            ).fetchall()
        scored: list[tuple[MemoryChunk, float]] = []
        for row in rows:
            emb = json.loads(row["embedding"])
            dist = _cosine_distance(vector, emb)
            scored.append(
                (
                    MemoryChunk(
                        chunk_id=row["chunk_id"],
                        content=row["content"],
                        embedding=emb,
                        metadata=json.loads(row["metadata"]),
                        path=row["path"],
                        created_at=row["created_at"],
                    ),
                    dist,
                )
            )
        scored.sort(key=lambda t: t[1])
        return scored[:top_k]

    async def delete(self, chunk_id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, chunk_id)

    def _delete_sync(self, chunk_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM memory_chunk WHERE chunk_id = ?", (chunk_id,)
            )
            return cur.rowcount > 0

    async def get(self, chunk_id: str) -> MemoryChunk | None:
        return await asyncio.to_thread(self._get_sync, chunk_id)

    def _get_sync(self, chunk_id: str) -> MemoryChunk | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_chunk WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
        if row is None:
            return None
        return MemoryChunk(
            chunk_id=row["chunk_id"],
            content=row["content"],
            embedding=json.loads(row["embedding"]) if row["embedding"] else None,
            metadata=json.loads(row["metadata"]),
            path=row["path"],
            created_at=row["created_at"],
        )

    async def count(self) -> int:
        return await asyncio.to_thread(self._count_sync)

    def _count_sync(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM memory_chunk").fetchone()
        return int(row["n"])


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """1 - cos(a,b)；零向量按最远距离处理。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


async def make_memory_store(kind: str, **kwargs: Any) -> MemoryStore:
    """工厂：kind ∈ {"pgvector", "sqlite"}。"""
    if kind == "pgvector":
        return PgVectorMemoryStore(pool=kwargs["pool"], dim=kwargs.get("dim", 1536))
    if kind == "sqlite":
        return SqliteMemoryStore(db_path=kwargs["db_path"], dim=kwargs.get("dim", 1536))
    raise ValueError(f"unknown memory store kind: {kind!r}")
