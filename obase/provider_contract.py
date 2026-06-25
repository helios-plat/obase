"""E1 — Provider Contract: unified pricing source of truth.

Replaces manual PricingTable registration with contract-driven derivation.
Aliases (ltx2_local→wan_local) resolve to the endpoint's pricing automatically.
"""
from __future__ import annotations

from typing import Literal

from obase._types import OBaseModel
from obase.cost_tracker import PricingEntry, PricingTable
from obase.exceptions import PricingNotConfiguredError, ProviderNotFoundError


class ProviderContract(OBaseModel):
    name: str
    location: Literal["local", "cloud"]
    capability: str           # "video_gen" | "llm" | "audio" | "avatar"
    unit_cost_usd: float      # local=0.0
    unit: str                 # "per_second" | "per_call" | "per_token"
    alias_of: str | None = None


class ProviderContractRegistry(OBaseModel):
    contracts: dict[str, ProviderContract] = {}

    def register(self, contract: ProviderContract) -> None:
        """Register a provider contract. Overwrites if name already exists."""
        self.contracts[contract.name] = contract

    def resolve(self, name: str) -> ProviderContract:
        """Follow alias chain to the terminal contract.

        ltx2_local → wan_local → (no alias) → returns wan_local contract.
        Raises ProviderNotFoundError on unknown provider.
        Raises ValueError on circular alias chain.
        """
        visited: set[str] = set()
        current = name
        while True:
            if current in visited:
                raise ValueError(f"Circular alias detected: {current!r} in chain from {name!r}")
            visited.add(current)
            contract = self.contracts.get(current)
            if contract is None:
                raise ProviderNotFoundError(f"Provider not registered: {current!r}")
            if contract.alias_of is None:
                return contract
            current = contract.alias_of

    def derive_pricing(self) -> PricingTable:
        """Build a PricingTable from registered contracts.

        Alias names get their own PricingEntry pointing to the resolved
        endpoint's pricing — no hand-maintained fallback lists needed.
        Raises ProviderNotFoundError if any alias chain is broken.
        """
        entries: list[PricingEntry] = []
        for name in self.contracts:
            resolved = self.resolve(name)
            entries.append(PricingEntry(
                category=resolved.capability,
                provider=name,
                model_or_tier=name,
                unit=resolved.unit,
                price_usd=resolved.unit_cost_usd,
            ))
        return PricingTable(entries=entries)
