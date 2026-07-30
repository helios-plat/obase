"""Tests for obase.payment_providers.ManualPaymentProvider and the
PaymentProvider Protocol's integration with the existing ProviderRegistry
generic-category mechanism (no separate PaymentProviderRegistry class)."""

from __future__ import annotations

import pytest

from obase.payment_providers import ManualPaymentProvider
from obase.provider_registry import PaymentProvider, ProviderRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


class TestManualPaymentProviderLifecycle:
    async def test_authorize_returns_intent_id(self):
        provider = ManualPaymentProvider()
        result = await provider.authorize(amount=1000, currency="CNY")
        assert result["status"] == "authorized"
        assert result["amount"] == 1000
        assert result["intent_id"].startswith("manual_")

    async def test_authorize_then_capture(self):
        provider = ManualPaymentProvider()
        auth = await provider.authorize(amount=1000, currency="CNY")
        captured = await provider.capture(intent_id=auth["intent_id"])
        assert captured["status"] == "captured"
        assert captured["amount"] == 1000

    async def test_capture_then_refund(self):
        provider = ManualPaymentProvider()
        auth = await provider.authorize(amount=1000, currency="CNY")
        await provider.capture(intent_id=auth["intent_id"])
        refunded = await provider.refund(intent_id=auth["intent_id"], amount=400)
        assert refunded["status"] == "refunded"
        assert refunded["amount"] == 400

    async def test_authorize_then_cancel(self):
        provider = ManualPaymentProvider()
        auth = await provider.authorize(amount=1000, currency="CNY")
        canceled = await provider.cancel(intent_id=auth["intent_id"])
        assert canceled["status"] == "canceled"

    async def test_capture_without_authorize_raises(self):
        provider = ManualPaymentProvider()
        with pytest.raises(ValueError, match="unknown manual payment intent"):
            await provider.capture(intent_id="ghost")

    async def test_refund_without_capture_raises(self):
        provider = ManualPaymentProvider()
        auth = await provider.authorize(amount=1000, currency="CNY")
        with pytest.raises(ValueError, match="cannot refund"):
            await provider.refund(intent_id=auth["intent_id"], amount=100)

    async def test_refund_exceeding_captured_amount_raises(self):
        provider = ManualPaymentProvider()
        auth = await provider.authorize(amount=1000, currency="CNY")
        await provider.capture(intent_id=auth["intent_id"])
        with pytest.raises(ValueError, match="exceeds captured amount"):
            await provider.refund(intent_id=auth["intent_id"], amount=2000)

    async def test_cancel_after_capture_raises(self):
        provider = ManualPaymentProvider()
        auth = await provider.authorize(amount=1000, currency="CNY")
        await provider.capture(intent_id=auth["intent_id"])
        with pytest.raises(ValueError, match="cannot cancel"):
            await provider.cancel(intent_id=auth["intent_id"])

    async def test_double_capture_raises(self):
        provider = ManualPaymentProvider()
        auth = await provider.authorize(amount=1000, currency="CNY")
        await provider.capture(intent_id=auth["intent_id"])
        with pytest.raises(ValueError, match="cannot capture"):
            await provider.capture(intent_id=auth["intent_id"])

    async def test_two_intents_are_independent(self):
        provider = ManualPaymentProvider()
        a = await provider.authorize(amount=100, currency="CNY")
        b = await provider.authorize(amount=200, currency="CNY")
        assert a["intent_id"] != b["intent_id"]
        await provider.capture(intent_id=a["intent_id"])
        # b is untouched — still authorize-only, cancel must still work.
        canceled = await provider.cancel(intent_id=b["intent_id"])
        assert canceled["status"] == "canceled"


class TestPaymentProviderRegistration:
    def test_manual_provider_satisfies_protocol(self):
        provider = ManualPaymentProvider()
        assert isinstance(provider, PaymentProvider)

    def test_register_and_retrieve_via_generic_category(self):
        provider = ManualPaymentProvider()
        ProviderRegistry.get().register_generic("payment", "manual", provider)
        retrieved = ProviderRegistry.get().generic("payment", "manual")
        assert retrieved is provider

    def test_unregistered_payment_provider_raises(self):
        from obase.exceptions import ProviderNotFoundError

        with pytest.raises(ProviderNotFoundError, match="payment.*ghost"):
            ProviderRegistry.get().generic("payment", "ghost")
