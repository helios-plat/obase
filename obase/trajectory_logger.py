"""3O 范式内化 — 演化轨迹日志 (obase 基础设施).

OpenRSI 演化轨迹 JSONL 落盘与读取 (训练/演化闭环的观测面)。
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TrajectoryEntry:
    """OpenRSI 演化轨迹节点 (与规范数据契约一致)。"""

    task_id: str
    branch_id: str
    operator_used: str
    input_code: str
    error_trace: str = ""
    output_code: str = ""
    sandbox_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrajectoryLog:
    """追加式 JSONL 轨迹日志 (线程安全)。"""

    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, entry: TrajectoryEntry) -> Path:
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return self.log_path

    def load(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        with self._lock:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines:
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def count(self) -> int:
        return len(self.load())


def append_trajectory(entry: TrajectoryEntry, *, path: str | Path) -> Path:
    """单次轨迹落盘 (函数入口)。"""
    return TrajectoryLog(path).append(entry)


def load_trajectories(path: str | Path) -> list[dict[str, Any]]:
    """读取全部轨迹。"""
    return TrajectoryLog(path).load()
