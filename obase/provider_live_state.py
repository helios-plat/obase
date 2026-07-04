"""C5 — Provider 健康/余额活状态 + 余额探针。

`ProviderContract`(E1)是**静态**成本;L0 路由要从"盲的静态表"升级为"交易所",还需
**动态**的余额/健康信号(fal/DashScope 双欠费 403 就是这个盲区的账单)。本模块补:
  - `ProviderLiveState`:读写 `{name: {balance_usd, health, updated_at}}`,供路由/熔断读。
  - `Rolling403Rate`:滚动窗口 403 率 → 健康代理(fal 无余额 API 时用)。
  - `fal_balance_probe`:查 fal 余额,查不到降级为 403 率代理。

**告警归 Aegis**(消费 `ProviderLiveState`),不在本模块。
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any


class Rolling403Rate:
    """滚动窗口内 403 占比 → 健康代理(`health = 1 - rate`)。"""

    def __init__(self, window: int = 50) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        self._events: deque[bool] = deque(maxlen=window)

    def record(self, *, is_403: bool) -> None:
        self._events.append(bool(is_403))

    def rate(self) -> float:
        return sum(self._events) / len(self._events) if self._events else 0.0

    def health(self) -> float:
        return 1.0 - self.rate()


class ProviderLiveState:
    """provider 动态状态存储:`{name: {balance_usd, health, updated_at}}`。

    进程内;持久化(Aegis 供给)后置。这是 L0 从"数据表"到"交易所"缺的那份"活的状态"。
    """

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def update(
        self,
        name: str,
        *,
        balance_usd: float | None = None,
        health: float | None = None,
        updated_at: float | None = None,
    ) -> None:
        s = self._state.setdefault(name, {})
        if balance_usd is not None:
            s["balance_usd"] = float(balance_usd)
        if health is not None:
            s["health"] = float(health)
        s["updated_at"] = updated_at if updated_at is not None else time.time()

    def get(self, name: str) -> dict[str, Any]:
        return dict(self._state.get(name, {}))

    def healthy(self, name: str, *, min_balance_usd: float = 0.0, min_health: float = 0.5) -> bool:
        """可否路由到该 provider:余额(若已知)≥ 阈 且 健康 ≥ 阈。

        无记录 → True(未探到不误杀,退回静态表现行为)。
        """
        s = self._state.get(name)
        if not s:
            return True
        bal = s.get("balance_usd")
        if bal is not None and bal < min_balance_usd:
            return False
        return s.get("health", 1.0) >= min_health


async def fal_balance_probe(*, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """探 fal 余额。

    → ``{"balance_usd": float | None, "ok": bool, "source": "api" | "403_rate" | "unknown"}``

    优先查配置的余额端点(``config["FAL_BALANCE_URL"]`` + ``["FAL_API_KEY"]``);查不到/未配
    则用滚动 403 率代理(``config["error_rate_403"]``,阈 ``max_403_rate`` 默认 0.5);
    都无 → ``source="unknown"``、``ok=True``(不误杀)。告警由 Aegis 消费,不在此。
    """
    config = config or {}
    endpoint = config.get("FAL_BALANCE_URL")
    api_key = config.get("FAL_API_KEY")
    min_balance = float(config.get("min_balance_usd", 0.0))

    if endpoint and api_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(endpoint, headers={"Authorization": f"Key {api_key}"})
                resp.raise_for_status()
                data = resp.json()
                raw = data.get("balance_usd", data.get("balance"))
                bal = float(raw) if raw is not None else None
                if bal is not None:
                    return {"balance_usd": bal, "ok": bal > min_balance, "source": "api"}
        except Exception:
            pass  # 端点不可达/无鉴权 → 降级 403 率代理

    rate = config.get("error_rate_403")
    if rate is not None:
        max_rate = float(config.get("max_403_rate", 0.5))
        return {"balance_usd": None, "ok": float(rate) < max_rate, "source": "403_rate"}

    return {"balance_usd": None, "ok": True, "source": "unknown"}
