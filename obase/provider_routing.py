"""Provider routing value types.

The objects in this module are deliberately data-only.  They describe what a
provider can do and what a call consumed; selection, fallback, persistence,
and provider SDK calls live in the layers above or are injected into them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(value)


class ProtocolFamily(StrEnum):
    """Canonical runtime protocol family (D1, single authority).

    The only protocol taxonomy that may describe *runtime* protocol in
    obase. ``str``-serializable (JSON renders the plain value) and
    backward-compatible with existing plain-string metadata via
    :meth:`coerce`. Unknown values are fail-closed (``ValueError``).

    This type never performs semantic routing and never decides
    agent/task intent — it is static transport/protocol metadata only.
    """

    NATIVE = "native"
    HARNESS = "harness"
    ACP = "acp"
    A2A = "a2a"
    MCP = "mcp"

    @classmethod
    def coerce(cls, value: ProtocolFamily | str) -> ProtocolFamily:
        """Coerce a stored string (or member) to a member, fail-closed."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value.strip().lower())
            except ValueError:
                pass
        valid = sorted(member.value for member in cls)
        raise ValueError(f"unknown protocol family {value!r}; expected one of {valid}")


#: Lifecycle/support matrix operations (static capability metadata only).
LIFECYCLE_OPS = ("run", "stream", "status", "cancel", "resume")


_TOOL_KIND_TO_FAMILY = {
    "native": ProtocolFamily.NATIVE,
    "mcp": ProtocolFamily.MCP,
}


def tool_kind_to_protocol_family(kind: str) -> ProtocolFamily:
    """Map a legacy ``ToolKind`` value onto the canonical ProtocolFamily.

    ``ToolKind`` itself is retained (tool transport identity is orthogonal
    metadata), but it must never grow into an independent runtime protocol
    taxonomy — runtime protocol questions go to :class:`ProtocolFamily`.
    """
    if isinstance(kind, str) and kind.strip().lower() in _TOOL_KIND_TO_FAMILY:
        return _TOOL_KIND_TO_FAMILY[kind.strip().lower()]
    raise ValueError(
        f"tool kind {kind!r} is not a runtime protocol; "
        f"expected one of {sorted(_TOOL_KIND_TO_FAMILY)}"
    )


@dataclass(frozen=True)
class Pricing:
    """Token pricing for one model.

    Prices are USD per token.  ``None`` means that the price is not known and
    must not be silently estimated by a caller that requires strict pricing.
    """

    provider: str
    model: str
    input_usd_per_token: float | None = None
    output_usd_per_token: float | None = None
    currency: str = "USD"

    def estimate(self, input_tokens: int, output_tokens: int) -> float | None:
        if self.input_usd_per_token is None or self.output_usd_per_token is None:
            return None
        return input_tokens * self.input_usd_per_token + output_tokens * self.output_usd_per_token


@dataclass(frozen=True)
class ModelSpec:
    """Execution capabilities for one provider model."""

    name: str
    provider: str
    capabilities: frozenset[str] = frozenset({"chat"})
    context_window: int | None = None
    supports_streaming: bool = True
    supports_tools: bool = True
    pricing: Pricing | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def supports(self, capability: str | None) -> bool:
        return capability is None or capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "capabilities": sorted(self.capabilities),
            "context_window": self.context_window,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.supports_tools,
            "pricing": self.pricing.__dict__ if self.pricing else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ProviderHealth:
    """Latest health observation for a provider or provider endpoint."""

    provider: str
    healthy: bool
    status: str = "healthy"
    latency_ms: float | None = None
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "healthy": self.healthy,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProviderSpec:
    """Provider registry metadata consumed by the routing skill.

    D1 runtime descriptor: the same value type carries the static
    runtime/capability metadata (protocol family, version, availability,
    lifecycle/support matrix). Live mutable session/run state must never
    be stored here — descriptor = static metadata, run state = project
    /runtime layer.
    """

    name: str
    models: tuple[ModelSpec, ...] = ()
    capabilities: frozenset[str] = frozenset({"chat"})
    health: ProviderHealth | None = None
    priority: int = 0
    enabled: bool = True
    credential_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    protocol_family: ProtocolFamily = ProtocolFamily.NATIVE
    version: str | None = None
    available: bool = True
    unavailable_reason: str | None = None
    lifecycle: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        models: list[ModelSpec] = []
        for model in _as_tuple(self.models):
            if isinstance(model, ModelSpec):
                models.append(model)
            elif isinstance(model, Mapping):
                raw = dict(model)
                pricing = raw.get("pricing")
                if isinstance(pricing, Mapping):
                    raw["pricing"] = Pricing(**pricing)
                models.append(ModelSpec(**raw))
            else:
                raise TypeError("ProviderSpec.models must contain ModelSpec values")
        object.__setattr__(self, "models", tuple(models))
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "protocol_family", ProtocolFamily.coerce(self.protocol_family))
        version = self.version.strip() if isinstance(self.version, str) else self.version
        object.__setattr__(self, "version", version or None)
        object.__setattr__(self, "available", bool(self.available))
        raw_lifecycle = dict(self.lifecycle or {})
        unknown = set(raw_lifecycle) - set(LIFECYCLE_OPS)
        if unknown:
            raise ValueError(
                f"unknown lifecycle ops {sorted(unknown)}; expected subset of {list(LIFECYCLE_OPS)}"
            )
        object.__setattr__(
            self,
            "lifecycle",
            {op: bool(raw_lifecycle.get(op, False)) for op in LIFECYCLE_OPS},
        )

    def can(self, op: str) -> bool:
        """Return the static lifecycle/support flag for one operation."""
        if op not in LIFECYCLE_OPS:
            raise ValueError(f"unknown lifecycle op {op!r}; expected one of {LIFECYCLE_OPS}")
        return bool(self.lifecycle.get(op, False))

    def model(self, name: str | None = None) -> ModelSpec | None:
        if name:
            return next((item for item in self.models if item.name == name), None)
        return self.models[0] if self.models else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "models": [model.to_dict() for model in self.models],
            "capabilities": sorted(self.capabilities),
            "health": self.health.to_dict() if self.health else None,
            "priority": self.priority,
            "enabled": self.enabled,
            # A reference is safe metadata; the secret itself is never part of
            # this object or any serialized routing record.
            "credential_ref": self.credential_ref,
            "metadata": dict(self.metadata),
            "protocol_family": self.protocol_family.value,
            "version": self.version,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "lifecycle": dict(self.lifecycle),
        }


@dataclass(frozen=True)
class ProviderCallRequest:
    """Provider-neutral call envelope passed to the atomic call primitive."""

    provider: str
    model: str
    messages: tuple[Mapping[str, Any], ...]
    tools: tuple[Mapping[str, Any], ...] = ()
    stream: bool = False
    max_tokens: int | None = None
    temperature: float | None = None
    credential_ref: str | None = None
    request_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))

    def to_dict(self) -> dict[str, Any]:
        """Return a transport-ready mapping without secret material."""
        return {
            "provider": self.provider,
            "model": self.model,
            "messages": [dict(message) for message in self.messages],
            "tools": [dict(tool) for tool in self.tools],
            "stream": self.stream,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "credential_ref": self.credential_ref,
            "request_ref": self.request_ref,
        }

    def safe_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "stream": self.stream,
            "request_ref": self.request_ref,
        }


@dataclass(frozen=True)
class UsageRecord:
    """Normalized provider usage; no messages or credentials are retained."""

    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float | None = None
    estimated_cost_usd: float | None = None
    success: bool = True
    streamed: bool = False
    request_ref: str | None = None
    error_type: str | None = None
    recorded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "estimated_cost_usd": self.estimated_cost_usd,
            "success": self.success,
            "streamed": self.streamed,
            "request_ref": self.request_ref,
            "error_type": self.error_type,
            "recorded_at": self.recorded_at,
        }


__all__ = [
    "LIFECYCLE_OPS",
    "ModelSpec",
    "Pricing",
    "ProtocolFamily",
    "ProviderCallRequest",
    "ProviderHealth",
    "ProviderSpec",
    "UsageRecord",
    "tool_kind_to_protocol_family",
]
