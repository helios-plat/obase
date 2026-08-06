"""obase.vector_memory — AutoAgent-style memory (SQLite + BM25-style retrieval).

A dependency-light vector memory: documents (queries + results, code snippets,
tool outputs) are stored in SQLite; retrieval ranks by token-overlap scoring
(BM25-style, no external deps).  An optional ``embed_fn`` may be supplied for
true cosine-similarity retrieval — when absent the deterministic ranker runs,
so the memory is always usable offline/CI.

3O element: ``obase.vector_memory`` (``VectorMemory`` class).
"""

from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fff]+")


class VectorMemory:
    """SQLite-backed memory with BM25-style retrieval.

    Usage::

        mem = VectorMemory()
        mem.add_query("how to parse AST", "use tree_sitter")
        hits = mem.query(["parse AST"])
    """

    def __init__(self, base_dir: str | Path | None = None, embed_fn: Callable | None = None) -> None:
        self._base = Path(base_dir) if base_dir else Path.home() / ".veya" / "memory"
        self._base.mkdir(parents=True, exist_ok=True)
        self._db = self._base / "memory.db"
        self._embed_fn = embed_fn
        self._conn = sqlite3.connect(str(self._db), check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL DEFAULT 'default',
                query TEXT NOT NULL,
                result TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (strftime('%s','now'))
            )"""
        )
        self._conn.commit()

    # -- writes ------------------------------------------------------------
    def add(self, query: str, result: str, collection: str = "default", metadata: dict | None = None) -> int:
        """Insert one (query, result) memory entry; returns the record id."""
        import json

        cur = self._conn.execute(
            "INSERT INTO memory (collection, query, result, metadata) VALUES (?, ?, ?, ?)",
            (collection, query, result, json.dumps(metadata or {}, ensure_ascii=False)),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    # AutoAgent-compatible alias
    def add_query(self, query: str, result: str, collection: str = "default", metadata: dict | None = None) -> int:
        return self.add(query, result, collection, metadata)

    # -- retrieval ---------------------------------------------------------
    def query(self, query_texts: list[str], collection: str | None = None, n_results: int = 5) -> list[dict[str, Any]]:
        """Retrieve the top-n most relevant memories (deterministic offline)."""
        rows = self._conn.execute(
            "SELECT id, collection, query, result, metadata FROM memory"
            + (" WHERE collection = ?" if collection else "")
            + " ORDER BY id DESC LIMIT 1000",
            (collection,) if collection else (),
        ).fetchall()
        candidates = [
            {"id": r[0], "collection": r[1], "query": r[2], "result": r[3], "metadata": r[4]}
            for r in rows
        ]
        if not candidates:
            return []

        # true embedding path when available
        if self._embed_fn is not None:
            return self._rank_embeddings(query_texts, candidates, n_results)

        scores = []
        query_terms = _terms(" ".join(query_texts))
        for c in candidates:
            doc_terms = _terms(c["query"] + " " + c["result"])
            scores.append((c, _bm25_score(query_terms, doc_terms, len(candidates), _df(candidates, query_terms))))
        scores.sort(key=lambda kv: -kv[1])
        return [c for c, _ in scores[:n_results] if _ > 0] or candidates[:n_results]

    def _rank_embeddings(self, query_texts: list[str], candidates: list[dict], n_results: int) -> list[dict]:
        qvec = self._embed_fn(" ".join(query_texts))
        scored = []
        for c in candidates:
            dvec = self._embed_fn(c["query"] + " " + c["result"])
            scored.append((c, _cosine(qvec, dvec)))
        scored.sort(key=lambda kv: -kv[1])
        return [c for c, _ in scored[:n_results]]

    # -- lifecycle ---------------------------------------------------------
    def peek(self, collection: str | None = None, n: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, collection, query, result FROM memory"
            + (" WHERE collection = ?" if collection else "")
            + " ORDER BY id DESC LIMIT ?",
            (collection, n) if collection else (n,),
        ).fetchall()
        return [{"id": r[0], "collection": r[1], "query": r[2], "result": r[3]} for r in rows]

    def count(self, collection: str | None = None) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM memory" + (" WHERE collection = ?" if collection else ""),
            (collection,) if collection else (),
        ).fetchone()
        return row[0] if row else 0

    def delete(self, record_id: int | None = None, collection: str | None = None) -> None:
        if record_id is not None:
            self._conn.execute("DELETE FROM memory WHERE id = ?", (record_id,))
        elif collection is not None:
            self._conn.execute("DELETE FROM memory WHERE collection = ?", (collection,))
        else:
            self._conn.execute("DELETE FROM memory")
        self._conn.commit()

    def reset(self) -> None:
        self.delete()


# ---------------------------------------------------------------------------
# deterministic BM25-style scoring (no external deps)
# ---------------------------------------------------------------------------


def _terms(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _df(candidates: list[dict], terms: list[str]) -> dict[str, int]:
    df: dict[str, int] = {}
    for c in candidates:
        seen = set(_terms(c["query"] + " " + c["result"]))
        for t in terms:
            if t in seen:
                df[t] = df.get(t, 0) + 1
    return df


def _bm25_score(query_terms: list[str], doc_terms: list[str], n_docs: int, df: dict[str, int]) -> float:
    if not doc_terms:
        return 0.0
    k1, b = 1.5, 0.75
    dl = len(doc_terms)
    avgdl = max(1.0, dl)
    score = 0.0
    from collections import Counter

    freq = Counter(doc_terms)
    for t in set(query_terms):
        f = freq.get(t, 0)
        if f == 0:
            continue
        n_t = df.get(t, 1)
        idf = math.log(1 + (n_docs - n_t + 0.5) / (n_t + 0.5))
        score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
    return score


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
