from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog

from obase.exceptions import BudgetExceeded, PauseRequested, StageContractViolation
from obase.fs import FS

log = structlog.get_logger()


@dataclass
class OrchestratorContext:
    run_id: str
    pipeline_name: str
    stage_name: str
    trail: Any | None = None
    cost: Any | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Stage:
    name: str
    func: Callable[..., Coroutine[Any, Any, dict[str, Any]]]
    max_retries: int = 0
    retry_delay: float = 1.0
    input_keys: list[str] | None = None
    output_keys: list[str] | None = None


class CheckType(StrEnum):
    CHECKLIST = "checklist"
    COMMAND = "command"
    PREDICATE = "predicate"
    LLM_REVIEW = "llm_review"
    MANUAL = "manual"


@dataclass
class Check:
    type: CheckType
    payload: dict[str, Any]
    blocking: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "payload": self.payload,
            "blocking": self.blocking,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Check:
        return cls(
            type=CheckType(d["type"]),
            payload=d.get("payload", {}),
            blocking=d.get("blocking", True),
            id=d.get("id", uuid.uuid4().hex[:8]),
        )


@dataclass
class Node:
    id: str
    prompt: str = ""
    in_hook: str | None = None
    out_hook: str | None = None
    before_transfer: list[Check] = field(default_factory=list)


@dataclass
class Edge:
    from_node: str
    to_node: str
    condition: str = ""
    hook: str | None = None
    max_attempts: int = 3


@dataclass
class Runbook:
    name: str
    initial: str
    nodes: dict[str, Node]
    edges: list[Edge]
    version: str = "1"

    def content_hash(self) -> str:
        payload = {
            "name": self.name,
            "initial": self.initial,
            "version": self.version,
            "nodes": {
                k: {
                    "id": n.id,
                    "prompt": n.prompt,
                    "in_hook": n.in_hook,
                    "out_hook": n.out_hook,
                    "before_transfer": [c.to_dict() for c in n.before_transfer],
                }
                for k, n in self.nodes.items()
            },
            "edges": [
                {
                    "from_node": e.from_node,
                    "to_node": e.to_node,
                    "condition": e.condition,
                    "hook": e.hook,
                    "max_attempts": e.max_attempts,
                }
                for e in self.edges
            ],
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class RunEntry:
    entry_id: str
    node_id: str
    entered_at: float
    checks: list[dict[str, Any]] = field(default_factory=list)
    dynamic_checks: list[Check] = field(default_factory=list)
    attempts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "node_id": self.node_id,
            "entered_at": self.entered_at,
            "checks": self.checks,
            "dynamic_checks": [c.to_dict() for c in self.dynamic_checks],
            "attempts": self.attempts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunEntry:
        return cls(
            entry_id=d["entry_id"],
            node_id=d["node_id"],
            entered_at=d["entered_at"],
            checks=d.get("checks", []),
            dynamic_checks=[Check.from_dict(c) for c in d.get("dynamic_checks", [])],
            attempts=d.get("attempts", {}),
        )


@dataclass
class RunState:
    run_id: str
    pipeline_name: str
    started_at: datetime
    state: str = "pending"
    current_stage: str | None = None
    current_stage_index: int = 0
    paused_at_stage: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    # Runbook (graph) mode — unused by linear Pipeline runs.
    runbook_hash: str | None = None
    current_node: str | None = None
    current_entry_id: str | None = None
    entries: dict[str, RunEntry] = field(default_factory=dict)
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "started_at": self.started_at.isoformat(),
            "state": self.state,
            "current_stage": self.current_stage,
            "current_stage_index": self.current_stage_index,
            "paused_at_stage": self.paused_at_stage,
            "data": self.data,
            "errors": self.errors,
            "runbook_hash": self.runbook_hash,
            "current_node": self.current_node,
            "current_entry_id": self.current_entry_id,
            "entries": {eid: e.to_dict() for eid, e in self.entries.items()},
            "transitions": self.transitions,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunState:
        started_raw = d.get("started_at", datetime.now(UTC).isoformat())
        started = datetime.fromisoformat(started_raw)
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return cls(
            run_id=d["run_id"],
            pipeline_name=d["pipeline_name"],
            started_at=started,
            state=d.get("state", "pending"),
            current_stage=d.get("current_stage"),
            current_stage_index=d.get("current_stage_index", 0),
            paused_at_stage=d.get("paused_at_stage"),
            data=d.get("data", {}),
            errors=d.get("errors", []),
            runbook_hash=d.get("runbook_hash"),
            current_node=d.get("current_node"),
            current_entry_id=d.get("current_entry_id"),
            entries={eid: RunEntry.from_dict(e) for eid, e in d.get("entries", {}).items()},
            transitions=d.get("transitions", []),
        )


class Pipeline:
    def __init__(self, name: str, stages: list[Stage]) -> None:
        self.name = name
        self.stages = stages


def _save_run_state(state: RunState, run_dir: Path) -> None:
    path = run_dir / "run_state.json"
    path.write_text(json.dumps(state.to_dict(), default=str), encoding="utf-8")


def _load_run_state(run_dir: Path) -> RunState:
    path = run_dir / "run_state.json"
    return RunState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _filter_input(data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {k: data[k] for k in keys if k in data}


async def run_pipeline(
    pipeline: Pipeline,
    initial_data: dict[str, Any] | None = None,
    run_id: str | None = None,
    resume: bool = False,
    trail: Any | None = None,
    cost: Any | None = None,
) -> RunState:
    """Execute a pipeline. Supports resume from paused state."""

    if run_id is None:
        run_id = str(uuid.uuid4())

    run_dir = FS.run_dir(run_id)

    # ---- import lazily to avoid circular deps ----
    from obase.trail import Trail

    if trail is None:
        trail = Trail(run_id=run_id, run_dir=run_dir)

    if resume:
        state = _load_run_state(run_dir)
        start_index = state.current_stage_index
        state.state = "running"
        state.paused_at_stage = None
    else:
        state = RunState(
            run_id=run_id,
            pipeline_name=pipeline.name,
            started_at=datetime.now(UTC),
            state="running",
            data=dict(initial_data or {}),
        )
        start_index = 0

    _save_run_state(state, run_dir)
    trail.emit("pipeline_start", pipeline=pipeline.name, run_id=run_id)

    for idx in range(start_index, len(pipeline.stages)):
        stage = pipeline.stages[idx]
        state.current_stage = stage.name
        state.current_stage_index = idx
        _save_run_state(state, run_dir)

        ctx = OrchestratorContext(
            run_id=run_id,
            pipeline_name=pipeline.name,
            stage_name=stage.name,
            trail=trail,
            cost=cost,
        )

        trail.emit("stage_start", stage=stage.name)

        if stage.input_keys is not None:
            filtered_input = _filter_input(state.data, stage.input_keys)
        else:
            filtered_input = dict(state.data)

        result: dict[str, Any] | None = None
        last_exc: Exception | None = None
        attempts = 0

        while attempts <= stage.max_retries:
            try:
                result = await stage.func(filtered_input, ctx)
                break
            except PauseRequested as pr:
                state.data.update(pr.resume_data)
                state.state = "paused"
                state.paused_at_stage = stage.name
                _save_run_state(state, run_dir)
                trail.emit(
                    "pipeline_paused",
                    stage=stage.name,
                    reason=str(pr),
                    resume_data=pr.resume_data,
                )
                return state
            except BudgetExceeded as exc:
                state.state = "failed"
                state.errors.append(
                    {"stage": stage.name, "error": str(exc), "type": "BudgetExceeded"}
                )
                _save_run_state(state, run_dir)
                trail.emit("pipeline_failed", stage=stage.name, reason=str(exc))
                return state
            except StageContractViolation:
                raise
            except Exception as exc:
                last_exc = exc
                attempts += 1
                state.errors.append({"stage": stage.name, "attempt": attempts, "error": str(exc)})
                trail.emit("stage_error", stage=stage.name, attempt=attempts, error=str(exc))
                if attempts <= stage.max_retries:
                    await asyncio.sleep(stage.retry_delay)
                else:
                    break

        if result is None:
            state.state = "failed"
            _save_run_state(state, run_dir)
            trail.emit("pipeline_failed", stage=stage.name, reason=str(last_exc))
            return state

        if stage.output_keys is not None:
            extra_keys = set(result.keys()) - set(stage.output_keys)
            if extra_keys:
                raise StageContractViolation(
                    f"Stage {stage.name!r} returned unexpected keys: {sorted(extra_keys)}. "
                    f"Allowed output_keys: {stage.output_keys}"
                )
            missing_keys = set(stage.output_keys) - set(result.keys())
            if missing_keys:
                raise StageContractViolation(
                    f"Stage {stage.name!r} missing required output keys: {sorted(missing_keys)}. "
                    f"Required output_keys: {stage.output_keys}"
                )

        state.data.update(result)
        trail.emit("stage_done", stage=stage.name)
        _save_run_state(state, run_dir)

    state.state = "completed"
    _save_run_state(state, run_dir)
    trail.emit("pipeline_done", pipeline=pipeline.name)
    trail.finalize(state="completed")
    return state


def start_runbook(runbook: Runbook, run_id: str | None = None, resume: bool = True) -> RunState:
    """Start (or resume) a Runbook-driven run. Reuses the Pipeline persistence path."""
    run_id = run_id or str(uuid.uuid4())
    run_dir = FS.run_dir(run_id)
    state_path = run_dir / "run_state.json"

    if resume and state_path.exists():
        existing = _load_run_state(run_dir)
        if existing.runbook_hash == runbook.content_hash():
            return existing
        raise StageContractViolation(
            f"Runbook hash mismatch for run {run_id!r}: "
            f"stored={existing.runbook_hash} current={runbook.content_hash()}. "
            "Refuse automatic resume."
        )

    entry_id = uuid.uuid4().hex[:12]
    state = RunState(
        run_id=run_id,
        pipeline_name=runbook.name,
        started_at=datetime.now(UTC),
        state="running",
        runbook_hash=runbook.content_hash(),
        current_node=runbook.initial,
        current_entry_id=entry_id,
    )
    state.entries[entry_id] = RunEntry(
        entry_id=entry_id, node_id=runbook.initial, entered_at=time.time()
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    _save_run_state(state, run_dir)
    return state


def runbook_current(runbook: Runbook, run_id: str) -> dict[str, Any]:
    """Return the node the run is currently sitting in, plus the edges it may take."""
    state = _load_run_state(FS.run_dir(run_id))
    node = runbook.nodes[state.current_node]
    return {
        "run_id": run_id,
        "node": state.current_node,
        "entry_id": state.current_entry_id,
        "prompt": node.prompt,
        "state": state.state,
        "allowed_next": [e.to_node for e in runbook.edges if e.from_node == state.current_node],
    }


def runbook_goto(
    runbook: Runbook,
    run_id: str,
    target: str,
    check_runner: Callable[[Check, dict[str, Any]], dict[str, Any]],
    hook_runner: Callable[[str, dict[str, Any]], Any] | None = None,
    agent_context: dict[str, Any] | None = None,
    causal_store: Any | None = None,
) -> dict[str, Any]:
    """Attempt to transition the run from its current node to ``target``.

    Runs ``before_transfer`` checks first; a failing blocking check keeps the
    run at its current node and records the attempt (capped by
    ``edge.max_attempts``, after which the run is marked ``blocked``).
    """
    run_dir = FS.run_dir(run_id)
    state = _load_run_state(run_dir)
    if state.state != "running":
        return {"ok": False, "reason": f"invalid state: {state.state}"}

    edge = next(
        (e for e in runbook.edges if e.from_node == state.current_node and e.to_node == target),
        None,
    )
    if edge is None:
        return {"ok": False, "reason": f"no edge {state.current_node} -> {target}"}

    edge_key = f"{edge.from_node}->{edge.to_node}"
    entry = state.entries[state.current_entry_id]
    attempts = entry.attempts.get(edge_key, 0)
    if attempts >= edge.max_attempts:
        state.state = "blocked"
        _save_run_state(state, run_dir)
        return {"ok": False, "reason": "max_attempts exceeded", "blocked": True}

    node = runbook.nodes[state.current_node]
    check_results: list[dict[str, Any]] = []
    for chk in [*node.before_transfer, *entry.dynamic_checks]:
        result = check_runner(
            chk, {"run_id": run_id, "node": state.current_node, "agent": agent_context or {}}
        )
        check_results.append({"check_id": chk.id, "type": chk.type.value, **result})
        if chk.blocking and not result.get("passed", False):
            entry.attempts[edge_key] = attempts + 1
            entry.checks.extend(check_results)
            _save_run_state(state, run_dir)
            record_failure = getattr(causal_store, "record_failure", None)
            if record_failure is not None:
                record_failure(state.current_node, result.get("message", ""), result)
            return {
                "ok": False,
                "reason": "before_transfer failed",
                "failed_check": result,
                "stay_in": state.current_node,
                "evidence": check_results,
            }

    if hook_runner is not None:
        if node.out_hook:
            hook_runner(node.out_hook, {"run_id": run_id, "to": target})
        if edge.hook:
            hook_runner(edge.hook, {"run_id": run_id})

    old_entry = state.current_entry_id
    new_entry_id = uuid.uuid4().hex[:12]
    state.transitions.append(
        {
            "from": edge.from_node,
            "to": target,
            "from_entry": old_entry,
            "to_entry": new_entry_id,
            "checks": check_results,
            "ts": time.time(),
        }
    )
    state.current_node = target
    state.current_entry_id = new_entry_id
    state.entries[new_entry_id] = RunEntry(
        entry_id=new_entry_id, node_id=target, entered_at=time.time()
    )

    target_node = runbook.nodes[target]
    if hook_runner is not None and target_node.in_hook:
        hook_runner(target_node.in_hook, {"run_id": run_id, "node": target})

    if not any(e.from_node == target for e in runbook.edges):
        state.state = "completed"

    _save_run_state(state, run_dir)
    return {
        "ok": True,
        "from": edge.from_node,
        "to": target,
        "entry_id": new_entry_id,
        "prompt": target_node.prompt,
    }


def register_dynamic_check(run_id: str, check: Check) -> None:
    """Attach a check to the run's current entry, evaluated on the next ``runbook_goto``."""
    run_dir = FS.run_dir(run_id)
    state = _load_run_state(run_dir)
    entry = state.entries[state.current_entry_id]
    entry.dynamic_checks.append(check)
    _save_run_state(state, run_dir)


def runbook_history(run_id: str, tail: int = 50) -> list[dict[str, Any]]:
    state = _load_run_state(FS.run_dir(run_id))
    return state.transitions[-tail:]
