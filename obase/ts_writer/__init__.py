"""ts_writer — TimescaleDB timeseries write helpers.

Provides async write functions for fusion, timeframes, and regime hypertables.
DB session injected via protocol.

depends_on_external: (none — IO injected)
"""

from __future__ import annotations

from obase.ts_writer.writer import (
    write_fusion_ts,
    write_regime_ts,
    write_timeframes_ts,
)

__all__ = [
    "write_fusion_ts",
    "write_timeframes_ts",
    "write_regime_ts",
    "TsWriterError",
]


class TsWriterError(Exception):
    """Base error for ts_writer submodule."""
