from __future__ import annotations

import pytest

from obase.exceptions import BudgetExceeded, PauseRequested, StageContractViolation
from obase.orchestrator import OrchestratorContext, Pipeline, Stage, run_pipeline


async def _echo(data: dict, ctx: OrchestratorContext) -> dict:
    return data


async def _add_key(data: dict, ctx: OrchestratorContext) -> dict:
    return {"result": "ok"}


async def _fail_once(data: dict, ctx: OrchestratorContext) -> dict:
    if not data.get("_retried"):
        data["_retried"] = True
        raise RuntimeError("transient error")
    return {"done": True}


async def _always_fail(data: dict, ctx: OrchestratorContext) -> dict:
    raise RuntimeError("always fails")


async def _pause_stage(data: dict, ctx: OrchestratorContext) -> dict:
    raise PauseRequested("waiting for human", resume_data={"x": 1, "approved": True})


async def _budget_busted(data: dict, ctx: OrchestratorContext) -> dict:
    raise BudgetExceeded("over budget")


async def _strict_in(data: dict, ctx: OrchestratorContext) -> dict:
    return {"out": "value"}


async def _strict_out_extra(data: dict, ctx: OrchestratorContext) -> dict:
    return {"expected_key": "v", "extra_key": "bad"}


async def _strict_out_missing(data: dict, ctx: OrchestratorContext) -> dict:
    return {}


class TestCompatibleMode:
    async def test_stage_compatible_mode(self):
        """input_keys=None/output_keys=None: stage receives full dict."""
        received: dict = {}

        async def capture(data: dict, ctx: OrchestratorContext) -> dict:
            received.update(data)
            return {"extra": "added"}

        pipeline = Pipeline("p", [Stage("s1", capture)])
        state = await run_pipeline(pipeline, initial_data={"foo": "bar", "baz": 42})
        assert state.state == "completed"
        assert received["foo"] == "bar"
        assert received["baz"] == 42
        assert state.data["extra"] == "added"

    async def test_stage_strict_mode_valid(self):
        """Non-None keys execute and produce correct output."""
        pipeline = Pipeline(
            "p",
            [
                Stage(
                    "s1",
                    _strict_in,
                    input_keys=["inp"],
                    output_keys=["out"],
                )
            ],
        )
        state = await run_pipeline(pipeline, initial_data={"inp": "hello", "other": "ignored"})
        assert state.state == "completed"
        assert state.data["out"] == "value"

    async def test_stage_strict_violation_output_extra_key(self):
        """Stage returning extra keys raises StageContractViolation."""
        pipeline = Pipeline(
            "p",
            [Stage("s1", _strict_out_extra, output_keys=["expected_key"])],
        )
        with pytest.raises(StageContractViolation, match="extra_key"):
            await run_pipeline(pipeline, initial_data={})

    async def test_stage_strict_violation_output_missing_key(self):
        """Stage missing required output keys raises StageContractViolation."""
        pipeline = Pipeline(
            "p",
            [Stage("s1", _strict_out_missing, output_keys=["required_key"])],
        )
        with pytest.raises(StageContractViolation, match="required_key"):
            await run_pipeline(pipeline, initial_data={})


class TestPauseResume:
    async def test_pause_with_resume_data(self):
        """PauseRequested merges resume_data into state.data, sets state=paused."""
        pipeline = Pipeline("p", [Stage("gate", _pause_stage)])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.state == "paused"
        assert state.paused_at_stage == "gate"
        assert state.data["x"] == 1
        assert state.data["approved"] is True

    async def test_resume_paused_stage(self, tmp_path):
        """resume=True continues from the paused stage index."""
        call_count = {"n": 0}

        async def pausable(data: dict, ctx: OrchestratorContext) -> dict:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise PauseRequested("first pass")
            return {"resumed": True}

        async def second(data: dict, ctx: OrchestratorContext) -> dict:
            return {"second_done": True}

        pipeline = Pipeline("p", [Stage("pausable", pausable), Stage("second", second)])
        state1 = await run_pipeline(pipeline, run_id="resume-test", initial_data={})
        assert state1.state == "paused"

        state2 = await run_pipeline(pipeline, run_id="resume-test", resume=True)
        assert state2.state == "completed"
        assert state2.data.get("resumed") is True
        assert state2.data.get("second_done") is True


class TestRetryAndFailure:
    async def test_retry_exhausted_abort(self):
        """Exceeding max_retries results in state=failed."""
        pipeline = Pipeline("p", [Stage("bad", _always_fail, max_retries=2, retry_delay=0)])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.state == "failed"
        assert len(state.errors) == 3

    async def test_retry_succeeds_on_second_attempt(self):
        """Stage succeeds within retry budget → completed."""
        pipeline = Pipeline("p", [Stage("s", _fail_once, max_retries=2, retry_delay=0)])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.state == "completed"

    async def test_budget_exceeded_stops_pipeline(self):
        """BudgetExceeded from a stage sets state=failed, does not propagate."""
        pipeline = Pipeline("p", [Stage("costly", _budget_busted)])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.state == "failed"
        assert any("BudgetExceeded" in str(e) for e in state.errors)

    async def test_empty_pipeline_completes(self):
        pipeline = Pipeline("empty", [])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.state == "completed"

    async def test_run_state_fields(self):
        pipeline = Pipeline("p", [Stage("s", _add_key)])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.pipeline_name == "p"
        assert state.run_id is not None
        assert state.started_at is not None
        assert state.state == "completed"

    async def test_data_accumulates_across_stages(self):
        async def s1(data: dict, ctx: OrchestratorContext) -> dict:
            return {"from_s1": 1}

        async def s2(data: dict, ctx: OrchestratorContext) -> dict:
            assert data["from_s1"] == 1
            return {"from_s2": 2}

        pipeline = Pipeline("p", [Stage("s1", s1), Stage("s2", s2)])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.data["from_s1"] == 1
        assert state.data["from_s2"] == 2

    async def test_trail_injected(self):

        events: list[str] = []

        class MockTrail:
            def emit(self, event: str, **kwargs):
                events.append(event)

            def save_stage_input(self, stage_name: str, data: dict) -> None:
                pass

            def save_stage_output(self, stage_name: str, data: dict) -> None:
                pass

            def finalize(self, state: str, **kwargs) -> None:
                events.append("finalize")

        pipeline = Pipeline("p", [Stage("s", _echo)])
        await run_pipeline(pipeline, initial_data={"a": 1}, trail=MockTrail())
        assert "pipeline_start" in events
        assert "finalize" in events
