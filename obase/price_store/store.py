"""Price store — cache-first price lookup with DB fallback."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Protocol

log = logging.getLogger(__name__)


class CacheClient(Protocol):
    """Protocol for cache read operations."""

    async def get(self, key: str) -> dict | None: ...
    async def mget(self, keys: list[str]) -> list[dict | None]: ...


class DbClient(Protocol):
    """Protocol for DB price queries."""

    async def get_latest(self, symbol: str) -> Decimal | None: ...
    async def get_yesterday_close(self, symbol: str) -> Decimal | None: ...
    async def get_price_history(self, symbol: str, days: int) -> list[Decimal]: ...


async def get_latest_price(
    *,
    symbol: str,
    cache: CacheClient | None = None,
    db: DbClient | None = None,
) -> Decimal | None:
    """Get latest price for a symbol (cache → DB fallback).

    Args:
        symbol: Asset symbol (uppercased internally).
        cache: Optional cache client.
        db: Optional DB client.

    Returns:
        Latest price as Decimal, or None if unavailable.

    Raises:
        PriceStoreError: Never (best-effort).

    Example:
        >>> price = await get_latest_price(symbol="BTC", cache=my_cache, db=my_db)
    """
    sym = symbol.upper()

    if cache is not None:
        try:
            data = await cache.get(f"market:latest:{sym}")
            if data:
                raw_price = data.get("price") or data.get("close") or data.get("last")
                if raw_price is not None:
                    try:
                        return Decimal(str(raw_price))
                    except InvalidOperation:
                        pass
        except Exception as exc:
            log.warning("redis_price_miss symbol=%s err=%s", sym, exc)

    if db is not None:
        try:
            return await db.get_latest(sym)
        except Exception as exc:
            log.warning("db_price_miss symbol=%s err=%s", sym, exc)

    return None


async def get_prices_batch(
    *,
    symbols: list[str],
    cache: CacheClient | None = None,
    db: DbClient | None = None,
) -> dict[str, Decimal]:
    """Get latest prices for multiple symbols.

    Args:
        symbols: List of asset symbols.
        cache: Optional cache client.
        db: Optional DB client.

    Returns:
        Dict mapping symbol → price (skips unavailable).

    Example:
        >>> prices = await get_prices_batch(symbols=["BTC", "ETH"], cache=c, db=d)
    """
    prices: dict[str, Decimal] = {}
    syms = [s.upper() for s in symbols]
    missing: list[str] = []

    if cache is not None:
        try:
            keys = [f"market:latest:{s}" for s in syms]
            results = await cache.mget(keys)
            for sym, data in zip(syms, results, strict=False):
                if data:
                    raw_price = data.get("price") or data.get("close") or data.get("last")
                    if raw_price is not None:
                        try:
                            prices[sym] = Decimal(str(raw_price))
                            continue
                        except InvalidOperation:
                            pass
                missing.append(sym)
        except Exception as exc:
            log.warning("redis_batch_miss err=%s", exc)
            missing = syms
    else:
        missing = syms

    if db is not None:
        for sym in missing:
            if sym in prices:
                continue
            try:
                p = await db.get_latest(sym)
                if p is not None:
                    prices[sym] = p
            except Exception as exc:
                log.warning("db_batch_miss symbol=%s err=%s", sym, exc)

    return prices


async def get_yesterday_closes(
    *,
    symbols: list[str],
    db: DbClient,
) -> dict[str, Decimal]:
    """Get yesterday's closing prices.

    Args:
        symbols: List of asset symbols.
        db: DB client for historical queries.

    Returns:
        Dict mapping symbol → yesterday close price.

    Example:
        >>> closes = await get_yesterday_closes(symbols=["BTC"], db=my_db)
    """
    result: dict[str, Decimal] = {}
    for sym in symbols:
        try:
            price = await db.get_yesterday_close(sym.upper())
            if price is not None:
                result[sym.upper()] = price
        except Exception as exc:
            log.warning("yesterday_close_miss symbol=%s err=%s", sym, exc)
    return result


async def get_30d_returns_stddev(
    *,
    symbols: list[str],
    db: DbClient,
) -> dict[str, Decimal]:
    """Compute 30-day daily returns standard deviation.

    Args:
        symbols: List of asset symbols.
        db: DB client for price history.

    Returns:
        Dict mapping symbol → daily stddev.

    Example:
        >>> stddevs = await get_30d_returns_stddev(symbols=["BTC"], db=my_db)
    """
    result: dict[str, Decimal] = {}
    for sym in symbols:
        try:
            prices = await db.get_price_history(sym.upper(), days=31)
            if len(prices) < 5:
                continue
            returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
            n = len(returns)
            mean = sum(returns) / n
            variance = sum((r - mean) ** 2 for r in returns) / max(n - 1, 1)
            result[sym.upper()] = variance.sqrt()
        except Exception as exc:
            log.warning("stddev_miss symbol=%s err=%s", sym, exc)
    return result
