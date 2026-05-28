"""BaseExternalCollector — abstract collector skeleton with retry/backoff/diagnostic."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Protocol

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL_S = 3600
_MAX_RETRIES = 3


class DiagnosticWriter(Protocol):
    """Protocol for writing diagnostic counters (decouples Redis)."""

    async def incr(self, key: str) -> None: ...
    async def set(self, key: str, value: str) -> None: ...


class BaseExternalCollector(ABC):
    """Abstract base for external data collectors.

    Subclass contract:
        - Set ``source`` class attribute (e.g. "sosovalue", "defillama").
        - Implement ``fetch()`` → raw dict from external API.
        - Implement ``write(data)`` → persist fetched data.
        - Optionally inject ``diagnostic_writer`` for counter persistence.

    Framework provides:
        - 3-attempt retry with exponential backoff (2^attempt seconds).
        - Diagnostic counters via injected writer.
        - CancelledError propagation (clean shutdown).
        - Never raises on fetch/write failure — logs warning and skips.

    Args:
        source: Data source identifier.
        interval_seconds: Seconds between collection cycles.
        diagnostic_writer: Optional protocol for persisting diagnostics.

    Example:
        >>> class MyCollector(BaseExternalCollector):
        ...     source = "binance"
        ...     async def fetch(self) -> dict[str, Any]:
        ...         return {"price": 100}
        ...     async def write(self, data: dict[str, Any]) -> None:
        ...         pass
    """

    source: str = ""
    interval_seconds: int = _DEFAULT_INTERVAL_S

    def __init__(
        self,
        *,
        source: str | None = None,
        interval_seconds: int | None = None,
        diagnostic_writer: DiagnosticWriter | None = None,
    ) -> None:
        if source is not None:
            self.source = source
        if interval_seconds is not None:
            self.interval_seconds = interval_seconds
        self._diagnostic_writer = diagnostic_writer

    @abstractmethod
    async def fetch(self) -> dict[str, Any]:
        """Fetch raw data from external API.

        Raises:
            Exception: On any fetch failure — caller handles retry.
        """
        ...

    @abstractmethod
    async def write(self, data: dict[str, Any]) -> None:
        """Persist fetched data.

        Args:
            data: Raw data dict returned by fetch().

        Raises:
            Exception: On write failure.
        """
        ...

    async def run_once(self) -> bool:
        """Execute one fetch+write cycle with retry.

        Returns:
            True if cycle completed successfully, False otherwise.
        """
        start = time.monotonic()
        data: dict[str, Any] | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                data = await self.fetch()
                break
            except Exception as exc:
                if attempt == _MAX_RETRIES - 1:
                    log.warning(
                        "collector.%s fetch_failed all_attempts err=%s",
                        self.source,
                        exc,
                    )
                    await self._inc_diagnostic("error_count")
                    return False
                backoff = 2**attempt
                log.debug(
                    "collector.%s fetch_attempt=%d err=%s backoff=%ds",
                    self.source,
                    attempt + 1,
                    exc,
                    backoff,
                )
                await asyncio.sleep(backoff)

        if data is None:
            return False

        try:
            await self.write(data)
        except Exception as exc:
            log.warning("collector.%s write_failed err=%s", self.source, exc)
            await self._inc_diagnostic("error_count")
            return False

        elapsed_ms = int((time.monotonic() - start) * 1000)
        await self._write_success_diagnostic(elapsed_ms)
        return True

    async def run(self) -> None:
        """Run collector loop indefinitely.

        Raises:
            asyncio.CancelledError: On clean shutdown.
        """
        log.info("collector.%s started interval=%ds", self.source, self.interval_seconds)
        try:
            while True:
                await self.run_once()
                await asyncio.sleep(self.interval_seconds)
        except asyncio.CancelledError:
            log.info("collector.%s stopped", self.source)
            raise

    async def _inc_diagnostic(self, counter: str) -> None:
        if self._diagnostic_writer is None:
            return
        try:
            await self._diagnostic_writer.incr(f"diagnostic:collector:{self.source}:{counter}")
        except Exception as exc:
            log.debug("collector.%s diagnostic_inc_failed err=%s", self.source, exc)

    async def _write_success_diagnostic(self, elapsed_ms: int) -> None:
        if self._diagnostic_writer is None:
            return
        try:
            await self._diagnostic_writer.incr(f"diagnostic:collector:{self.source}:fetch_count")
            await self._diagnostic_writer.set(
                f"diagnostic:collector:{self.source}:last_run_ts",
                str(int(time.time())),
            )
            await self._diagnostic_writer.set(
                f"diagnostic:collector:{self.source}:last_duration_ms",
                str(elapsed_ms),
            )
        except Exception as exc:
            log.debug("collector.%s diagnostic_write_failed err=%s", self.source, exc)
