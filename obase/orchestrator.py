from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
                state.errors.append(
                    {"stage": stage.name, "attempt": attempts, "error": str(exc)}
                )
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
