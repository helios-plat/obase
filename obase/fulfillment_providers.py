"""obase.fulfillment_providers — 内置 obase.FulfillmentProvider 实现。

ManualFulfillmentProvider：不对接真实快递商 API 的兜底 provider，报价固定为
单一 flat-rate 选项，创建面单时生成本地追踪号并记录状态，取消面单是真实的
状态转移（不是 no-op）——同 ManualPaymentProvider 的设计取向：语义跟真实
provider 一致，用于没有真实快递商凭据的环境里跑集成测试。
"""

from __future__ import annotations

import uuid
from typing import Any


class ManualFulfillmentProvider:
    """内存态履约 provider,进程生命周期内维持面单状态。"""

    def __init__(self, *, flat_rate_cents: int = 500, carrier_name: str = "manual") -> None:
        self._flat_rate_cents = flat_rate_cents
        self._carrier_name = carrier_name
        self._labels: dict[str, dict[str, Any]] = {}

    async def get_rates(
        self, *, package: dict[str, Any], address: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [
            {
                "carrier": self._carrier_name,
                "service": "standard",
                "rate_cents": self._flat_rate_cents,
            }
        ]

    async def create_label(self, *, shipment_info: dict[str, Any]) -> dict[str, Any]:
        tracking_number = f"manual_{uuid.uuid4().hex[:16]}"
        self._labels[tracking_number] = {
            "status": "created",
            "shipment_info": shipment_info,
        }
        return {
            "tracking_number": tracking_number,
            "carrier": self._carrier_name,
            "status": "created",
        }

    async def cancel_label(self, *, tracking_number: str) -> bool:
        label = self._labels.get(tracking_number)
        if label is None or label["status"] == "canceled":
            return False
        label["status"] = "canceled"
        return True
