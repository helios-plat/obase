"""obase.durable_lease_queue — 持久化租约队列.

SQLite 落盘的可靠任务队列：enqueue → lease（带租约超时）→ renew → complete /
release。租约超时未完成的任务可被其他 worker 重新领取（at-least-once 语义）。

Example:
    >>> q = DurableLeaseQueue("/tmp/queue.db")
    >>> q.enqueue({"task": "x"}, priority=1)
    'task-...'
    >>> lease = q.lease("worker-1", timeout_s=30.0)
    >>> q.complete(lease["lease_id"])
    True
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = ["DurableLeaseQueue", "LeaseQueueError"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queue_items (
    item_id     TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | leased | done | failed
    worker_id   TEXT,
    lease_id    TEXT,
    lease_until REAL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_queue_pending ON queue_items(status, priority, created_at);
"""


class LeaseQueueError(RuntimeError):
    """租约队列操作失败。"""


class DurableLeaseQueue:
    """SQLite 持久化租约队列（线程安全：每操作独立连接 + 全局锁）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def enqueue(
        self, payload: dict[str, Any], *, priority: int = 0, item_id: str | None = None
    ) -> str:
        """入队，返回 item_id。"""
        now = time.time()
        item_id = item_id or f"task-{uuid.uuid4().hex[:12]}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO queue_items
                    (item_id, payload, priority, status, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (item_id, json.dumps(payload, ensure_ascii=False, default=str),
                 priority, now, now),
            )
        return item_id

    # ------------------------------------------------------------------
    # 租约
    # ------------------------------------------------------------------

    def lease(
        self, worker_id: str, *, timeout_s: float = 60.0, max_attempts: int = 3
    ) -> dict[str, Any] | None:
        """领取一个 pending 或过期租约的任务；无任务返回 None。

        返回 {"item_id", "lease_id", "payload", "attempts"}。
        """
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM queue_items
                WHERE (status = 'pending')
                   OR (status = 'leased' AND lease_until < ? AND attempts < ?)
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                """,
                (now, max_attempts),
            ).fetchone()
            if row is None:
                return None
            lease_id = f"lease-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                UPDATE queue_items
                SET status='leased', worker_id=?, lease_id=?, lease_until=?,
                    attempts=attempts+1, updated_at=?
                WHERE item_id=?
                """,
                (worker_id, lease_id, now + timeout_s, now, row["item_id"]),
            )
        return {
            "item_id": row["item_id"],
            "lease_id": lease_id,
            "payload": json.loads(row["payload"]),
            "attempts": row["attempts"] + 1,
        }

    def renew(self, lease_id: str, *, timeout_s: float = 60.0) -> bool:
        """续租（长任务保活）。"""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE queue_items SET lease_until=? WHERE lease_id=? AND status='leased'",
                (time.time() + timeout_s, lease_id),
            )
            return cur.rowcount > 0

    def complete(self, lease_id: str) -> bool:
        """任务完成（幂等）。"""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE queue_items SET status='done', updated_at=? WHERE lease_id=?",
                (time.time(), lease_id),
            )
            return cur.rowcount > 0

    def release(self, lease_id: str) -> bool:
        """释放租约回到 pending（worker 失败时归还）。"""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE queue_items SET status='pending', worker_id=NULL,
                    lease_id=NULL, lease_until=NULL, updated_at=?
                WHERE lease_id=? AND status='leased'
                """,
                (time.time(), lease_id),
            )
            return cur.rowcount > 0

    def fail(self, lease_id: str) -> bool:
        """标记失败（不再领取）。"""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE queue_items SET status='failed', updated_at=? WHERE lease_id=?",
                (time.time(), lease_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # 查询/维护
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM queue_items GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def pending_count(self) -> int:
        return int(self.stats().get("pending", 0))

    def get(self, item_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM queue_items WHERE item_id=?", (item_id,)
            ).fetchone()
        if row is None:
            return None
        return {k: row[k] for k in row.keys()} | {"payload": json.loads(row["payload"])}

    def sweep_expired(self, *, max_attempts: int = 3) -> int:
        """把过期租约释放回 pending（超 max_attempts 的置 failed）。返回处理数。"""
        now = time.time()
        with self._lock, self._connect() as conn:
            expired = conn.execute(
                "SELECT item_id, attempts FROM queue_items "
                "WHERE status='leased' AND lease_until < ?",
                (now,),
            ).fetchall()
            for row in expired:
                if row["attempts"] >= max_attempts:
                    conn.execute(
                        "UPDATE queue_items SET status='failed', updated_at=? WHERE item_id=?",
                        (now, row["item_id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE queue_items SET status='pending', worker_id=NULL, "
                        "lease_id=NULL, lease_until=NULL, updated_at=? WHERE item_id=?",
                        (now, row["item_id"]),
                    )
            return len(expired)
