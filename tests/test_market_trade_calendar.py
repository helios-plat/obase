"""Tests for obase.market.trade_calendar (calendar-table trading-day lookup).

Upstreamed from the Tide consumer line. The important contracts:

* the table name is a **parameter** (a library must not ship one project's
  schema), so it is validated as a SQL identifier before interpolation;
* a missing/None pool, a raising query, or a missing row all degrade to the
  Mon-Fri weekday heuristic rather than raising;
* ``lookup_trading_day`` never applies the heuristic — it returns ``None`` so a
  caller with a better second opinion can take over.
"""

from __future__ import annotations

from datetime import date

import pytest

from obase.market import trade_calendar as cal
from obase.market.trade_calendar import (
    SOURCE_TABLE,
    SOURCE_WEEKDAY_FALLBACK,
    configure_calendar_table,
    is_trading_day,
    lookup_trading_day,
)

TABLE = "some_calendar"


@pytest.fixture(autouse=True)
def _reset_default_table():
    """Keep the process-wide default from leaking between tests."""
    saved = cal._DEFAULT_TABLE
    yield
    cal._DEFAULT_TABLE = saved


class _Row(dict):
    """Row object supporting name-based item access like asyncpg's Record."""

    def __getitem__(self, key):  # noqa: D105
        return dict.__getitem__(self, key)


class _Conn:
    def __init__(self, row):
        self._row = row
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if isinstance(self._row, Exception):
            raise self._row
        return self._row


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, row):
        self.conn = _Conn(row)

    def acquire(self):
        return _Acquire(self.conn)


# ---------------------------------------------------------------------------
# lookup_trading_day — the raw table verdict
# ---------------------------------------------------------------------------


async def test_lookup_returns_true_when_table_says_open():
    pool = _Pool(_Row(is_open=True))
    assert await lookup_trading_day(pool, date(2026, 10, 23), table=TABLE) is True


async def test_lookup_returns_false_when_table_says_closed():
    pool = _Pool(_Row(is_open=False))
    assert await lookup_trading_day(pool, date(2026, 10, 24), table=TABLE) is False


async def test_lookup_returns_none_without_a_pool():
    assert await lookup_trading_day(None, date(2026, 10, 23), table=TABLE) is None


async def test_lookup_returns_none_when_no_row():
    pool = _Pool(None)
    assert await lookup_trading_day(pool, date(2026, 10, 23), table=TABLE) is None


async def test_lookup_returns_none_when_query_raises():
    pool = _Pool(RuntimeError("connection reset"))
    assert await lookup_trading_day(pool, date(2026, 10, 23), table=TABLE) is None


async def test_lookup_uses_the_requested_table_name():
    pool = _Pool(_Row(is_open=True))
    await lookup_trading_day(pool, date(2026, 10, 23), table="my_cal")
    query, _ = pool.conn.calls[0]
    assert "my_cal" in query
    assert "SELECT is_open" in query


async def test_lookup_passes_the_date_as_a_bind_parameter():
    pool = _Pool(_Row(is_open=True))
    await lookup_trading_day(pool, date(2026, 10, 23), table=TABLE)
    _, args = pool.conn.calls[0]
    assert args == (date(2026, 10, 23),)


# ---------------------------------------------------------------------------
# is_trading_day — verdict + weekday fallback
# ---------------------------------------------------------------------------


async def test_is_trading_day_uses_table_when_available():
    pool = _Pool(_Row(is_open=False))
    verdict, source = await is_trading_day(pool, date(2026, 10, 23), table=TABLE)
    assert verdict is False
    assert source == SOURCE_TABLE


async def test_is_trading_day_falls_back_on_weekday():
    verdict, source = await is_trading_day(None, date(2026, 10, 23), table=TABLE)  # Friday
    assert verdict is True
    assert source == SOURCE_WEEKDAY_FALLBACK


async def test_is_trading_day_weekend_is_closed():
    verdict, source = await is_trading_day(None, date(2026, 10, 24), table=TABLE)  # Saturday
    assert verdict is False
    assert source == SOURCE_WEEKDAY_FALLBACK


async def test_is_trading_day_falls_back_on_query_error():
    pool = _Pool(RuntimeError("boom"))
    verdict, source = await is_trading_day(pool, date(2026, 10, 26), table=TABLE)  # Monday
    assert verdict is True
    assert source == SOURCE_WEEKDAY_FALLBACK


# ---------------------------------------------------------------------------
# table-name handling (SQL-identifier validation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["cal; DROP TABLE users", "cal--", "1cal", "a b", ""])
async def test_rejects_unsafe_table_identifiers(bad):
    with pytest.raises(ValueError, match="unsafe table identifier"):
        await lookup_trading_day(None, date(2026, 10, 23), table=bad)


@pytest.mark.parametrize("good", ["cal", "my_cal", "public.cal", "_cal2"])
async def test_accepts_safe_table_identifiers(good):
    assert await lookup_trading_day(None, date(2026, 10, 23), table=good) is None


async def test_requires_a_table_when_no_default_configured():
    cal._DEFAULT_TABLE = None
    with pytest.raises(ValueError, match="no table given"):
        await lookup_trading_day(None, date(2026, 10, 23))


async def test_configured_default_is_used():
    configure_calendar_table("configured_cal")
    pool = _Pool(_Row(is_open=True))
    assert await lookup_trading_day(pool, date(2026, 10, 23)) is True
    query, _ = pool.conn.calls[0]
    assert "configured_cal" in query


def test_configure_rejects_unsafe_identifier():
    with pytest.raises(ValueError, match="unsafe table identifier"):
        configure_calendar_table("bad;drop")


async def test_explicit_table_overrides_the_default():
    configure_calendar_table("default_cal")
    pool = _Pool(_Row(is_open=True))
    await lookup_trading_day(pool, date(2026, 10, 23), table="explicit_cal")
    query, _ = pool.conn.calls[0]
    assert "explicit_cal" in query
    assert "default_cal" not in query
