"""OhlcvBar dataclass."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"}
LIST_BAR_LIMIT = 200


class OhlcvStoreError(Exception):
    """Base error for ohlcv_store submodule."""


@dataclass
class OhlcvBar:
    """OHLCV bar data.

    Args:
        ts: Bar open time (UTC).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Base volume.
        quote_volume: Quote volume (optional).
        trades_count: Number of trades (optional).
    """

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    trades_count: int | None = None

    def to_redis_json(self) -> str:
        """Serialize bar to JSON string for cache storage.

        Returns:
            JSON string with ts as ms epoch.

        Example:
            >>> from datetime import datetime, timezone
            >>> bar = OhlcvBar(
            ...     ts=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ...     open=1.0, high=2.0, low=0.5, close=1.5, volume=100.0,
            ... )
            >>> bar.to_redis_json()
            '{"ts": 1704067200000, ...}'
        """
        payload: dict = {
            "ts": int(self.ts.timestamp() * 1000),
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
        }
        if self.quote_volume is not None:
            payload["quote_volume"] = float(self.quote_volume)
        if self.trades_count is not None:
            payload["trades_count"] = int(self.trades_count)
        return json.dumps(payload)
