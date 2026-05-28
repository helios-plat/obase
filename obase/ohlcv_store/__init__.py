"""ohlcv_store — OHLCV bar double-write and fallback-read.

Provides OhlcvBar dataclass, write (DB+cache), and read with multi-tier fallback.
IO dependencies injected via callables/protocols.

depends_on_external: (none — IO injected)
"""
from __future__ import annotations

from obase.ohlcv_store.model import OhlcvBar, OhlcvStoreError
from obase.ohlcv_store.reader import read_ohlcv_list_or_fallback
from obase.ohlcv_store.writer import write_ohlcv_bars

__all__ = [
    "OhlcvBar",
    "read_ohlcv_list_or_fallback",
    "write_ohlcv_bars",
    "OhlcvStoreError",
]
