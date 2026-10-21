"""A-share / exchange trading-calendar primitives.

3O layer: obase (cross-cutting infrastructure — DB-backed calendar plumbing).

See :mod:`obase.market.trade_calendar`. The calendar table name is a parameter
(``table=``), because a library must not ship one project's physical schema
(SPEC §2.4).
"""

from __future__ import annotations

from obase.market.trade_calendar import (
    SOURCE_TABLE,
    SOURCE_WEEKDAY_FALLBACK,
    configure_calendar_table,
    is_trading_day,
    lookup_trading_day,
)

__all__ = [
    "SOURCE_TABLE",
    "SOURCE_WEEKDAY_FALLBACK",
    "configure_calendar_table",
    "is_trading_day",
    "lookup_trading_day",
]
