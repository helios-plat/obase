"""Tests for obase.tax_providers.FlatRateTaxProvider and the TaxProvider
Protocol's integration with ProviderRegistry's generic-category mechanism
(no separate TaxProviderRegistry class)."""

from __future__ import annotations

import pytest

from obase.provider_registry import ProviderRegistry, TaxProvider
from obase.tax_providers import FlatRateTaxProvider


@pytest.fixture(autouse=True)
def _clean_registry():
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


class TestFlatRateTaxProvider:
    async def test_calculate_applies_flat_rate(self):
        provider = FlatRateTaxProvider(rate_percent=8.0)
        result = await provider.calculate(address={"country": "US"}, items=[{"amount_cents": 1000}])
        assert result["tax_cents"] == 80
        assert result["rate_percent"] == 8.0

    async def test_calculate_sums_multiple_items(self):
        provider = FlatRateTaxProvider(rate_percent=10.0)
        result = await provider.calculate(
            address={},
            items=[{"amount_cents": 1000}, {"amount_cents": 2000}],
        )
        assert result["tax_cents"] == 300
        assert len(result["lines"]) == 2
        assert result["lines"][0]["tax_cents"] == 100
        assert result["lines"][1]["tax_cents"] == 200

    async def test_calculate_zero_rate(self):
        provider = FlatRateTaxProvider(rate_percent=0.0)
        result = await provider.calculate(address={}, items=[{"amount_cents": 1000}])
        assert result["tax_cents"] == 0

    async def test_negative_rate_rejected(self):
        with pytest.raises(ValueError, match="rate_percent"):
            FlatRateTaxProvider(rate_percent=-1.0)

    async def test_calculate_preserves_item_fields(self):
        provider = FlatRateTaxProvider(rate_percent=5.0)
        result = await provider.calculate(address={}, items=[{"amount_cents": 1000, "sku": "abc"}])
        assert result["lines"][0]["sku"] == "abc"


class TestTaxProviderRegistration:
    def test_flat_rate_provider_satisfies_protocol(self):
        provider = FlatRateTaxProvider(rate_percent=8.0)
        assert isinstance(provider, TaxProvider)

    def test_register_and_retrieve_via_generic_category(self):
        provider = FlatRateTaxProvider(rate_percent=8.0)
        ProviderRegistry.get().register_generic("tax", "flat", provider)
        retrieved = ProviderRegistry.get().generic("tax", "flat")
        assert retrieved is provider

    def test_unregistered_tax_provider_raises(self):
        from obase.exceptions import ProviderNotFoundError

        with pytest.raises(ProviderNotFoundError, match="tax.*ghost"):
            ProviderRegistry.get().generic("tax", "ghost")
