"""PB-specific tests: verify no silent fallbacks anywhere in obase."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from obase.cache import Cache
from obase.cost_tracker import CostTracker, PricingTable
from obase.exceptions import (
    BudgetExceeded,
    CacheError,
    PricingNotConfiguredError,
    ProviderNotFoundError,
)
from obase.provider_registry import ProviderRegistry


class TestNoSilentFallback:
    async def test_cache_put_failure_raises(self):
        """Cache put failure raises CacheError, not silently swallowed."""
        c = Cache("nsf-cache")
        with patch("pathlib.Path.write_bytes", side_effect=OSError("no space")):
            with pytest.raises(CacheError):
                await c.put("k", "v")

    async def test_cache_get_corrupt_raises(self):
        """Corrupt cache file raises CacheError on get, not silently ignored."""
        c = Cache("nsf-corrupt")
        path = c._key_path("bad_key")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"garbage bytes that are not pickle")
        with pytest.raises(CacheError):
            await c.get("bad_key")

    def test_provider_not_found_raises_not_returns_none(self):
        """Provider.get raises ProviderNotFoundError, never returns None."""
        with pytest.raises(ProviderNotFoundError):
            ProviderRegistry.get().generic("nonexistent", "category")

    def test_budget_exceeded_raises_not_continues(self):
        """BudgetExceeded is raised by record(), not silently skipped."""
        from obase.cost_tracker import PricingEntry
        table = PricingTable(
            entries=[PricingEntry(category="a", provider="b", model_or_tier="c",
                                  unit="u", price_usd=1.0)]
        )
        ct = CostTracker(pricing_table=table, budget_usd=0.5, strict_pricing=True)
        with pytest.raises(BudgetExceeded):
            ct.record("a", "b", "c", "u", 1)

    def test_pricing_missing_strict_raises(self):
        """strict_pricing=True with missing entry raises PricingNotConfiguredError."""
        ct = CostTracker(pricing_table=PricingTable(), strict_pricing=True)
        with pytest.raises(PricingNotConfiguredError):
            ct.record("cat", "prov", "model", "unit", 10)

    def test_pricing_missing_lenient_records_zero(self):
        """strict_pricing=False records $0 (not a random number, not an error)."""
        ct = CostTracker(pricing_table=PricingTable(), strict_pricing=False)
        cost = ct.record("cat", "prov", "model", "unit", 10)
        assert cost == 0.0
        assert ct.total_usd == 0.0

    async def test_orchestrator_budget_exceeded_returns_failed_state(self):
        """BudgetExceeded inside a stage → state=failed, not propagated to caller."""
        from obase.exceptions import BudgetExceeded
        from obase.orchestrator import OrchestratorContext, Pipeline, Stage, run_pipeline

        async def costly_stage(data: dict, ctx: OrchestratorContext) -> dict:
            raise BudgetExceeded("over limit")

        pipeline = Pipeline("budget_test", [Stage("costly", costly_stage)])
        state = await run_pipeline(pipeline, initial_data={})
        assert state.state == "failed"

    def test_rate_limiter_not_found_raises_obase_error(self):
        """RateLimitRegistry.get on unknown name raises OBaseError, not returns None."""
        from obase.exceptions import OBaseError
        from obase.rate_limit import RateLimitRegistry
        with pytest.raises(OBaseError, match="not found"):
            RateLimitRegistry.get("unknown-limiter-xyz")
