from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

# ── Module-level lightweight cost accumulator (stdlib only, no extra deps) ──

@dataclass
class CostRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


_records: list[CostRecord] = []
_lock = Lock()


def track(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    record = CostRecord(provider, model, input_tokens, output_tokens, cost_usd)
    with _lock:
        _records.append(record)
    try:
        from obase import logging as _olog
        _olog.info(
            "obase.cost_tracker.track",
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
    except Exception:
        pass


def total_cost() -> float:
    with _lock:
        return sum(r.cost_usd for r in _records)


def get_records() -> list[CostRecord]:
    with _lock:
        return list(_records)


def reset() -> None:
    with _lock:
        _records.clear()


# ── Legacy Helios CostTracker (requires structlog + pydantic + yaml) ──

try:
    import structlog
    import yaml

    from obase._types import OBaseModel
    from obase.exceptions import BudgetExceeded, PricingNotConfiguredError

    _log = structlog.get_logger()

    class PricingEntry(OBaseModel):
        category: str
        provider: str
        model_or_tier: str
        unit: str
        price_usd: float

    class PricingTable(OBaseModel):
        entries: list[PricingEntry] = []

        @classmethod
        def from_yaml(cls, path: Path) -> "PricingTable":
            with path.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            return cls(entries=[PricingEntry(**e) for e in (raw or [])])

        def lookup(
            self,
            category: str,
            provider: str,
            model_or_tier: str,
            unit: str,
        ) -> "PricingEntry | None":
            for entry in self.entries:
                if (
                    entry.category == category
                    and entry.provider == provider
                    and entry.model_or_tier == model_or_tier
                    and entry.unit == unit
                ):
                    return entry
            return None

    class CostTracker:
        """Track spend across categories/providers and enforce a budget ceiling."""

        def __init__(
            self,
            pricing_table: "PricingTable | None" = None,
            budget_usd: float | None = None,
            strict_pricing: bool = True,
            trail: Any | None = None,
        ) -> None:
            self._table = pricing_table or PricingTable()
            self._budget = budget_usd
            self._strict = strict_pricing
            self._trail = trail
            self._total_usd: float = 0.0
            self._entries: list[dict[str, Any]] = []

        @property
        def total_usd(self) -> float:
            return self._total_usd

        def record(
            self,
            category: str,
            provider: str,
            model_or_tier: str,
            unit: str,
            quantity: float,
        ) -> float:
            """Record usage and return the cost in USD."""
            entry = self._table.lookup(category, provider, model_or_tier, unit)
            if entry is None:
                if self._strict:
                    raise PricingNotConfiguredError(category, provider, model_or_tier, unit)
                _log.warning(
                    "obase.cost_tracker.pricing_missing",
                    category=category,
                    provider=provider,
                    model_or_tier=model_or_tier,
                    unit=unit,
                )
                if self._trail is not None:
                    self._trail.emit(
                        "pricing_missing",
                        category=category,
                        provider=provider,
                        model_or_tier=model_or_tier,
                        unit=unit,
                    )
                cost = 0.0
            else:
                cost = entry.price_usd * quantity

            self._total_usd += cost
            self._entries.append(
                {
                    "category": category,
                    "provider": provider,
                    "model_or_tier": model_or_tier,
                    "unit": unit,
                    "quantity": quantity,
                    "cost_usd": cost,
                }
            )

            if self._budget is not None and self._total_usd > self._budget:
                raise BudgetExceeded(
                    f"Budget ${self._budget:.4f} exceeded (total=${self._total_usd:.4f})"
                )

            return cost

        def check_budget(self) -> None:
            """Raise BudgetExceeded if current total exceeds the budget."""
            if self._budget is not None and self._total_usd > self._budget:
                raise BudgetExceeded(
                    f"Budget ${self._budget:.4f} exceeded (total=${self._total_usd:.4f})"
                )

        def summary(self) -> dict[str, Any]:
            return {"total_usd": self._total_usd, "entries": list(self._entries)}

except ImportError:
    pass
