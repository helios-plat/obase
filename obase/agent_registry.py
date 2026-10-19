"""obase.agent_registry — AutoAgent-style agent/tool/workflow registry.

Provides ``@register_agent`` / ``@register_tool`` / ``@register_workflow``
decorators plus a process-wide ``AgentRegistry`` singleton (3O ``obase`` layer:
zero reverse deps).  Registry entries carry a type, a stable name and the
factory/loader callable; the Layer-4 gateway and the creation workflows use
this as the single source of truth for "what agents/tools/workflows exist".

3O element: ``obase.agent_registry`` (``AgentRegistry`` / decorators).

D1 runtime role: ``register_runtime`` entries may *reference* the canonical
``ProviderSpec`` descriptor by name and resolve it live from
``ProviderRegistry`` (same object, never a field copy —
PROVIDER_SPEC_AUTHORITY stays 1).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from obase.exceptions import ProviderNotFoundError
from obase.provider_routing import ProviderSpec

REGISTRY_TYPES = ("agent", "tool", "workflow", "plugin_agent", "plugin_tool", "runtime")


class RegistryConflictError(Exception):
    """Raised when a name is registered twice under the same type."""


class AgentRegistry:
    """Type-keyed registry of agents / tools / workflows.

    Entries: ``{type: {name: {"name": ..., "func": <factory>, "desc": ...}}}``
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in REGISTRY_TYPES}

    # -- registration ------------------------------------------------------
    def register(
        self,
        type_: str,
        name: str,
        func: Callable,
        func_name: str | None = None,
        desc: str = "",
    ) -> Callable:
        if type_ not in self._entries:
            raise ValueError(f"unknown registry type {type_!r}; expected {REGISTRY_TYPES}")
        if name in self._entries[type_]:
            raise RegistryConflictError(f"{type_} {name!r} already registered")
        self._entries[type_][name] = {
            "name": name,
            "func": func,
            "func_name": func_name or getattr(func, "__name__", name),
            "desc": desc or (func.__doc__ or "").strip().split("\n")[0],
        }
        return func

    # -- queries -----------------------------------------------------------
    def get(self, type_: str, name: str) -> dict[str, Any] | None:
        return self._entries.get(type_, {}).get(name)

    def get_func(self, type_: str, name: str) -> Callable | None:
        entry = self.get(type_, name)
        return entry["func"] if entry else None

    def list(self, type_: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in (type_,) if type_ else REGISTRY_TYPES:
            for entry in self._entries[t].values():
                out.append({k: v for k, v in entry.items() if k != "func"})
        return sorted(out, key=lambda e: (e.get("type", ""), e.get("name", "")))

    def count(self, type_: str | None = None) -> int:
        if type_:
            return len(self._entries[type_])
        return sum(len(v) for v in self._entries.values())

    def reset(self) -> None:
        for t in self._entries:
            self._entries[t].clear()

    # -- runtime role (D1: reference-only descriptor bridge) ------------------
    def register_runtime(
        self,
        name: str,
        func: Callable,
        *,
        spec: str | ProviderSpec | None = None,
        func_name: str | None = None,
        desc: str = "",
    ) -> Callable:
        """Register a ``runtime`` entry referencing a canonical descriptor.

        Only the spec *reference* (its name) is stored under the ``"spec"``
        key; descriptor fields are never copied here. Resolution always
        goes through :meth:`runtime_descriptor` against ``ProviderRegistry``.
        """
        self.register("runtime", name, func, func_name=func_name, desc=desc)
        if spec is not None:
            ref = spec.name if isinstance(spec, ProviderSpec) else str(spec)
            self._entries["runtime"][name]["spec"] = ref
        return func

    def runtime_descriptor(self, name: str) -> ProviderSpec | None:
        """Resolve a runtime entry's descriptor (same object, live lookup).

        Returns ``None`` when the entry has no ``spec`` reference or the
        referenced spec is not registered. Never synthesizes or copies
        descriptor state.
        """
        from obase.provider_registry import ProviderRegistry

        entry = self.get("runtime", name)
        if not entry:
            return None
        ref = entry.get("spec")
        if not ref:
            return None
        try:
            return ProviderRegistry.get().spec(ref)
        except ProviderNotFoundError:
            return None


# process-wide singleton (mirrors AutoAgent's module-level registry)
registry = AgentRegistry()


def _make_decorator(type_: str) -> Callable:
    def decorator(name: str = None, func_name: str = None) -> Callable:
        def wrap(func: Callable) -> Callable:
            registry.register(
                type_=type_,
                name=name or func.__name__,
                func=func,
                func_name=func_name,
            )
            return func

        return wrap

    return decorator


register_agent = _make_decorator("agent")
register_tool = _make_decorator("tool")
register_workflow = _make_decorator("workflow")
register_plugin_agent = _make_decorator("plugin_agent")
register_plugin_tool = _make_decorator("plugin_tool")
