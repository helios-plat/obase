"""obase.tax_providers — 内置 obase.TaxProvider 实现。

FlatRateTaxProvider：不对接真实税务 API(Avalara/TaxJar)的兜底 provider,
对每个 item 按同一固定税率计算,不做地址级税率查表(那是真实 provider 的职责)。
"""

from __future__ import annotations

from typing import Any


class FlatRateTaxProvider:
    """按固定百分比税率计算,不区分地址。"""

    def __init__(self, *, rate_percent: float) -> None:
        if rate_percent < 0:
            raise ValueError(f"rate_percent must be >= 0, got {rate_percent}")
        self._rate_percent = rate_percent

    async def calculate(self, *, address: dict[str, Any], items: list[Any]) -> dict[str, Any]:
        lines: list[dict[str, Any]] = []
        total_tax_cents = 0
        for item in items:
            amount_cents = int(item["amount_cents"])
            tax_cents = round(amount_cents * self._rate_percent / 100)
            total_tax_cents += tax_cents
            lines.append({**item, "tax_cents": tax_cents})

        return {
            "tax_cents": total_tax_cents,
            "rate_percent": self._rate_percent,
            "lines": lines,
        }
