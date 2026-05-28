"""OHLCV reader — multi-tier fallback read (cache → DB → empty)."""

from __future__ import annotations

import logging
from typing import Protocol

from obase.ohlcv_store.model import LIST_BAR_LIMIT, VALID_TIMEFRAMES, OhlcvStoreError

log = logging.getLogger(__name__)


class CacheReader(Protocol):
    """Protocol for cache read operations."""

    async def lrange(self, key: str, start: int, stop: int) -> list[dict]: ...


class DbReader(Protocol):
    """Protocol for DB read operations."""

    async def read_bars(
        self, exchange: str, symbol: str, timeframe: str, limit: int
    ) -> list[dict]: ...


async def read_ohlcv_list_or_fallback(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    limit: int = LIST_BAR_LIMIT,
    cache_reader: CacheReader | None = None,
    db_reader: DbReader | None = None,
) -> list[dict]:
    """Read OHLCV bars with cache + DB fallback chain.

    Priority:
        1. Cache hit → return bars.
        2. DB query → return rows (newest first).
        3. Empty list (caller decides external fallback).

    Args:
        exchange: Exchange identifier.
        symbol: Canonical symbol.
        timeframe: Bar timeframe.
        limit: Maximum bars to return.
        cache_reader: Optional cache reader protocol.
        db_reader: Optional DB reader protocol.

    Returns:
        List of bar dicts (newest first), or empty list.

    Raises:
        OhlcvStoreError: If symbol is empty or timeframe invalid.

    Example:
        >>> bars = await read_ohlcv_list_or_fallback(
        ...     exchange="binance", symbol="BTC-USDT", timeframe="1d",
        ...     cache_reader=my_cache, db_reader=my_db,
        ... )
    """
    if not symbol:
        raise OhlcvStoreError("symbol must not be empty")
    if timeframe not in VALID_TIMEFRAMES:
        raise OhlcvStoreError(f"invalid timeframe: {timeframe}")

    # 1. Cache
    if cache_reader is not None:
        try:
            list_key = f"marketdata:{exchange}:ohlcv_{timeframe}:{symbol}"
            bars = await cache_reader.lrange(list_key, 0, limit - 1)
            if bars:
                log.debug(
                    "ohlcv_reader.cache_hit exchange=%s symbol=%s tf=%s n=%d",
                    exchange,
                    symbol,
                    timeframe,
                    len(bars),
                )
                return bars
        except Exception as exc:
            log.warning(
                "ohlcv_reader.cache_read_failed exchange=%s symbol=%s err=%s",
                exchange,
                symbol,
                exc,
            )

    # 2. DB
    if db_reader is not None:
        try:
            bars = await db_reader.read_bars(exchange, symbol, timeframe, limit)
            if bars:
                log.debug(
                    "ohlcv_reader.db_hit exchange=%s symbol=%s tf=%s n=%d",
                    exchange,
                    symbol,
                    timeframe,
                    len(bars),
                )
                return bars
        except Exception as exc:
            log.warning(
                "ohlcv_reader.db_read_failed exchange=%s symbol=%s err=%s",
                exchange,
                symbol,
                exc,
            )

    # 3. All miss
    log.info(
        "ohlcv_reader.all_miss exchange=%s symbol=%s tf=%s",
        exchange,
        symbol,
        timeframe,
    )
    return []
