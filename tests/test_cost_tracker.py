from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from obase.cost_tracker import CostTracker, PricingEntry, PricingTable
from obase.exceptions import BudgetExceeded, PricingNotConfiguredError


def _make_table(*entries: dict) -> PricingTable:
    return PricingTable(entries=[PricingEntry(**e) for e in entries])


class TestPricingTable:
    def test_lookup_found(self):
        table = _make_table(
            {"category": "llm", "provider": "openai", "model_or_tier": "gpt-4", "unit": "token", "price_usd": 0.00003}
        )
        entry = table.lookup("llm", "openai", "gpt-4", "token")
        assert entry is not None
        assert entry.price_usd == 0.00003

    def test_lookup_not_found(self):
        table = _make_table(
            {"category": "llm", "provider": "openai", "model_or_tier": "gpt-4", "unit": "token", "price_usd": 0.00003}
        )
        assert table.lookup("llm", "openai", "gpt-3.5", "token") is None

    def test_from_yaml(self, tmp_path):
        data = [
            {"category": "tts", "provider": "azure", "model_or_tier": "neural", "unit": "char", "price_usd": 0.00001}
        ]
        p = tmp_path / "pricing.yaml"
        p.write_text(yaml.dump(data))
        table = PricingTable.from_yaml(p)
        assert len(table.entries) == 1
        entry = table.lookup("tts", "azure", "neural", "char")
        assert entry is not None


class TestCostTracker:
    def _tracker(self, budget=None, strict=True, trail=None) -> CostTracker:
        table = _make_table(
            {"category": "llm", "provider": "mock", "model_or_tier": "v1", "unit": "token", "price_usd": 0.001}
        )
        return CostTracker(pricing_table=table, budget_usd=budget, strict_pricing=strict, trail=trail)

    def test_record_returns_cost(self):
        ct = self._tracker()
        cost = ct.record("llm", "mock", "v1", "token", 100)
        assert cost == pytest.approx(0.1)
        assert ct.total_usd == pytest.approx(0.1)

    def test_missing_pricing_strict(self):
        """strict_pricing=True missing entry → PricingNotConfiguredError."""
        ct = self._tracker(strict=True)
        with pytest.raises(PricingNotConfiguredError) as exc_info:
            ct.record("llm", "unknown_provider", "v1", "token", 100)
        err = exc_info.value
        assert err.category == "llm"
        assert err.provider == "unknown_provider"
        assert err.model_or_tier == "v1"
        assert err.unit == "token"

    def test_missing_pricing_lenient(self):
        """strict_pricing=False missing entry → records $0 + trail emit pricing_missing."""
        events: list[str] = []

        class FakeTrail:
            def emit(self, event: str, **kwargs):
                events.append(event)

        ct = self._tracker(strict=False, trail=FakeTrail())
        cost = ct.record("llm", "ghost", "v99", "token", 100)
        assert cost == 0.0
        assert ct.total_usd == 0.0
        assert "pricing_missing" in events

    def test_budget_exceeded(self):
        ct = self._tracker(budget=0.05)
        with pytest.raises(BudgetExceeded):
            ct.record("llm", "mock", "v1", "token", 100)

    def test_budget_check_passes(self):
        ct = self._tracker(budget=1.0)
        ct.record("llm", "mock", "v1", "token", 10)
        ct.check_budget()

    def test_summary(self):
        ct = self._tracker()
        ct.record("llm", "mock", "v1", "token", 5)
        s = ct.summary()
        assert "total_usd" in s
        assert "entries" in s
        assert len(s["entries"]) == 1

    def test_cumulative_cost(self):
        ct = self._tracker()
        ct.record("llm", "mock", "v1", "token", 10)
        ct.record("llm", "mock", "v1", "token", 10)
        assert ct.total_usd == pytest.approx(0.02)
