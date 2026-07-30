"""obase.payment_providers — 内置 obase.PaymentProvider 实现。

ManualPaymentProvider：线下/货到付款场景的兜底 provider（真实商户对接见
Stripe/PayPal 等外部 SDK，不在本模块）。不移动真实货币，但状态机语义与真实
支付网关一致（未 authorize 不能 capture、未 capture 不能 refund、已
capture/refund 不能 cancel），便于在没有真实网关凭据的环境里跑集成测试。
"""

from __future__ import annotations

import uuid
from typing import Any


class ManualPaymentProvider:
    """内存态支付 provider，进程生命周期内维持 intent 状态机。"""

    def __init__(self) -> None:
        self._intents: dict[str, dict[str, Any]] = {}

    async def authorize(
        self, *, amount: int, currency: str, meta: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        intent_id = f"manual_{uuid.uuid4().hex[:16]}"
        self._intents[intent_id] = {
            "status": "authorized",
            "amount": amount,
            "currency": currency,
            "meta": meta or {},
        }
        return {"intent_id": intent_id, "status": "authorized", "amount": amount}

    async def capture(self, *, intent_id: str) -> dict[str, Any]:
        intent = self._require_intent(intent_id)
        if intent["status"] != "authorized":
            raise ValueError(f"cannot capture intent {intent_id!r} in status {intent['status']!r}")
        intent["status"] = "captured"
        return {"intent_id": intent_id, "status": "captured", "amount": intent["amount"]}

    async def refund(self, *, intent_id: str, amount: int) -> dict[str, Any]:
        intent = self._require_intent(intent_id)
        if intent["status"] != "captured":
            raise ValueError(f"cannot refund intent {intent_id!r} in status {intent['status']!r}")
        if amount > intent["amount"]:
            raise ValueError(f"refund amount {amount} exceeds captured amount {intent['amount']}")
        intent["status"] = "refunded"
        return {"intent_id": intent_id, "status": "refunded", "amount": amount}

    async def cancel(self, *, intent_id: str) -> dict[str, Any]:
        intent = self._require_intent(intent_id)
        if intent["status"] != "authorized":
            raise ValueError(f"cannot cancel intent {intent_id!r} in status {intent['status']!r}")
        intent["status"] = "canceled"
        return {"intent_id": intent_id, "status": "canceled"}

    def _require_intent(self, intent_id: str) -> dict[str, Any]:
        intent = self._intents.get(intent_id)
        if intent is None:
            raise ValueError(f"unknown manual payment intent: {intent_id!r}")
        return intent
