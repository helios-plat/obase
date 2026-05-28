"""Tests for obase.ohlcv_store."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from obase.ohlcv_store import (
    OhlcvBar,
    OhlcvStoreError,
    read_ohlcv_list_or_fallback,
    write_ohlcv_bars,
)


class _MockDbWriter:
    def __init__(self) -> None:
        self.written: list = []

    async def execute_insert(
        self, exchange: str, symbol: str, timeframe: str, bars: Sequence[OhlcvBar], source: str
    ) -> int:
        self.written.extend(bars)
        return len(bars)


class _MockCacheWriter:
    def __init__(self) -> None:
        self.stored: list = []

    async def lpush_and_trim(self, key: str, values: list[str], max_len: int) -> int:
        self.stored.extend(values)
        return len(values)


class _MockCacheReader:
    def __init__(self, data: list[dict] | None = None) -> None:
        self._data = data or []

    async def lrange(self, key: str, start: int, stop: int) -> list[dict]:
        return self._data


class _MockDbReader:
    def __init__(self, data: list[dict] | None = None) -> None:
        self._data = data or []

    async def read_bars(self, exchange: str, symbol: str, timeframe: str, limit: int) -> list[dict]:
        return self._data


def _make_bar() -> OhlcvBar:
    return OhlcvBar(
        ts=datetime(2024, 1, 1, tzinfo=UTC),
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1000.0,
    )


def test_ohlcv_bar_to_redis_json():
    bar = _make_bar()
    j = json.loads(bar.to_redis_json())
    assert j["open"] == 100.0
    assert j["close"] == 105.0
    assert "quote_volume" not in j


def test_ohlcv_bar_to_redis_json_with_optional():
    bar = OhlcvBar(
        ts=datetime(2024, 1, 1, tzinfo=UTC),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=50.0,
        quote_volume=75.0,
        trades_count=10,
    )
    j = json.loads(bar.to_redis_json())
    assert j["quote_volume"] == 75.0
    assert j["trades_count"] == 10


@pytest.mark.asyncio
async def test_write_ohlcv_bars_success():
    db = _MockDbWriter()
    cache = _MockCacheWriter()
    bar = _make_bar()
    rows_db, rows_cache = await write_ohlcv_bars(
        exchange="binance",
        symbol="BTC-USDT",
        timeframe="1d",
        bars=[bar],
        db_writer=db,
        cache_writer=cache,
    )
    assert rows_db == 1
    assert rows_cache == 1


@pytest.mark.asyncio
async def test_write_ohlcv_bars_empty():
    db = _MockDbWriter()
    rows_db, rows_cache = await write_ohlcv_bars(
        exchange="binance",
        symbol="BTC-USDT",
        timeframe="1d",
        bars=[],
        db_writer=db,
    )
    assert rows_db == 0
    assert rows_cache == 0


@pytest.mark.asyncio
async def test_write_ohlcv_bars_invalid_timeframe():
    db = _MockDbWriter()
    with pytest.raises(OhlcvStoreError):
        await write_ohlcv_bars(
            exchange="binance",
            symbol="BTC-USDT",
            timeframe="2d",
            bars=[_make_bar()],
            db_writer=db,
        )


@pytest.mark.asyncio
async def test_read_cache_hit():
    cache = _MockCacheReader([{"ts": 1704067200000, "close": 105.0}])
    bars = await read_ohlcv_list_or_fallback(
        exchange="binance",
        symbol="BTC-USDT",
        timeframe="1d",
        cache_reader=cache,
    )
    assert len(bars) == 1


@pytest.mark.asyncio
async def test_read_db_fallback():
    cache = _MockCacheReader([])
    db = _MockDbReader([{"ts": 1704067200000, "close": 105.0}])
    bars = await read_ohlcv_list_or_fallback(
        exchange="binance",
        symbol="BTC-USDT",
        timeframe="1d",
        cache_reader=cache,
        db_reader=db,
    )
    assert len(bars) == 1


@pytest.mark.asyncio
async def test_read_all_miss():
    bars = await read_ohlcv_list_or_fallback(
        exchange="binance",
        symbol="BTC-USDT",
        timeframe="1d",
    )
    assert bars == []


@pytest.mark.asyncio
async def test_read_invalid_timeframe():
    with pytest.raises(OhlcvStoreError):
        await read_ohlcv_list_or_fallback(
            exchange="binance",
            symbol="BTC-USDT",
            timeframe="invalid",
        )


def test_ohlcv_store_error_is_exception():
    assert issubclass(OhlcvStoreError, Exception)
