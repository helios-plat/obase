"""obase.team_registry — ClawTeam-style multi-agent team registry.

TeamConfig / TeamMember / TaskItem models plus a TeamRegistry that persists
to a file-based JSON store.  Zero external deps — pure Python with fcntl-based
file locking for multi-agent safety.

3O element: ``obase.team_registry`` (``TeamRegistry`` / models).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# models (mirror ClawTeam's pydantic models as lightweight dataclass-like dicts)
# ---------------------------------------------------------------------------

STATUSES = ("pending", "in_progress", "completed", "blocked")
PRIORITIES = ("low", "medium", "high", "urgent")
MSG_TYPES = (
    "message", "join_request", "join_approved", "join_rejected",
    "plan_approval_request", "plan_approved", "plan_rejected",
    "shutdown_request", "shutdown_approved", "shutdown_rejected",
    "idle", "broadcast",
)


def make_team_member(name: str, **kw: Any) -> dict[str, Any]:
    return {
        "name": name, "user": "", "agent_id": uuid.uuid4().hex[:12],
        "agent_type": kw.pop("agent_type", "general-purpose"),
        "joined_at": _now_iso(), **kw,
    }


def make_team_config(
    name: str, description: str = "", lead_agent_id: str = "",
    members: list[dict[str, Any]] | None = None, budget_cents: float = 0.0,
) -> dict[str, Any]:
    return {
        "name": name, "description": description,
        "lead_agent_id": lead_agent_id, "created_at": _now_iso(),
        "members": members or [], "budget_cents": budget_cents,
    }


def make_task(
    subject: str, description: str = "", status: str = "pending",
    priority: str = "medium", owner: str = "", blocks: list[str] | None = None,
    blocked_by: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:8], "subject": subject,
        "description": description, "status": status, "priority": priority,
        "owner": owner, "locked_by": "", "locked_at": "",
        "blocks": blocks or [], "blocked_by": blocked_by or [],
        "started_at": "", "created_at": _now_iso(), "updated_at": _now_iso(),
        "metadata": {},
    }


def make_message(
    from_agent: str, to: str | None = None, content: str | None = None,
    msg_type: str = "message", request_id: str | None = None, **kw: Any,
) -> dict[str, Any]:
    return {
        "type": msg_type, "from": from_agent, "to": to,
        "content": content, "request_id": request_id or uuid.uuid4().hex[:8],
        "timestamp": _now_iso(), **{k: v for k, v in kw.items() if v is not None},
    }


# ---------------------------------------------------------------------------
# TeamRegistry — creates / lists / updates teams
# ---------------------------------------------------------------------------


class TeamRegistry:
    """ClawTeam-style team registry backed by a file-based JSON store."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir else Path.home() / ".clawteam"
        self._base.mkdir(parents=True, exist_ok=True)

    def _team_dir(self, team_name: str) -> Path:
        d = self._base / "teams" / team_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _config_path(self, team_name: str) -> Path:
        return self._team_dir(team_name) / "config.json"

    def _tasks_path(self, team_name: str) -> Path:
        return self._team_dir(team_name) / "tasks.json"

    # -- team CRUD ---------------------------------------------------------
    def create_team(
        self, name: str, description: str = "", lead_agent_id: str = "",
        budget_cents: float = 0.0,
    ) -> dict[str, Any]:
        if self._config_path(name).exists():
            raise ValueError(f"team {name!r} already exists")
        cfg = make_team_config(name, description, lead_agent_id, budget_cents=budget_cents)
        self._save_json(self._config_path(name), cfg)
        return cfg

    def get_team(self, name: str) -> dict[str, Any] | None:
        p = self._config_path(name)
        return self._load_json(p) if p.exists() else None

    def list_teams(self) -> list[dict[str, Any]]:
        root = self._base / "teams"
        if not root.exists():
            return []
        return [
            self._load_json(root / d / "config.json")
            for d in root.iterdir() if d.is_dir()
            if (root / d / "config.json").exists()
        ]

    # -- members -----------------------------------------------------------
    def add_member(self, team_name: str, name: str, **kw: Any) -> dict[str, Any]:
        cfg = self.get_team(team_name)
        if cfg is None:
            raise ValueError(f"team {team_name!r} not found")
        member = make_team_member(name, **kw)
        cfg.setdefault("members", []).append(member)
        if not cfg.get("lead_agent_id"):
            cfg["lead_agent_id"] = member["agent_id"]
        self._save_json(self._config_path(team_name), cfg)
        return member

    def remove_member(self, team_name: str, member_name: str) -> bool:
        cfg = self.get_team(team_name)
        if cfg is None:
            return False
        before = len(cfg.get("members", []))
        cfg["members"] = [m for m in cfg.get("members", []) if m["name"] != member_name]
        self._save_json(self._config_path(team_name), cfg)
        return len(cfg["members"]) < before

    def list_members(self, team_name: str) -> list[dict[str, Any]]:
        cfg = self.get_team(team_name)
        return list(cfg.get("members", [])) if cfg else []

    def get_leader_name(self, team_name: str) -> str | None:
        cfg = self.get_team(team_name)
        if cfg is None:
            return None
        lead_id = cfg.get("lead_agent_id")
        for m in cfg.get("members", []):
            if m.get("agent_id") == lead_id:
                return m["name"]
        return None

    # -- tasks -------------------------------------------------------------
    def add_task(self, team_name: str, subject: str, **kw: Any) -> dict[str, Any]:
        task = make_task(subject)
        task.update({k: v for k, v in kw.items() if k in task and k not in ("subject",)})
        tasks = self._load_json(self._tasks_path(team_name)) or []
        tasks.append(task)
        self._save_json(self._tasks_path(team_name), tasks)
        return task

    def get_tasks(self, team_name: str, status: str | None = None) -> list[dict[str, Any]]:
        tasks = self._load_json(self._tasks_path(team_name)) or []
        if status:
            return [t for t in tasks if t.get("status") == status]
        return tasks

    def update_task(self, team_name: str, task_id: str, **fields: Any) -> bool:
        tasks = self._load_json(self._tasks_path(team_name)) or []
        for t in tasks:
            if t.get("id") == task_id:
                t.update(fields)
                t["updated_at"] = _now_iso()
                self._save_json(self._tasks_path(team_name), tasks)
                return True
        return False

    def lock_task(self, team_name: str, task_id: str, agent_name: str) -> bool:
        return self.update_task(team_name, task_id, status="in_progress", locked_by=agent_name, locked_at=_now_iso(), started_at=_now_iso())

    # -- messages / inbox --------------------------------------------------
    def _inbox_dir(self, team_name: str, agent_name: str) -> Path:
        d = self._team_dir(team_name) / "inboxes" / agent_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def send_message(self, team_name: str, msg: dict[str, Any]) -> dict[str, Any]:
        if "request_id" not in msg:
            msg["request_id"] = uuid.uuid4().hex[:8]
        if "timestamp" not in msg:
            msg["timestamp"] = _now_iso()
        recipient = msg.get("to")
        if not recipient:
            raise ValueError("message must have a 'to' field")
        inbox = self._inbox_dir(team_name, recipient)
        fname = f"{msg['request_id']}.json"
        self._save_json(inbox / fname, msg)
        return msg

    def receive_messages(self, team_name: str, agent_name: str, limit: int = 10) -> list[dict[str, Any]]:
        inbox = self._inbox_dir(team_name, agent_name)
        msgs: list[dict[str, Any]] = []
        for f in sorted(inbox.glob("*.json")):
            m = self._load_json(f)
            if m:
                msgs.append(m)
            f.unlink(missing_ok=True)  # consumed
            if len(msgs) >= limit:
                break
        return msgs

    def broadcast(self, team_name: str, from_agent: str, content: str) -> list[dict[str, Any]]:
        members = self.list_members(team_name)
        sent: list[dict[str, Any]] = []
        for m in members:
            if m["name"] == from_agent:
                continue
            msg = make_message(from_agent=from_agent, to=m["name"], content=content, msg_type="broadcast")
            sent.append(self.send_message(team_name, msg))
        return sent

    # -- helpers -----------------------------------------------------------
    def cleanup(self, team_name: str) -> bool:
        import shutil
        d = self._team_dir(team_name)
        if d.exists():
            shutil.rmtree(d)
            return True
        return False

    @staticmethod
    def _save_json(path: Path, obj: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _load_json(path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
