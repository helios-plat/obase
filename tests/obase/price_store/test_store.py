"""Tests for obase.price_store."""

from __future__ import annotations

from decimal import Decimal

import pytest

from obase.price_store import (
    PriceStoreError,
    get_30d_returns_stddev,
    get_latest_price,
    get_prices_batch,
    get_yesterday_closes,
)


class _MockCache:
    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    async def get(self, key: str) -> dict | None:
        return self._data.get(key)

    async def mget(self, keys: list[str]) -> list[dict | None]:
        return [self._data.get(k) for k in keys]


class _MockDb:
    def __init__(self, prices: dict | None = None, history: dict | None = None) -> None:
        self._prices = prices or {}
        self._history = history or {}

    async def get_latest(self, symbol: str) -> Decimal | None:
        return self._prices.get(symbol)

    async def get_yesterday_close(self, symbol: str) -> Decimal | None:
        return self._prices.get(f"{symbol}_yesterday")

    async def get_price_history(self, symbol: str, days: int) -> list[Decimal]:
        return self._history.get(symbol, [])


@pytest.mark.asyncio
async def test_get_latest_price_from_cache():
    cache = _MockCache({"market:latest:BTC": {"price": "50000"}})
    price = await get_latest_price(symbol="BTC", cache=cache)
    assert price == Decimal("50000")


@pytest.mark.asyncio
async def test_get_latest_price_db_fallback():
    cache = _MockCache({})
    db = _MockDb(prices={"BTC": Decimal("49000")})
    price = await get_latest_price(symbol="BTC", cache=cache, db=db)
    assert price == Decimal("49000")


@pytest.mark.asyncio
async def test_get_latest_price_all_miss():
    price = await get_latest_price(symbol="BTC")
    assert price is None


@pytest.mark.asyncio
async def test_get_prices_batch_mixed():
    cache = _MockCache({"market:latest:BTC": {"price": "50000"}})
    db = _MockDb(prices={"ETH": Decimal("3000")})
    prices = await get_prices_batch(symbols=["BTC", "ETH"], cache=cache, db=db)
    assert prices["BTC"] == Decimal("50000")
    assert prices["ETH"] == Decimal("3000")


@pytest.mark.asyncio
async def test_get_prices_batch_empty():
    prices = await get_prices_batch(symbols=["XYZ"])
    assert prices == {}


@pytest.mark.asyncio
async def test_get_yesterday_closes():
    db = _MockDb(prices={"BTC_yesterday": Decimal("48000")})
    closes = await get_yesterday_closes(symbols=["BTC"], db=db)
    assert closes["BTC"] == Decimal("48000")


@pytest.mark.asyncio
async def test_get_30d_returns_stddev_sufficient_data():
    prices = [Decimal(str(100 + i)) for i in range(31)]
    db = _MockDb(history={"BTC": prices})
    result = await get_30d_returns_stddev(symbols=["BTC"], db=db)
    assert "BTC" in result
    assert result["BTC"] > 0


@pytest.mark.asyncio
async def test_get_30d_returns_stddev_insufficient_data():
    db = _MockDb(history={"BTC": [Decimal("100"), Decimal("101")]})
    result = await get_30d_returns_stddev(symbols=["BTC"], db=db)
    assert "BTC" not in result


def test_price_store_error_is_exception():
    assert issubclass(PriceStoreError, Exception)
