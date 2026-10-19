"""Tests for obase.notification_providers.LogNotificationProvider and the
NotificationProvider Protocol's integration with ProviderRegistry's
generic-category mechanism (no separate NotificationProviderRegistry class)."""

from __future__ import annotations

import pytest

from obase.notification_providers import LogNotificationProvider
from obase.provider_registry import NotificationProvider, ProviderRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    ProviderRegistry.clear()
    yield
    ProviderRegistry.clear()


class TestLogNotificationProvider:
    async def test_send_email_records_message(self):
        provider = LogNotificationProvider()
        result = await provider.send_email(to="a@x.com", subject="hi", body="hello")
        assert result["status"] == "sent"
        assert provider.sent == [
            {"channel": "email", "to": "a@x.com", "subject": "hi", "body": "hello"}
        ]

    async def test_send_sms_records_message(self):
        provider = LogNotificationProvider()
        result = await provider.send_sms(to="+8613800000000", message="code: 123456")
        assert result["status"] == "sent"
        assert provider.sent == [
            {"channel": "sms", "to": "+8613800000000", "message": "code: 123456"}
        ]

    async def test_multiple_sends_accumulate(self):
        provider = LogNotificationProvider()
        await provider.send_email(to="a@x.com", subject="s1", body="b1")
        await provider.send_sms(to="+861", message="m1")
        assert len(provider.sent) == 2


class TestNotificationProviderRegistration:
    def test_log_provider_satisfies_protocol(self):
        provider = LogNotificationProvider()
        assert isinstance(provider, NotificationProvider)

    def test_register_and_retrieve_via_generic_category(self):
        provider = LogNotificationProvider()
        ProviderRegistry.get().register_generic("notification", "log", provider)
        retrieved = ProviderRegistry.get().generic("notification", "log")
        assert retrieved is provider

    def test_unregistered_notification_provider_raises(self):
        from obase.exceptions import ProviderNotFoundError

        with pytest.raises(ProviderNotFoundError, match="notification.*ghost"):
            ProviderRegistry.get().generic("notification", "ghost")
