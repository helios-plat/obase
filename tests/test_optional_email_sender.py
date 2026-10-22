"""Tests for email sender importability when the optional SDK is absent."""

from __future__ import annotations

import pytest

from obase.email_client import EmailClientError
from obase.email_client import sender


def test_send_fails_clearly_when_resend_sdk_is_unavailable(monkeypatch):
    monkeypatch.setattr(sender, "resend", None)

    with pytest.raises(EmailClientError, match="resend SDK is not installed"):
        sender._send(
            api_key="test-only",
            from_addr="App <no-reply@example.com>",
            to="user@example.com",
            subject="Hello",
            html="<p>Hello</p>",
            text_body="Hello",
        )
