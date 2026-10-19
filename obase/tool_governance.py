"""Shared tool, MCP, grant, and credential-reference value types.

These types are deliberately data-only.  They do not resolve secrets, make
policy decisions, call MCP, or persist grants.  A native tool and an MCP tool
share the same identity shape so the governance layer can treat them equally.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit

ToolKind = Literal["native", "mcp"]
ToolEffect = Literal["read", "local_write", "process", "network", "remote", "destructive"]

_SECRET_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "credential",
    "private_key",
    "authorization",
    "api_key",
    "access_key",
    "client_secret",
    "webhook",
)


def _secret_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _redact_endpoint(endpoint: str) -> str:
    """Remove optional URL userinfo before endpoint metadata is persisted."""
    try:
        parsed = urlsplit(endpoint)
        if parsed.username is None and parsed.password is None:
            return endpoint
        hostname = parsed.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = f"[REDACTED]@{hostname}"
        if parsed.port is not None:
            netloc += f":{parsed.port}"
        safe = SplitResult(parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
        return urlunsplit(safe)
    except ValueError:
        return "[REDACTED_ENDPOINT]"


def redact_payload(value: Any, *, secrets: Sequence[str] = ()) -> Any:
    """Return a JSON-safe payload with secret-looking values removed.

    Key-based redaction protects structured metadata; ``secrets`` additionally
    protects a resolved value if a physical tool returns it in plain text.
    """
    secret_values = tuple(item for item in secrets if item)
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _secret_key(key)
            else redact_payload(item, secrets=secret_values)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_payload(item, secrets=secret_values) for item in value]
    if isinstance(value, str):
        output = value
        for secret in secret_values:
            output = output.replace(secret, "[REDACTED]")
        return output
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


@dataclass(frozen=True, repr=False)
class CredentialRef:
    """Stable reference to a credential; never contains its value."""

    id: str
    provider: str | None = None
    version: int | None = None
    scope: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("CredentialRef.id must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "credential_ref",
            "id": self.id,
            "provider": self.provider,
            "version": self.version,
            "scope": self.scope,
        }

    def __repr__(self) -> str:
        return (
            f"CredentialRef(id={self.id!r}, provider={self.provider!r}, version={self.version!r})"
        )


@dataclass(frozen=True, repr=False)
class SecretRef:
    """Stable reference to a secret in an obase vault."""

    id: str
    version: int | None = None
    scope: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("SecretRef.id must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "secret_ref",
            "id": self.id,
            "version": self.version,
            "scope": self.scope,
        }

    def __repr__(self) -> str:
        return f"SecretRef(id={self.id!r}, version={self.version!r})"


@dataclass(frozen=True, repr=False)
class ToolSpec:
    """Versioned identity and execution metadata for native or MCP tools."""

    name: str
    description: str = ""
    kind: ToolKind = "native"
    server: str | None = None
    version: str = "1"
    effect: ToolEffect = "read"
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    capabilities: frozenset[str] = frozenset()
    credential_ref: CredentialRef | SecretRef | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("ToolSpec.name must not be empty")
        if self.kind not in {"native", "mcp"}:
            raise ValueError(f"unsupported tool kind: {self.kind!r}")
        if self.kind == "mcp" and not (self.server or "").strip():
            raise ValueError("MCP ToolSpec requires server")
        if not self.version.strip():
            raise ValueError("ToolSpec.version must not be empty")

    @property
    def identity(self) -> str:
        prefix = "native" if self.kind == "native" else f"mcp/{self.server}"
        return f"{prefix}/{self.name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "server": self.server,
            "version": self.version,
            "effect": self.effect,
            "input_schema": redact_payload(self.input_schema),
            "capabilities": sorted(self.capabilities),
            "credential_ref": self.credential_ref.to_dict() if self.credential_ref else None,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, repr=False)
class MCPServerSpec:
    """Versioned MCP server registration and its advertised tool schemas."""

    name: str
    endpoint: str
    version: str = "1"
    protocol_version: str = "2025-03-26"
    tools: tuple[ToolSpec, ...] = ()
    credential_ref: CredentialRef | SecretRef | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.endpoint.strip():
            raise ValueError("MCPServerSpec requires name and endpoint")
        if not self.version.strip():
            raise ValueError("MCPServerSpec.version must not be empty")
        normalized: list[ToolSpec] = []
        for tool in self.tools:
            if isinstance(tool, ToolSpec):
                normalized.append(tool)
            else:
                normalized.append(ToolSpec(**dict(tool)))
        if any(tool.kind != "mcp" or tool.server != self.name for tool in normalized):
            raise ValueError("MCPServerSpec.tools must belong to this MCP server")
        object.__setattr__(self, "tools", tuple(normalized))

    @property
    def identity(self) -> str:
        return f"mcp-server/{self.name}@{self.version}"

    def tool(self, name: str, version: str | None = None) -> ToolSpec | None:
        return next(
            (
                item
                for item in self.tools
                if item.name == name and (version is None or item.version == version)
            ),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "name": self.name,
            "endpoint": _redact_endpoint(self.endpoint),
            "version": self.version,
            "protocol_version": self.protocol_version,
            "tools": [tool.to_dict() for tool in self.tools],
            "credential_ref": self.credential_ref.to_dict() if self.credential_ref else None,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, repr=False)
class Grant:
    """A time/version scoped capability grant; revocation is fail-closed."""

    tool: str
    subject: str = "*"
    grant_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    allowed_effects: frozenset[str] = frozenset({"read"})
    tool_version: str | None = None
    resource: str = "*"
    expires_at: str | None = None
    revoked: bool = False
    issued_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def is_valid(self, *, now: datetime | None = None) -> bool:
        if self.revoked:
            return False
        if not self.expires_at:
            return True
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        current = now or datetime.now(UTC)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return current.astimezone(UTC) < expires.astimezone(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "subject": self.subject,
            "tool": self.tool,
            "allowed_effects": sorted(self.allowed_effects),
            "tool_version": self.tool_version,
            "resource": self.resource,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "issued_at": self.issued_at,
        }

    def __repr__(self) -> str:
        return (
            f"Grant(grant_id={self.grant_id!r}, subject={self.subject!r}, "
            f"tool={self.tool!r}, revoked={self.revoked!r})"
        )


@dataclass(frozen=True, repr=False)
class ToolCallRequest:
    """Governance-bound tool call containing references, not secret values."""

    tool: str
    kind: ToolKind = "native"
    server: str | None = None
    version: str = "1"
    arguments: Mapping[str, Any] = field(default_factory=dict, repr=False)
    actor: str = "master"
    source: str = ""
    grant: Grant | None = None
    credential_ref: CredentialRef | SecretRef | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    context: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def identity(self) -> str:
        prefix = "native" if self.kind == "native" else f"mcp/{self.server}"
        return f"{prefix}/{self.tool}@{self.version}"

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "tool": self.tool,
            "kind": self.kind,
            "server": self.server,
            "version": self.version,
            "arguments": redact_payload(self.arguments),
            "actor": self.actor,
            "source": self.source,
            "grant": self.grant.to_dict() if self.grant else None,
            "credential_ref": self.credential_ref.to_dict() if self.credential_ref else None,
            "request_id": self.request_id,
            "context": redact_payload(self.context),
        }

    def __repr__(self) -> str:
        return (
            f"ToolCallRequest(identity={self.identity!r}, "
            f"request_id={self.request_id!r}, credential_ref={self.credential_ref!r})"
        )


@dataclass(frozen=True, repr=False)
class ToolCallResult:
    """Safe result crossing back to Layer 4; payloads are redacted on export."""

    status: Literal["completed", "failed", "denied"]
    request_id: str
    tool: str
    result: Any = field(default=None, repr=False)
    error: Mapping[str, Any] | None = field(default=None, repr=False)
    executed: bool = False
    ledger_recorded: bool = False
    credential_ref: CredentialRef | SecretRef | None = None

    def to_dict(self, *, secrets: Sequence[str] = ()) -> dict[str, Any]:
        return {
            "status": self.status,
            "request_id": self.request_id,
            "tool": self.tool,
            "result": redact_payload(self.result, secrets=secrets),
            "error": redact_payload(self.error, secrets=secrets),
            "executed": self.executed,
            "ledger_recorded": self.ledger_recorded,
            "credential_ref": self.credential_ref.to_dict() if self.credential_ref else None,
        }

    def __repr__(self) -> str:
        return (
            f"ToolCallResult(status={self.status!r}, request_id={self.request_id!r}, "
            f"tool={self.tool!r}, executed={self.executed!r})"
        )


__all__ = [
    "CredentialRef",
    "Grant",
    "MCPServerSpec",
    "SecretRef",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolEffect",
    "ToolKind",
    "ToolSpec",
    "redact_payload",
]
