"""signal_data_registry — Unified data source registry for signal providers."""
from __future__ import annotations

from typing import Any, Callable


class SignalDataRegistryError(Exception):
    """Base error for signal_data_registry."""


class SignalDataRegistry:
    """Registry for signal data providers (ProviderRegistry pattern).

    Example:
        >>> reg = SignalDataRegistry()
        >>> reg.register("binance", lambda **kw: {"price": 50000})
        >>> reg.get_data("binance")
        {'price': 50000}
    """

    def __init__(self) -> None:
        self._providers: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, impl: Callable[..., Any]) -> None:
        """Register a data provider.

        Args:
            name: Provider name.
            impl: Callable that returns data.
        """
        self._providers[name] = impl

    def get_data(self, source: str, **kwargs: Any) -> Any:
        """Get data from a registered provider.

        Args:
            source: Provider name.
            **kwargs: Provider-specific arguments.

        Returns:
            Data from provider.

        Raises:
            SignalDataRegistryError: If provider not registered.
        """
        if source not in self._providers:
            raise SignalDataRegistryError(f"Provider not registered: {source}")
        return self._providers[source](**kwargs)

    @property
    def providers(self) -> list[str]:
        """List registered provider names."""
        return list(self._providers.keys())
