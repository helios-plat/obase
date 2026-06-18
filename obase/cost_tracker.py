from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml

from obase._types import OBaseModel
from obase.exceptions import BudgetExceeded, PricingNotConfiguredError

log = structlog.get_logger()


class PricingEntry(OBaseModel):
    category: str
    provider: str
    model_or_tier: str
    unit: str
    price_usd: float


class PricingTable(OBaseModel):
    entries: list[PricingEntry] = []

    @classmethod
    def from_yaml(cls, path: Path) -> PricingTable:
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        return cls(entries=[PricingEntry(**e) for e in (raw or [])])

    def lookup(
        self,
        category: str,
        provider: str,
        model_or_tier: str,
        unit: str,
    ) -> PricingEntry | None:
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
        pricing_table: PricingTable | None = None,
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
            log.warning(
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


# ---------------------------------------------------------------------------
# StepUsage / CostBreakdown — 多步聚合所需共享类型
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class StepUsage:
    """单步骤用量描述。"""
    step: str        # "llm" / "video" / "audio" / "avatar"
    provider: str
    usage: float
    unit: str
    tier: str | None = None
    category: str = "default"  # provider category（llm/video/audio/image_gen等）


@dataclass
class CostBreakdown:
    """多步骤成本分解。"""
    per_step: dict[str, Decimal] = field(default_factory=dict)
    total: Decimal = Decimal("0")
    currency: str = "USD"


# ---------------------------------------------------------------------------
# PricingTable 扩展：动态 register_pricing
# ---------------------------------------------------------------------------

def _pricing_table_register(
    self,
    provider: str,
    *,
    unit: str,
    price_per_unit: float,
    category: str = "default",
    tier: str | None = None,
    metadata: dict | None = None,
) -> None:
    """动态注册单价（替代 YAML 文件加载）。

    Example:
        >>> table = PricingTable()
        >>> table.register_pricing("fal", unit="second", price_per_unit=0.04, tier="fast")
    """
    entry = PricingEntry(
        category=category,
        provider=provider,
        model_or_tier=tier or "default",
        unit=unit,
        price_usd=price_per_unit,
    )
    # 覆盖已有同 key 条目
    self.entries = [
        e for e in self.entries
        if not (e.category == category and e.provider == provider
                and e.model_or_tier == (tier or "default") and e.unit == unit)
    ]
    self.entries.append(entry)

PricingTable.register_pricing = _pricing_table_register


# ---------------------------------------------------------------------------
# CostTracker 扩展：estimate / estimate_steps / reference 字段
# ---------------------------------------------------------------------------

def _tracker_estimate(
    self,
    provider: str,
    *,
    usage: float,
    category: str = "default",
    tier: str | None = None,
    unit: str,
) -> Decimal:
    """预估单 provider 成本（不记录，纯计算）。

    Example:
        >>> cost = tracker.estimate("fal", usage=10.0, unit="second", tier="fast")
    """
    entry = self._table.lookup(category, provider, tier or "default", unit)
    if entry is None:
        return Decimal("0")
    return Decimal(str(entry.price_usd * usage))

def _tracker_estimate_steps(self, steps: list[StepUsage]) -> CostBreakdown:
    """多步聚合成本预估（不记录，纯计算）。

    Example:
        >>> breakdown = tracker.estimate_steps([
        ...     StepUsage("llm", "qwen3", 1000, "1k_token"),
        ...     StepUsage("video", "wan", 10.0, "second"),
        ... ])
    """
    per_step: dict[str, Decimal] = {}
    total = Decimal("0")
    for s in steps:
        cost = _tracker_estimate(
            self, s.provider,
            usage=s.usage, unit=s.unit,
            tier=s.tier,
        )
        per_step[s.step] = per_step.get(s.step, Decimal("0")) + cost
        total += cost
    return CostBreakdown(per_step=per_step, total=total)

CostTracker.estimate = _tracker_estimate
CostTracker.estimate_steps = _tracker_estimate_steps


# ---------------------------------------------------------------------------
# C3 货币换算（通用，不含业务汇率）
# ---------------------------------------------------------------------------

def convert_currency(
    amount: Decimal,
    *,
    from_cur: str,
    to_cur: str,
    rate: float,
) -> Decimal:
    """货币换算（调用方提供汇率，主库不硬编码汇率值）。

    Args:
        amount: 原始金额。
        from_cur: 原始货币代码（如 "USD"）。
        to_cur: 目标货币代码（如 "CNY" / "credits"）。
        rate: 兑换率（1 from_cur = rate to_cur）。

    Returns:
        换算后金额（Decimal）。

    Raises:
        ValueError: rate <= 0。

    Example:
        >>> credits = convert_currency(Decimal("1.5"), from_cur="USD", to_cur="credits", rate=100)
        >>> # → Decimal("150.0")
    """
    if rate <= 0:
        raise ValueError(f"rate must be positive, got {rate}")
    return (amount * Decimal(str(rate))).quantize(Decimal("0.000001"))
