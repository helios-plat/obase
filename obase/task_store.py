"""obase.task_store — SQLite transactional task persistence.

3O layer: obase (I/O and resources).
Persists step-based task state (the transactional state machine's durable
backing store): each checkpoint is a committed SQLite transaction, so a
crash mid-write can never corrupt the resume point.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

DEFAULT_DB_PATH = str(Path.home() / ".veya" / "tasks.db")


class TaskStore:
    """SQLite-backed durable store for step-based tasks."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(
            db_path or os.environ.get("VEYA_TASKS_DB", DEFAULT_DB_PATH)
        ).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_dag (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    current_step INTEGER NOT NULL,
                    total_steps INTEGER NOT NULL,
                    steps_data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # ── 事务写入(每操作一个 SQLite 事务 = 原子) ──────────────────────
    def create(self, task_id: str, total_steps: int, steps: list[dict]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task_dag VALUES (?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    "PENDING",
                    0,
                    total_steps,
                    json.dumps(steps, ensure_ascii=False),
                    _now(),
                ),
            )
            conn.commit()

    def checkpoint(
        self,
        task_id: str,
        *,
        status: str,
        current_step: int,
        steps: list[dict],
    ) -> None:
        """Atomically persist one step's completed state (the resume point)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE task_dag SET status = ?, current_step = ?, steps_data = ?, "
                "updated_at = ? WHERE task_id = ?",
                (status, current_step, json.dumps(steps, ensure_ascii=False), _now(), task_id),
            )
            conn.commit()

    def mark_status(self, task_id: str, status: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE task_dag SET status = ?, updated_at = ? WHERE task_id = ?",
                (status, _now(), task_id),
            )
            conn.commit()

    # ── 读取 ─────────────────────────────────────────────────────────
    def load(self, task_id: str) -> dict[str, Any] | None:
        """Full task snapshot: {task_id, status, current_step, total_steps, steps}."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT task_id, status, current_step, total_steps, steps_data "
                "FROM task_dag WHERE task_id = ?",
                (task_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "status": row[1],
            "current_step": row[2],
            "total_steps": row[3],
            "steps": json.loads(row[4]),
        }

    def list_tasks(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT task_id, status, current_step, total_steps, updated_at FROM task_dag"
            )
            rows = cur.fetchall()
        return [
            {
                "task_id": r[0],
                "status": r[1],
                "current_step": r[2],
                "total_steps": r[3],
                "updated_at": r[4],
            }
            for r in rows
        ]

    def delete(self, task_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM task_dag WHERE task_id = ?", (task_id,))
            conn.commit()


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat()
