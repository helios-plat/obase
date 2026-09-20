"""Provider routing value types.

The objects in this module are deliberately data-only.  They describe what a
provider can do and what a call consumed; selection, fallback, persistence,
and provider SDK calls live in the layers above or are injected into them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(value)


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
    """Provider registry metadata consumed by the routing skill."""

    name: str
    models: tuple[ModelSpec, ...] = ()
    capabilities: frozenset[str] = frozenset({"chat"})
    health: ProviderHealth | None = None
    priority: int = 0
    enabled: bool = True
    credential_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

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
    "ModelSpec",
    "Pricing",
    "ProviderCallRequest",
    "ProviderHealth",
    "ProviderSpec",
    "UsageRecord",
]
