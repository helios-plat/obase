"""Tests for obase.email_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from obase.email_client import EmailClientError
from obase.email_client.sender import (
    send_magic_link_email,
    send_notification_email,
    send_tier_approved_email,
    send_upgrade_request_notification,
)

# The email sender integrates the optional `resend` SDK; skip its tests when absent.
resend = pytest.importorskip("resend")


@pytest.mark.asyncio
@patch("obase.email_client.sender.resend")
async def test_send_magic_link_email_success(mock_resend: MagicMock):
    mock_resend.Emails.send = MagicMock()
    await send_magic_link_email(
        to="user@example.com",
        magic_url="https://example.com/login?token=abc",
        api_key="re_test",
        from_addr="App <no-reply@app.com>",
    )
    mock_resend.Emails.send.assert_called_once()


@pytest.mark.asyncio
@patch("obase.email_client.sender.resend")
async def test_send_magic_link_email_failure(mock_resend: MagicMock):
    mock_resend.Emails.send = MagicMock(side_effect=RuntimeError("API down"))
    with pytest.raises(EmailClientError):
        await send_magic_link_email(
            to="user@example.com",
            magic_url="https://example.com/login",
            api_key="re_test",
            from_addr="App <no-reply@app.com>",
        )


@pytest.mark.asyncio
@patch("obase.email_client.sender.resend")
async def test_send_notification_email_success(mock_resend: MagicMock):
    mock_resend.Emails.send = MagicMock()
    await send_notification_email(
        to="user@example.com",
        title="Alert",
        body="Something happened",
        api_key="re_test",
        from_addr="App <no-reply@app.com>",
    )
    mock_resend.Emails.send.assert_called_once()


@pytest.mark.asyncio
@patch("obase.email_client.sender.resend")
async def test_send_upgrade_request_notification_success(mock_resend: MagicMock):
    mock_resend.Emails.send = MagicMock()
    await send_upgrade_request_notification(
        request_id="req-123",
        user_email="user@example.com",
        target_tier="pro",
        message="Please upgrade me",
        api_key="re_test",
        from_addr="App <no-reply@app.com>",
        admin_email="admin@example.com",
    )
    mock_resend.Emails.send.assert_called_once()


@pytest.mark.asyncio
@patch("obase.email_client.sender.resend")
async def test_send_tier_approved_email_success(mock_resend: MagicMock):
    mock_resend.Emails.send = MagicMock()
    await send_tier_approved_email(
        user_email="user@example.com",
        new_tier="pro",
        features=["Feature A", "Feature B"],
        api_key="re_test",
        from_addr="App <no-reply@app.com>",
    )
    mock_resend.Emails.send.assert_called_once()


@pytest.mark.asyncio
@patch("obase.email_client.sender.resend")
async def test_send_tier_approved_email_no_features(mock_resend: MagicMock):
    mock_resend.Emails.send = MagicMock()
    await send_tier_approved_email(
        user_email="user@example.com",
        new_tier="max",
        api_key="re_test",
        from_addr="App <no-reply@app.com>",
    )
    mock_resend.Emails.send.assert_called_once()


def test_email_client_error_is_exception():
    assert issubclass(EmailClientError, Exception)
