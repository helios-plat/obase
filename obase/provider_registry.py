from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any

import structlog

from obase.exceptions import ProviderDiscoveryError, ProviderNotFoundError

log = structlog.get_logger()

_ENTRY_POINT_GROUP = "obase.providers"


class ProviderRegistry:
    """Class-level registry mapping (category, name) → callable."""

    _providers: dict[tuple[str, str], Callable[..., Any]] = {}
    _capabilities: dict[tuple[str, str], list[str]] = {}

    @classmethod
    def register(
        cls,
        category: str,
        name: str,
        fn: Callable[..., Any],
        replace: bool = False,
    ) -> None:
        key = (category, name)
        if key in cls._providers and not replace:
            raise OBaseRegistryConflict(
                f"Provider already registered: category={category!r} name={name!r}. "
                "Use replace=True to override."
            )
        cls._providers[key] = fn
        log.info("obase.provider_registry.registered", category=category, name=name)

    @classmethod
    def get(cls, category: str, name: str) -> Callable[..., Any]:
        key = (category, name)
        if key not in cls._providers:
            raise ProviderNotFoundError(
                f"No provider registered for category={category!r} name={name!r}"
            )
        return cls._providers[key]

    @classmethod
    def get_caller(cls, provider: str, model: str) -> Callable[..., Any]:
        """Convenience method to get an LLM caller."""
        return cls.get("llm", provider)

    @classmethod
    def has(cls, category: str, name: str) -> bool:
        return (category, name) in cls._providers

    @classmethod
    def list_providers(cls, category: str | None = None) -> list[tuple[str, str]]:
        if category is None:
            return list(cls._providers.keys())
        return [(c, n) for (c, n) in cls._providers if c == category]

    @classmethod
    def auto_discover(cls) -> None:
        """Load all entry points in group 'obase.providers'."""
        try:
            eps = entry_points(group=_ENTRY_POINT_GROUP)
        except Exception as exc:
            raise ProviderDiscoveryError(f"entry_points scan failed: {exc}") from exc

        for ep in eps:
            try:
                fn = ep.load()
                parts = ep.name.split(".", 1)
                if len(parts) != 2:
                    log.warning(
                        "obase.provider_registry.bad_entry_point",
                        name=ep.name,
                        reason="expected 'category.name' format",
                    )
                    continue
                category, pname = parts
                cls.register(category, pname, fn, replace=True)
                log.info("obase.provider_registry.discovered", ep=ep.name)
            except Exception as exc:
                raise ProviderDiscoveryError(
                    f"Failed loading entry point {ep.name!r}: {exc}"
                ) from exc

    @classmethod
    def register_with_capability(
        cls,
        category: str,
        name: str,
        fn: Callable[..., Any],
        capabilities: list[str],
        replace: bool = False,
    ) -> None:
        """Register a provider and associate it with capability tags.

        Example:
            ProviderRegistry.register_with_capability(
                "video", "wan22", wan22_fn, ["i2v", "t2v", "fps24"]
            )
        """
        cls.register(category, name, fn, replace=replace)
        cls._capabilities[(category, name)] = list(capabilities)

    @classmethod
    def capabilities(cls, category: str, name: str) -> list[str]:
        """Return capability tags for a registered provider (empty list if none)."""
        return list(cls._capabilities.get((category, name), []))

    @classmethod
    def find_by_capability(cls, category: str, capability: str) -> list[str]:
        """Return provider names in a category that have the given capability tag."""
        return [
            n
            for (cat, n), caps in cls._capabilities.items()
            if cat == category and capability in caps
        ]

    @classmethod
    def clear(cls) -> None:
        """Remove all registered providers (useful in tests)."""
        cls._providers.clear()
        cls._capabilities.clear()


class OBaseRegistryConflict(Exception):
    pass
