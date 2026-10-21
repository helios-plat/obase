"""obase.snapshot_store — 快照存储与版本化状态管理基础设施.

职责:
- 带版本号的状态快照持久化
- 支持时间线回滚与 diff 比较
- 为 oskill._backtranslate_diff 提供历史状态查询

零反向依赖: 不 import oprim/oskill/omodul.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = ["SnapshotStore", "SnapshotMeta", "SnapshotStoreError"]


class SnapshotStoreError(RuntimeError):
    """快照存储错误."""


class SnapshotMeta:
    """快照元数据."""

    def __init__(
        self,
        snapshot_id: str,
        version: int,
        timestamp: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.snapshot_id = snapshot_id
        self.version = version
        self.timestamp = timestamp
        self.labels = labels or {}


class SnapshotStore:
    """快照存储与版本化状态管理.

    每个 entity_id 维护一条版本链，支持回滚与 diff。
    """

    def __init__(self, store_dir: str = ".snapshots") -> None:
        self.store_dir = Path(store_dir)
        os.makedirs(self.store_dir, exist_ok=True)
        self._index: dict[str, list[SnapshotMeta]] = {}

    def save(
        self,
        entity_id: str,
        state: dict[str, Any],
        *,
        labels: dict[str, str] | None = None,
    ) -> SnapshotMeta:
        """保存状态快照，自动递增版本号.

        Args:
            entity_id: 实体标识
            state: 状态字典
            labels: 标签

        Returns:
            SnapshotMeta
        """
        history = self._index.get(entity_id, [])
        version = len(history) + 1
        snap_id = uuid.uuid4().hex[:12]
        timestamp = time.time()

        meta = SnapshotMeta(
            snapshot_id=snap_id,
            version=version,
            timestamp=timestamp,
            labels=labels,
        )

        filepath = self.store_dir / f"{entity_id}_{snap_id}.json"
        payload = {
            "meta": {
                "snapshot_id": snap_id,
                "version": version,
                "timestamp": timestamp,
                "entity_id": entity_id,
                "labels": labels or {},
            },
            "state": state,
        }
        filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        history.append(meta)
        self._index[entity_id] = history
        return meta

    def load(self, entity_id: str, *, version: int | None = None) -> dict[str, Any] | None:
        """加载快照.

        Args:
            entity_id: 实体标识
            version: 版本号（None = 最新）

        Returns:
            状态字典或 None
        """
        history = self._index.get(entity_id, [])
        if not history:
            return None

        target = history[-1] if version is None else next(
            (h for h in history if h.version == version), None
        )
        if target is None:
            return None

        filepath = self.store_dir / f"{entity_id}_{target.snapshot_id}.json"
        if not filepath.exists():
            return None

        payload = json.loads(filepath.read_text())
        return payload.get("state", {})

    def list_versions(self, entity_id: str) -> list[int]:
        """列出所有版本号."""
        return [m.version for m in self._index.get(entity_id, [])]

    def diff(
        self, entity_id: str, version_a: int, version_b: int
    ) -> dict[str, Any]:
        """比较两个版本的差异.

        Returns:
            {"added": {...}, "removed": {...}, "changed": {...}}
        """
        state_a = self.load(entity_id, version=version_a) or {}
        state_b = self.load(entity_id, version=version_b) or {}

        added = {k: v for k, v in state_b.items() if k not in state_a}
        removed = {k: v for k, v in state_a.items() if k not in state_b}
        changed = {
            k: {"from": state_a[k], "to": state_b[k]}
            for k in state_a
            if k in state_b and state_a[k] != state_b[k]
        }

        return {"added": added, "removed": removed, "changed": changed}

    def health(self) -> dict[str, Any]:
        """健康检查."""
        return {
            "status": "healthy",
            "store_dir": str(self.store_dir),
            "entity_count": len(self._index),
        }
