"""Trading-day lookup against a calendar table (obase infrastructure).

3O layer: obase (cross-cutting infrastructure: DB access + market-calendar
plumbing).

Answers "is calendar date ``d`` a trading day?" from a calendar table with the
standard shape::

    cal_date        DATE PRIMARY KEY
    is_open         BOOLEAN NOT NULL
    pretrade_date   DATE
    source          VARCHAR(32)   -- provenance of the row, e.g. 'exchange_cal'

The table name is a parameter, not a constant: a library must not ship one
project's physical schema (SPEC §2.4 — no project-anchored names). Pass the
name your project uses via ``table=``.

The pool is duck-typed as an asyncpg-style pool: ``pool.acquire()`` must be
usable as an async context manager yielding a connection with
``await conn.fetchrow(query, *args)`` where the row supports name-based item
access (``row["is_open"]``). obase does not import asyncpg itself.

Fallback contract: when ``pool`` is ``None``, any query exception is raised, or
no row exists for ``d`` (calendar data gap), the answer degrades to the Mon–Fri
weekday heuristic and ``source`` reports where it came from.

:func:`lookup_trading_day` is the raw calendar verdict without the weekday
fallback (``None`` = the table cannot answer). Probe chains that have a better
second opinion than the weekday heuristic (latest-quote timestamps, see
``oskill.market.trading_day_probe``) consume it instead of
:func:`is_trading_day`, so the calendar lookup stays single-sourced here.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Protocol

__all__ = [
    "SOURCE_TABLE",
    "SOURCE_WEEKDAY_FALLBACK",
    "configure_calendar_table",
    "is_trading_day",
    "lookup_trading_day",
]

#: ``source`` tag: the answer came from the calendar table.
SOURCE_TABLE = "calendar_table"
#: ``source`` tag: the Mon–Fri weekday heuristic was used instead.
SOURCE_WEEKDAY_FALLBACK = "weekday_fallback"

#: Process-wide default calendar table. Set once at application bootstrap with
#: :func:`configure_calendar_table` so call sites stay short. A library cannot
#: know a project's physical schema, so there is deliberately no built-in
#: default (SPEC §2.4).
_DEFAULT_TABLE: str | None = None


def configure_calendar_table(table: str) -> None:
    """Set the process-wide default calendar table.

    Call once during application bootstrap. Every :func:`lookup_trading_day` /
    :func:`is_trading_day` call that omits ``table=`` then uses this value,
    which keeps call sites free of a repeated schema constant.

    Args:
        table: Calendar table name (validated as a safe SQL identifier).

    Raises:
        ValueError: if ``table`` is not a safe SQL identifier.
    """
    global _DEFAULT_TABLE
    _cal_query(table)  # validate eagerly so misconfiguration fails at startup
    _DEFAULT_TABLE = table


def _resolve_table(table: str | None) -> str:
    """Return ``table`` or the configured default, validating either way."""
    resolved = table if table is not None else _DEFAULT_TABLE
    if resolved is None:
        raise ValueError(
            "trade_calendar: no table given and no default configured — "
            "call obase.market.configure_calendar_table(...) at bootstrap "
            "or pass table= explicitly"
        )
    _cal_query(resolved)  # validate
    return resolved


#: Identifier allow-list for the ``table=`` parameter. The table name cannot be
#: a bind parameter, so it is validated against this pattern instead of being
#: interpolated blindly.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _cal_query(table: str) -> str:
    """Build the calendar query for ``table``, rejecting unsafe identifiers."""
    if not _IDENT_RE.match(table):
        raise ValueError(f"trade_calendar: unsafe table identifier: {table!r}")
    return f"SELECT is_open FROM {table} WHERE cal_date = $1"


class _Connection(Protocol):
    """asyncpg-style connection (``fetchrow`` returns a row or ``None``)."""

    async def fetchrow(self, query: str, *args: object) -> Any: ...


class _Pool(Protocol):
    """asyncpg-style pool whose ``acquire()`` yields an async CM."""

    def acquire(self) -> Any: ...


def _weekday_fallback(d: date) -> tuple[bool, str]:
    """Mon–Fri weekday heuristic (Sat/Sun are never trading days)."""
    return d.weekday() < 5, SOURCE_WEEKDAY_FALLBACK


async def lookup_trading_day(
    pool: _Pool | None,
    d: date,
    *,
    table: str | None = None,
) -> bool | None:
    """Return the calendar-table verdict for ``d``, or ``None``.

    ``None`` means the calendar cannot answer: ``pool`` is ``None``, the query
    raised, or no row exists for ``d`` (calendar data gap). No weekday
    heuristic is applied here; callers decide how to fill the gap.

    Args:
        pool: asyncpg-style connection pool, or ``None``.
        d: Calendar date to check (a bare ``date``).
        table: Calendar table name. Defaults to the value set by
            :func:`configure_calendar_table`.

    Returns:
        ``True`` / ``False`` from the table's ``is_open``, or ``None``.

    Raises:
        ValueError: if ``table`` is not a safe SQL identifier.
    """
    query = _cal_query(_resolve_table(table))
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, d)
    except Exception:
        return None
    if row is None:
        return None
    return bool(row["is_open"])


async def is_trading_day(
    pool: _Pool | None,
    d: date,
    *,
    table: str | None = None,
) -> tuple[bool, str]:
    """Return ``(is_trading_day, source)`` for calendar date ``d``.

    Looks the date up in ``table`` via an asyncpg-style pool. ``source`` is
    :data:`SOURCE_TABLE` when the table answered; otherwise
    :data:`SOURCE_WEEKDAY_FALLBACK`, used when ``pool`` is ``None``, the query
    raises, or no row exists for ``d`` (calendar data gap).

    Args:
        pool: asyncpg-style connection pool, or ``None`` to force fallback.
        d: Calendar date to check (any timezone; a bare ``date``).
        table: Calendar table name. Defaults to the value set by
            :func:`configure_calendar_table`.

    Returns:
        Tuple ``(is_trading_day, source)`` where ``source`` is either
        :data:`SOURCE_TABLE` or :data:`SOURCE_WEEKDAY_FALLBACK`.

    Raises:
        ValueError: if ``table`` is not a safe SQL identifier.
    """
    verdict = await lookup_trading_day(pool, d, table=table)
    if verdict is None:
        return _weekday_fallback(d)
    return verdict, SOURCE_TABLE
