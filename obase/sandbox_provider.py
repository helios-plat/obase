"""Provider contract for full-system sandbox substrates.

This is intentionally only a port.  It does not launch processes, own an
executor, decide acceptance, or expose a new canonical element.  A provider
such as a future ``rish`` adapter may implement the physical operations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from obase.local_sandbox_pool import SandboxExecutionResult


class SandboxProviderError(RuntimeError):
    """Provider contract or lifecycle failure."""


@runtime_checkable
class FullSystemSandboxProvider(Protocol):
    """Injected full-system sandbox port; implementation owns side effects."""

    async def create(self, spec: Mapping[str, Any] | Any) -> Any: ...

    async def execute(
        self,
        sandbox: Any,
        command: str | list[str],
        *,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> SandboxExecutionResult | Mapping[str, Any]: ...

    async def snapshot(self, sandbox: Any) -> Any: ...

    async def destroy(self, sandbox: Any) -> None: ...


__all__ = ["FullSystemSandboxProvider", "SandboxProviderError"]
