"""End-to-end integration tests wiring orchestrator + trail + cost + cache + rate_limit."""

from __future__ import annotations

import pytest

from obase.cache import Cache
from obase.cost_tracker import CostTracker, PricingEntry, PricingTable
from obase.exceptions import PauseRequested
from obase.orchestrator import OrchestratorContext, Pipeline, Stage, run_pipeline
from obase.rate_limit import RateLimitRegistry
from obase.trail import Trail, load_trail


class TestFullPipeline:
    async def test_pipeline_with_trail_and_cost(self, tmp_path):
        """Full run: 3 stages, trail recorded, cost tracked."""
        table = PricingTable(
            entries=[
                PricingEntry(
                    category="llm",
                    provider="mock",
                    model_or_tier="v1",
                    unit="token",
                    price_usd=0.001,
                )
            ]
        )
        cost = CostTracker(pricing_table=table, budget_usd=10.0)
        trail = Trail("integration-run-1")

        async def stage_a(data: dict, ctx: OrchestratorContext) -> dict:
            cost.record("llm", "mock", "v1", "token", 10)
            return {"step_a": "done"}

        async def stage_b(data: dict, ctx: OrchestratorContext) -> dict:
            assert data["step_a"] == "done"
            return {"step_b": "done"}

        async def stage_c(data: dict, ctx: OrchestratorContext) -> dict:
            return {"final": True}

        pipeline = Pipeline(
            "integration-test",
            [Stage("a", stage_a), Stage("b", stage_b), Stage("c", stage_c)],
        )
        state = await run_pipeline(
            pipeline,
            initial_data={},
            run_id="integration-run-1",
            trail=trail,
            cost=cost,
        )
        assert state.state == "completed"
        assert state.data["final"] is True
        assert cost.total_usd == pytest.approx(0.01)

        events = load_trail("integration-run-1")
        event_types = [e["event"] for e in events]
        assert "pipeline_start" in event_types
        assert "stage_start" in event_types
        assert "pipeline_done" in event_types

    async def test_pipeline_pause_and_resume(self, tmp_path):
        """Pause a pipeline mid-way, resume and complete it."""
        call_count = {"n": 0}

        async def gate(data: dict, ctx: OrchestratorContext) -> dict:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise PauseRequested("waiting for approval", resume_data={"approved": True})
            return {"gate_passed": True}

        async def finisher(data: dict, ctx: OrchestratorContext) -> dict:
            return {"finished": True}

        pipeline = Pipeline("pause-test", [Stage("gate", gate), Stage("finish", finisher)])

        state1 = await run_pipeline(pipeline, run_id="pause-resume-1", initial_data={})
        assert state1.state == "paused"
        assert state1.data.get("approved") is True

        state2 = await run_pipeline(pipeline, run_id="pause-resume-1", resume=True)
        assert state2.state == "completed"
        assert state2.data.get("finished") is True

    async def test_pipeline_with_cache(self, tmp_path):
        """Stage using cache: second call returns cached result."""
        cache = Cache("integration-cache")
        call_count = {"n": 0}

        async def cached_stage(data: dict, ctx: OrchestratorContext) -> dict:
            cached_val = await cache.get("result")
            if cached_val is not None:
                return {"value": cached_val}
            call_count["n"] += 1
            result = "computed"
            await cache.put("result", result)
            return {"value": result}

        pipeline = Pipeline("cache-test", [Stage("cached", cached_stage)])

        state1 = await run_pipeline(pipeline, initial_data={})
        assert state1.data["value"] == "computed"
        assert call_count["n"] == 1

        state2 = await run_pipeline(pipeline, initial_data={})
        assert state2.data["value"] == "computed"
        assert call_count["n"] == 1

    async def test_rate_limited_pipeline(self):
        """Pipeline respects rate limits."""
        RateLimitRegistry.register("test-limit", rate=5, period_seconds=1.0)
        rl = RateLimitRegistry.get("test-limit")
        call_count = {"n": 0}

        async def rate_limited_stage(data: dict, ctx: OrchestratorContext) -> dict:
            await rl.acquire()
            call_count["n"] += 1
            return {}

        pipeline = Pipeline("rl-test", [Stage("rl", rate_limited_stage)])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.state == "completed"
        assert call_count["n"] == 1
