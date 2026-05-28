"""collector_base — Abstract base for external data collector background tasks.

Provides retry/backoff/diagnostic/loop skeleton for any data collector.
Subclasses implement fetch() and write() with injected dependencies.

depends_on_external: (none — pure asyncio)
"""

from __future__ import annotations

from obase.collector_base.base import BaseExternalCollector

__all__ = ["BaseExternalCollector", "CollectorError"]


class CollectorError(Exception):
    """Base error for collector_base submodule."""
