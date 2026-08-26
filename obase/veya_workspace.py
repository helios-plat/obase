"""obase.veya_workspace — Spec Kit paths + TaskNode. No scheduling."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SpecKitPaths:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.speckit_dir = self.root / ".speckit"
        self.goal_runs_dir = self.root / ".veya-project" / "goal-runs"

    def artifact(self, name: str) -> Path:
        return self.speckit_dir / name

    def run_dir(self, goal_id: str) -> Path:
        return self.goal_runs_dir / goal_id

    def taskgraph_path(self, goal_id: str) -> Path:
        return self.run_dir(goal_id) / "taskgraph.json"


class TaskNode(BaseModel):
    id: str
    title: str
    instruction: str
    acceptance: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    assignee: str = "hicode"
    status: Literal[
        "pending", "ready", "running", "verifying", "completed", "blocked", "cancelled"
    ] = "pending"
    retries: int = 0
    # smart-ralph [P] marker: 此任务与其他无显式依赖的 [P] 任务可并行执行
    # 对标 mattpocock/skills: task-planner 标注哪些任务可安全并行
    parallel: bool = False
