"""OHLCV writer — double-write to DB (SoT) and cache."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

from obase.ohlcv_store.model import LIST_BAR_LIMIT, VALID_TIMEFRAMES, OhlcvBar, OhlcvStoreError

log = logging.getLogger(__name__)


class DbWriter(Protocol):
    """Protocol for DB write operations."""

    async def execute_insert(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        bars: Sequence[OhlcvBar],
        source: str,
    ) -> int: ...


class CacheWriter(Protocol):
    """Protocol for cache write operations."""

    async def lpush_and_trim(
        self,
        key: str,
        values: list[str],
        max_len: int,
    ) -> int: ...


async def write_ohlcv_bars(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    bars: Sequence[OhlcvBar],
    db_writer: DbWriter,
    cache_writer: CacheWriter | None = None,
    source: str = "default",
) -> tuple[int, int]:
    """Double-write OHLCV bars to DB (SoT) and cache.

    Args:
        exchange: Exchange identifier (e.g. "binance").
        symbol: Canonical symbol (e.g. "BTC-USDT").
        timeframe: Bar timeframe (1m/5m/15m/30m/1h/4h/1d/1w/1M).
        bars: Sequence of OhlcvBar to write.
        db_writer: Protocol for DB persistence (SoT, raises on failure).
        cache_writer: Optional protocol for cache persistence (non-fatal).
        source: Writer identifier for multi-source coordination.

    Returns:
        Tuple of (rows_written_db, rows_written_cache).

    Raises:
        OhlcvStoreError: If symbol is empty or timeframe invalid.
        Exception: If DB write fails (SoT must be writable).

    Example:
        >>> rows_db, rows_cache = await write_ohlcv_bars(
        ...     exchange="binance", symbol="BTC-USDT", timeframe="1d",
        ...     bars=[bar], db_writer=my_db,
        ... )
    """
    if not symbol:
        raise OhlcvStoreError("symbol must not be empty")
    if timeframe not in VALID_TIMEFRAMES:
        raise OhlcvStoreError(f"invalid timeframe: {timeframe}")
    if not bars:
        return (0, 0)

    rows_db = await db_writer.execute_insert(exchange, symbol, timeframe, bars, source)

    rows_cache = 0
    if cache_writer is not None:
        try:
            list_key = f"marketdata:{exchange}:ohlcv_{timeframe}:{symbol}"
            sorted_bars = sorted(bars, key=lambda b: b.ts)
            values = [bar.to_redis_json() for bar in sorted_bars]
            rows_cache = await cache_writer.lpush_and_trim(list_key, values, LIST_BAR_LIMIT)
        except Exception as exc:
            log.warning(
                "ohlcv cache write failed (non-fatal): exchange=%s symbol=%s err=%s",
                exchange,
                symbol,
                exc,
            )

    return (rows_db, rows_cache)
