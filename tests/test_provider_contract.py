"""Tests for E1 ProviderContract + ProviderContractRegistry."""
from __future__ import annotations

import pytest

from obase.exceptions import ProviderNotFoundError
from obase.provider_contract import ProviderContract, ProviderContractRegistry


def _wan_local() -> ProviderContract:
    return ProviderContract(
        name="wan_local", location="local", capability="video_gen",
        unit_cost_usd=0.0, unit="per_second",
    )


def _ltx2_local() -> ProviderContract:
    return ProviderContract(
        name="ltx2_local", location="local", capability="video_gen",
        unit_cost_usd=0.0, unit="per_second",
        alias_of="wan_local",
    )


def _wan_cloud() -> ProviderContract:
    return ProviderContract(
        name="wan_cloud", location="cloud", capability="video_gen",
        unit_cost_usd=0.08, unit="per_second",
    )


class TestProviderContract:

    def test_register_and_lookup(self):
        reg = ProviderContractRegistry()
        reg.register(_wan_local())
        assert "wan_local" in reg.contracts
        assert reg.contracts["wan_local"].location == "local"

    def test_resolve_direct_contract(self):
        reg = ProviderContractRegistry()
        reg.register(_wan_local())
        resolved = reg.resolve("wan_local")
        assert resolved.name == "wan_local"
        assert resolved.alias_of is None

    def test_resolve_alias_to_endpoint(self):
        reg = ProviderContractRegistry()
        reg.register(_wan_local())
        reg.register(_ltx2_local())
        resolved = reg.resolve("ltx2_local")
        assert resolved.name == "wan_local"

    def test_ltx2_local_pricing_equals_wan_local(self):
        reg = ProviderContractRegistry()
        reg.register(_wan_local())
        reg.register(_ltx2_local())
        pricing = reg.derive_pricing()
        wan_entry = pricing.lookup("video_gen", "wan_local", "wan_local", "per_second")
        ltx_entry = pricing.lookup("video_gen", "ltx2_local", "ltx2_local", "per_second")
        assert wan_entry is not None
        assert ltx_entry is not None
        assert ltx_entry.price_usd == wan_entry.price_usd

    def test_missing_provider_raises(self):
        reg = ProviderContractRegistry()
        with pytest.raises(ProviderNotFoundError):
            reg.resolve("nonexistent_provider")

    def test_derive_pricing_from_contracts(self):
        reg = ProviderContractRegistry()
        reg.register(_wan_local())
        reg.register(_wan_cloud())
        pricing = reg.derive_pricing()
        assert len(pricing.entries) == 2
        cloud_entry = pricing.lookup("video_gen", "wan_cloud", "wan_cloud", "per_second")
        assert cloud_entry is not None
        assert cloud_entry.price_usd == 0.08

    def test_local_provider_zero_cost(self):
        reg = ProviderContractRegistry()
        reg.register(_wan_local())
        pricing = reg.derive_pricing()
        entry = pricing.lookup("video_gen", "wan_local", "wan_local", "per_second")
        assert entry is not None
        assert entry.price_usd == 0.0

    def test_circular_alias_raises(self):
        reg = ProviderContractRegistry()
        a = ProviderContract(name="a", location="local", capability="llm",
                             unit_cost_usd=0.0, unit="per_call", alias_of="b")
        b = ProviderContract(name="b", location="local", capability="llm",
                             unit_cost_usd=0.0, unit="per_call", alias_of="a")
        reg.register(a)
        reg.register(b)
        with pytest.raises(ValueError, match="Circular"):
            reg.resolve("a")

    def test_broken_alias_chain_raises(self):
        reg = ProviderContractRegistry()
        reg.register(ProviderContract(
            name="ltx2_local", location="local", capability="video_gen",
            unit_cost_usd=0.0, unit="per_second", alias_of="wan_local",
        ))
        # wan_local not registered → broken chain
        with pytest.raises(ProviderNotFoundError):
            reg.resolve("ltx2_local")

    def test_multi_hop_alias_chain(self):
        reg = ProviderContractRegistry()
        reg.register(ProviderContract(name="c", location="local", capability="llm",
                                      unit_cost_usd=0.02, unit="per_call"))
        reg.register(ProviderContract(name="b", location="cloud", capability="llm",
                                      unit_cost_usd=0.0, unit="per_call", alias_of="c"))
        reg.register(ProviderContract(name="a", location="cloud", capability="llm",
                                      unit_cost_usd=0.0, unit="per_call", alias_of="b"))
        resolved = reg.resolve("a")
        assert resolved.name == "c"
        assert resolved.unit_cost_usd == 0.02
