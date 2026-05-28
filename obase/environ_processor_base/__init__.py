"""environ_processor_base — Abstract base for environ layer processors.

Provides load/compute/write/loop contract for data transformation processors
that read raw external data and produce fusion-ready environ signals.

depends_on_external: (none — pure asyncio)
"""

from __future__ import annotations

from obase.environ_processor_base.base import BaseEnvironProcessor

__all__ = ["BaseEnvironProcessor", "EnvironProcessorError"]


class EnvironProcessorError(Exception):
    """Base error for environ_processor_base submodule."""
