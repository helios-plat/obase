"""Shared, dependency-free contract metadata for 3O canonical elements.

This module is intentionally only a description type.  It does not execute
work, make acceptance decisions, persist state, or import any project layer.
The seven v1 elements use it to expose the same machine-readable contract
shape without creating another runtime authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

AUTHORITY_KEYS = (
    "semantic_authority",
    "execution_authority",
    "side_effect_authority",
    "acceptance_authority",
)


@dataclass(frozen=True)
class ElementContract:
    """Machine-readable metadata required by the 3O Element Contract."""

    element_id: str
    element_version: int
    owner_repo: str
    canonical_import: str
    canonical_export: str
    input_contract: str
    output_contract: str
    dependency_ports: tuple[str, ...]
    state_model: str
    persistence_model: str
    authority_declaration: Mapping[str, int]
    async_contract: str
    failure_semantics: str
    recovery_semantics: str
    observability_contract: str
    compatibility_contract: str
    conformance_suite: tuple[str, ...]
    manifest_registered: bool = True
    canonical_export_count: int = 1
    duplicate_implementation: int = 0
    stale_exports: int = 0

    def __post_init__(self) -> None:
        if not self.element_id:
            raise ValueError("element_id must be non-empty")
        if self.element_version < 1:
            raise ValueError("element_version must be >= 1")
        if not self.owner_repo:
            raise ValueError("owner_repo must be non-empty")
        if not self.canonical_import or not self.canonical_export:
            raise ValueError("canonical import/export must be non-empty")
        if self.canonical_export_count != 1:
            raise ValueError("canonical_export_count must be exactly 1")
        if self.duplicate_implementation != 0:
            raise ValueError("duplicate_implementation must be 0")
        if self.stale_exports != 0:
            raise ValueError("stale_exports must be 0")
        missing = set(AUTHORITY_KEYS) - set(self.authority_declaration)
        if missing:
            raise ValueError(f"authority declaration missing keys: {sorted(missing)}")
        nonzero = {
            key: value
            for key, value in self.authority_declaration.items()
            if key in AUTHORITY_KEYS and value != 0
        }
        if nonzero:
            raise ValueError(f"new elements cannot own authority: {nonzero}")

    @property
    def authority_zero(self) -> bool:
        """Whether all four prohibited second authorities are explicitly zero."""

        return all(self.authority_declaration.get(key) == 0 for key in AUTHORITY_KEYS)

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-friendly representation for manifest tooling."""

        return {
            "ElementId": self.element_id,
            "ElementVersion": self.element_version,
            "OwnerRepo": self.owner_repo,
            "CanonicalImport": self.canonical_import,
            "CanonicalExport": self.canonical_export,
            "InputContract": self.input_contract,
            "OutputContract": self.output_contract,
            "DependencyPorts": list(self.dependency_ports),
            "StateModel": self.state_model,
            "PersistenceModel": self.persistence_model,
            "AuthorityDeclaration": dict(self.authority_declaration),
            "AsyncContract": self.async_contract,
            "FailureSemantics": self.failure_semantics,
            "RecoverySemantics": self.recovery_semantics,
            "ObservabilityContract": self.observability_contract,
            "CompatibilityContract": self.compatibility_contract,
            "ConformanceSuite": list(self.conformance_suite),
            "MANIFEST_REGISTERED": self.manifest_registered,
            "CANONICAL_EXPORT_COUNT": self.canonical_export_count,
            "DUPLICATE_IMPLEMENTATION": self.duplicate_implementation,
            "STALE_EXPORTS": self.stale_exports,
        }


def zero_authority() -> dict[str, int]:
    """Return a fresh all-zero authority declaration."""

    return dict.fromkeys(AUTHORITY_KEYS, 0)


__all__ = ["AUTHORITY_KEYS", "ElementContract", "zero_authority"]
