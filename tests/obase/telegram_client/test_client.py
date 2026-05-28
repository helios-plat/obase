"""Tests for obase.telegram_client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from obase.telegram_client import TelegramClient, TelegramClientError, send_message


@pytest.mark.asyncio
@patch("obase.telegram_client.client.httpx.AsyncClient")
async def test_send_message_success(mock_client_cls):
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client

    result = await send_message(token="123:ABC", chat_id="456", text="hello")
    assert result is True


@pytest.mark.asyncio
@patch("obase.telegram_client.client.httpx.AsyncClient")
async def test_send_message_failure(mock_client_cls):
    mock_client = AsyncMock()
    mock_client.post.side_effect = RuntimeError("network error")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client

    result = await send_message(token="123:ABC", chat_id="456", text="hello")
    assert result is False


@pytest.mark.asyncio
async def test_telegram_client_not_configured():
    client = TelegramClient(token="", chat_id="")
    assert client.enabled is False
    result = await client.send("test")
    assert result is False


@pytest.mark.asyncio
@patch("obase.telegram_client.client.httpx.AsyncClient")
async def test_telegram_client_send_success(mock_client_cls):
    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client

    client = TelegramClient(token="123:ABC", chat_id="456")
    assert client.enabled is True
    result = await client.send("hello world")
    assert result is True


@pytest.mark.asyncio
async def test_telegram_client_enabled_property():
    client = TelegramClient(token="tok", chat_id="cid")
    assert client.enabled is True


def test_telegram_client_error_is_exception():
    assert issubclass(TelegramClientError, Exception)
