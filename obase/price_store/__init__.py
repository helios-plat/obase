"""price_store — Multi-market latest price lookup (cache → DB fallback).

Provides get_latest_price, get_prices_batch, get_yesterday_closes,
get_30d_returns_stddev with injected IO dependencies.

depends_on_external: (none — IO injected)
"""

from __future__ import annotations

from obase.price_store.store import (
    get_30d_returns_stddev,
    get_latest_price,
    get_prices_batch,
    get_yesterday_closes,
)

__all__ = [
    "get_latest_price",
    "get_prices_batch",
    "get_yesterday_closes",
    "get_30d_returns_stddev",
    "PriceStoreError",
]


class PriceStoreError(Exception):
    """Base error for price_store submodule."""
