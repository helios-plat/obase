"""Tests for obase.fulfillment_providers.ManualFulfillmentProvider and the
FulfillmentProvider Protocol's integration with ProviderRegistry's
generic-category mechanism (no separate FulfillmentProviderRegistry class)."""

from __future__ import annotations

import pytest

from obase.fulfillment_providers import ManualFulfillmentProvider
from obase.provider_registry import FulfillmentProvider, ProviderRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


class TestManualFulfillmentProvider:
    async def test_get_rates_returns_flat_rate(self):
        provider = ManualFulfillmentProvider(flat_rate_cents=800)
        rates = await provider.get_rates(package={"weight_g": 500}, address={"country": "CN"})
        assert rates == [{"carrier": "manual", "service": "standard", "rate_cents": 800}]

    async def test_get_rates_uses_default_rate(self):
        provider = ManualFulfillmentProvider()
        rates = await provider.get_rates(package={}, address={})
        assert rates[0]["rate_cents"] == 500

    async def test_create_label_returns_tracking_number(self):
        provider = ManualFulfillmentProvider()
        label = await provider.create_label(shipment_info={"to": "somewhere"})
        assert label["status"] == "created"
        assert label["tracking_number"].startswith("manual_")

    async def test_cancel_label_succeeds_once(self):
        provider = ManualFulfillmentProvider()
        label = await provider.create_label(shipment_info={"to": "somewhere"})
        ok = await provider.cancel_label(tracking_number=label["tracking_number"])
        assert ok is True

    async def test_cancel_label_twice_returns_false(self):
        provider = ManualFulfillmentProvider()
        label = await provider.create_label(shipment_info={"to": "somewhere"})
        await provider.cancel_label(tracking_number=label["tracking_number"])
        ok = await provider.cancel_label(tracking_number=label["tracking_number"])
        assert ok is False

    async def test_cancel_unknown_label_returns_false(self):
        provider = ManualFulfillmentProvider()
        ok = await provider.cancel_label(tracking_number="ghost")
        assert ok is False


class TestFulfillmentProviderRegistration:
    def test_manual_provider_satisfies_protocol(self):
        provider = ManualFulfillmentProvider()
        assert isinstance(provider, FulfillmentProvider)

    def test_register_and_retrieve_via_generic_category(self):
        provider = ManualFulfillmentProvider()
        ProviderRegistry.get().register_generic("fulfillment", "manual", provider)
        retrieved = ProviderRegistry.get().generic("fulfillment", "manual")
        assert retrieved is provider

    def test_unregistered_fulfillment_provider_raises(self):
        from obase.exceptions import ProviderNotFoundError

        with pytest.raises(ProviderNotFoundError, match="fulfillment.*ghost"):
            ProviderRegistry.get().generic("fulfillment", "ghost")
