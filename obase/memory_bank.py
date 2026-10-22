"""Small SQLite-backed experience memory store used by service adapters.

The async interface intentionally uses only the Python standard library so
obase does not acquire a second storage-framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Mapping


@dataclass(slots=True)
class MemoryItem:
    """A reusable experience with its failed attempt and successful strategy."""

    memory_id: str
    context_description: str
    failed_attempt: dict[str, str] = field(default_factory=dict)
    successful_strategy: dict[str, str] = field(default_factory=dict)
    context_vector: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.memory_id, str) or not self.memory_id.strip():
            raise ValueError("memory_id must be a non-empty string")
        if not isinstance(self.context_description, str) or not self.context_description.strip():
            raise ValueError("context_description must be a non-empty string")
        self.failed_attempt = self._string_mapping(self.failed_attempt, "failed_attempt")
        self.successful_strategy = self._string_mapping(
            self.successful_strategy, "successful_strategy"
        )
        try:
            vector = [float(value) for value in self.context_vector]
        except (TypeError, ValueError) as exc:
            raise ValueError("context_vector must contain only finite numbers") from exc
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("context_vector must contain only finite numbers")
        self.context_vector = vector

    @staticmethod
    def _string_mapping(value: Mapping[str, str], field_name: str) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{field_name} must be a mapping of strings")
        if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
            raise ValueError(f"{field_name} must contain only string keys and values")
        return dict(value)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible value without exposing mutable internals."""
        return {
            "memory_id": self.memory_id,
            "context_description": self.context_description,
            "failed_attempt": dict(self.failed_attempt),
            "successful_strategy": dict(self.successful_strategy),
            "context_vector": list(self.context_vector),
        }


class MemoryBank:
    """Durable CRUD and lexical retrieval for experience memories.

    Each record is stored transactionally in SQLite. Re-adding the same
    ``memory_id`` updates that record rather than creating a duplicate.
    """

    def __init__(self, path: str | Path):
        raw_path = str(path)
        if not raw_path.strip():
            raise ValueError("database path must be non-empty")
        if raw_path != ":memory:":
            Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.path = raw_path if raw_path == ":memory:" else str(Path(raw_path).expanduser())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = self.path
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self._connection:
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS experience_memories (
                    memory_id TEXT PRIMARY KEY,
                    context_description TEXT NOT NULL,
                    failed_attempt_json TEXT NOT NULL,
                    successful_strategy_json TEXT NOT NULL,
                    context_vector_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_experience_memories_created "
                "ON experience_memories(created_at, memory_id)"
            )
            # One-way idempotent migration from the old memory_items table.
            tables = {r[0] for r in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "memory_items" in tables:
                legacy_cols = {r["name"] for r in self._connection.execute("PRAGMA table_info(memory_items)")}
                if {"memory_id", "context_description", "failed_attempt", "successful_strategy"} <= legacy_cols:
                    vector_expr = "context_vector" if "context_vector" in legacy_cols else "'[]'"
                    for row in self._connection.execute(
                        "SELECT memory_id, context_description, failed_attempt, successful_strategy, "
                        + vector_expr + " AS context_vector FROM memory_items"
                    ):
                        now = self._now()
                        self._connection.execute(
                            """INSERT OR IGNORE INTO experience_memories
                               (memory_id, context_description, failed_attempt_json,
                                successful_strategy_json, context_vector_json, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (row["memory_id"], row["context_description"], row["failed_attempt"],
                             row["successful_strategy"], row["context_vector"], now, now),
                        )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="microseconds")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            memory_id=row["memory_id"],
            context_description=row["context_description"],
            failed_attempt=json.loads(row["failed_attempt_json"]),
            successful_strategy=json.loads(row["successful_strategy_json"]),
            context_vector=json.loads(row["context_vector_json"]),
        )

    async def add(self, item: MemoryItem) -> None:
        """Insert or update one validated memory record."""
        if not isinstance(item, MemoryItem):
            raise TypeError("item must be a MemoryItem")
        now = self._now()
        values = (
            item.memory_id,
            item.context_description,
            self._json(item.failed_attempt),
            self._json(item.successful_strategy),
            self._json(item.context_vector),
            now,
            now,
        )
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO experience_memories (
                    memory_id, context_description, failed_attempt_json,
                    successful_strategy_json, context_vector_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    context_description=excluded.context_description,
                    failed_attempt_json=excluded.failed_attempt_json,
                    successful_strategy_json=excluded.successful_strategy_json,
                    context_vector_json=excluded.context_vector_json,
                    updated_at=excluded.updated_at""",
                values,
            )

    async def search_experience(
        self, error_signature: str, *, top_k: int = 3, query_vector: list[float] | None = None
    ) -> list[MemoryItem]:
        """Return highest-overlap memories, breaking ties deterministically."""
        if not isinstance(error_signature, str):
            raise TypeError("error_signature must be a string")
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise TypeError("top_k must be an integer")
        if top_k <= 0:
            return []
        query_terms = set(re.findall(r"[^\W_]+", error_signature.casefold(), flags=re.UNICODE))
        normalized_query = " ".join(error_signature.casefold().split())
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM experience_memories ORDER BY created_at, memory_id"
            ).fetchall()
        scored: list[tuple[float, str, str, MemoryItem]] = []
        for row in rows:
            item = self._from_row(row)
            searchable = " ".join(
                (
                    item.context_description,
                    self._json(item.failed_attempt),
                    self._json(item.successful_strategy),
                )
            ).casefold()
            terms = set(re.findall(r"[^\W_]+", searchable, flags=re.UNICODE))
            overlap = len(query_terms & terms)
            phrase_bonus = 1.0 if normalized_query and normalized_query in " ".join(searchable.split()) else 0.0
            score = overlap / max(len(query_terms), 1) + phrase_bonus
            if query_vector is not None:
                score += cosine_similarity(query_vector, item.context_vector)
            if score > 0:
                scored.append((score, row["created_at"], item.memory_id, item))
        scored.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
        return [entry[3] for entry in scored[:top_k]]

    async def list_all(self) -> list[MemoryItem]:
        """List records in stable creation-time/id order."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM experience_memories ORDER BY created_at, memory_id"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def delete(self, memory_id: str) -> bool:
        """Delete a record and report whether it existed."""
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise ValueError("memory_id must be a non-empty string")
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM experience_memories WHERE memory_id = ?", (memory_id,)
            )
            return cursor.rowcount > 0

    async def count(self) -> int:
        """Return the number of unique stored memories."""
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS item_count FROM experience_memories"
            ).fetchone()
        return int(row["item_count"])

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._connection.close()

    def __enter__(self) -> MemoryBank:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity for finite vectors; empty/zero vectors score zero."""
    import math
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def _keyword_score(signature: str, item: MemoryItem) -> float:
    """Legacy keyword-overlap score retained for downstream callers."""
    import re
    if not isinstance(signature, str):
        return 0.0
    terms = set(re.findall(r"[^\W_]+", signature.casefold(), flags=re.UNICODE))
    haystack = " ".join((item.context_description, json.dumps(item.failed_attempt), json.dumps(item.successful_strategy))).casefold()
    found = set(re.findall(r"[^\W_]+", haystack, flags=re.UNICODE))
    return len(terms & found) / max(len(terms), 1)
