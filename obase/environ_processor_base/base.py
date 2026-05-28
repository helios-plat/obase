"""BaseEnvironProcessor — abstract processor skeleton with load/compute/write/loop."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL_S = 3600
_STARTUP_DELAY_S = 90


class DiagnosticWriter(Protocol):
    """Protocol for writing diagnostic counters."""

    async def incr(self, key: str) -> None: ...
    async def set(self, key: str, value: str) -> None: ...


class BaseEnvironProcessor(ABC):
    """Abstract base for environ layer processors.

    Subclass contract:
        - Set ``domain`` class attribute (e.g. "etf", "macro").
        - Implement ``load_external()`` → dict from raw data source.
        - Implement ``compute_environ(data)`` → processed dict.
        - Implement ``write_environ(data)`` → persist processed signals.

    Framework provides:
        - Startup delay (lets upstream collectors run first).
        - Diagnostic counters via injected writer.
        - CancelledError propagation (clean shutdown).
        - Never raises on processing failure — logs warning and skips.

    Args:
        domain: Processing domain identifier.
        interval_seconds: Seconds between processing cycles.
        startup_delay_seconds: Initial delay before first cycle.
        diagnostic_writer: Optional protocol for persisting diagnostics.

    Example:
        >>> class MacroProcessor(BaseEnvironProcessor):
        ...     domain = "macro"
        ...     async def load_external(self) -> dict[str, Any]:
        ...         return {"dxy": 104.5}
        ...     async def compute_environ(self, data: dict[str, Any]) -> dict[str, Any]:
        ...         return {"dxy_zscore": 1.2}
        ...     async def write_environ(self, data: dict[str, Any]) -> None:
        ...         pass
    """

    domain: str = ""
    interval_seconds: int = _DEFAULT_INTERVAL_S

    def __init__(
        self,
        *,
        domain: str | None = None,
        interval_seconds: int | None = None,
        startup_delay_seconds: int = _STARTUP_DELAY_S,
        diagnostic_writer: DiagnosticWriter | None = None,
    ) -> None:
        if domain is not None:
            self.domain = domain
        if interval_seconds is not None:
            self.interval_seconds = interval_seconds
        self._startup_delay_seconds = startup_delay_seconds
        self._diagnostic_writer = diagnostic_writer

    @abstractmethod
    async def load_external(self) -> dict[str, Any]:
        """Read external-layer data. Return empty dict if data not ready.

        Returns:
            Raw data dict, or empty dict to skip processing.
        """
        ...

    @abstractmethod
    async def compute_environ(self, external_data: dict[str, Any]) -> dict[str, Any]:
        """Transform external raw data to environ-ready signals.

        Args:
            external_data: Data from load_external().

        Returns:
            Processed signals dict, or empty dict to skip write.
        """
        ...

    @abstractmethod
    async def write_environ(self, environ_data: dict[str, Any]) -> None:
        """Persist processed environ signals.

        Args:
            environ_data: Processed data from compute_environ().
        """
        ...

    async def run_once(self) -> bool:
        """Execute one load→compute→write cycle.

        Returns:
            True if cycle completed successfully, False otherwise.
        """
        try:
            external_data = await self.load_external()
            if not external_data:
                log.debug("processor.%s no external data — skipping", self.domain)
                return False

            environ_data = await self.compute_environ(external_data)
            if not environ_data:
                log.debug("processor.%s compute returned empty — skipping", self.domain)
                return False

            await self.write_environ(environ_data)
            await self._write_diagnostic()
            return True
        except Exception as exc:
            log.warning("processor.%s run_once error=%s", self.domain, exc)
            await self._inc_error()
            return False

    async def run(self) -> None:
        """Run processor loop indefinitely with startup delay.

        Raises:
            asyncio.CancelledError: On clean shutdown.
        """
        await asyncio.sleep(self._startup_delay_seconds)
        log.info("processor.%s started interval=%ds", self.domain, self.interval_seconds)
        try:
            while True:
                await self.run_once()
                await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            log.info("processor.%s stopped", self.domain)
            raise

    async def _write_diagnostic(self) -> None:
        if self._diagnostic_writer is None:
            return
        try:
            await self._diagnostic_writer.set(
                f"diagnostic:processor:{self.domain}:last_run_ts",
                str(int(time.time())),
            )
        except Exception:
            pass

    async def _inc_error(self) -> None:
        if self._diagnostic_writer is None:
            return
        try:
            await self._diagnostic_writer.incr(f"diagnostic:processor:{self.domain}:error_count")
        except Exception:
            pass
