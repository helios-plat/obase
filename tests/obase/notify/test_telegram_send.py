"""Tests for obase.notify.telegram_send."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from obase.notify import TelegramRequest, TelegramResult, telegram_send

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_mock_client(
    json_body: dict | None = None, raise_exc: Exception | None = None
) -> AsyncMock:
    """Build a mock httpx.AsyncClient for patching."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    if raise_exc:
        mock_resp.raise_for_status.side_effect = raise_exc
    mock_resp.json.return_value = json_body or {"ok": True, "result": {"message_id": 42}}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


_REQ = TelegramRequest(bot_token="123:ABC", chat_id="456", text="Hello")


# ── TelegramRequest validation ────────────────────────────────────────────────


class TestTelegramRequest:
    def test_defaults(self):
        req = TelegramRequest(bot_token="tok", chat_id="123", text="hi")
        assert req.parse_mode == "HTML"
        assert req.disable_notification is False

    def test_empty_bot_token_raises(self):
        with pytest.raises(ValidationError):
            TelegramRequest(bot_token="", chat_id="123", text="hi")

    def test_empty_chat_id_raises(self):
        with pytest.raises(ValidationError):
            TelegramRequest(bot_token="tok", chat_id="", text="hi")

    def test_empty_text_raises(self):
        with pytest.raises(ValidationError):
            TelegramRequest(bot_token="tok", chat_id="123", text="")

    def test_custom_parse_mode(self):
        req = TelegramRequest(bot_token="tok", chat_id="123", text="hi", parse_mode="Markdown")
        assert req.parse_mode == "Markdown"


# ── telegram_send behaviour ───────────────────────────────────────────────────


class TestTelegramSend:
    async def test_success_returns_ok_true_with_message_id(self):
        mock_client = _make_mock_client({"ok": True, "result": {"message_id": 42}})
        with patch("obase.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            result = await telegram_send(_REQ)
        assert isinstance(result, TelegramResult)
        assert result.ok is True
        assert result.message_id == 42
        assert result.error is None

    async def test_http_status_error_returns_ok_false(self):
        exc = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=MagicMock())
        mock_client = _make_mock_client(raise_exc=exc)
        with patch("obase.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            result = await telegram_send(_REQ)
        assert result.ok is False
        assert result.error is not None

    async def test_connection_error_returns_ok_false(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        with patch("obase.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            result = await telegram_send(_REQ)
        assert result.ok is False
        assert "connection refused" in (result.error or "")

    async def test_payload_includes_disable_notification(self):
        mock_client = _make_mock_client()
        req = TelegramRequest(
            bot_token="tok", chat_id="123", text="silent", disable_notification=True
        )
        with patch("obase.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            await telegram_send(req)
        _, call_kwargs = mock_client.post.call_args
        assert call_kwargs.get("json", {}).get("disable_notification") is True

    async def test_missing_message_id_in_response_gives_none(self):
        mock_client = _make_mock_client({"ok": True, "result": {}})
        with patch("obase.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            result = await telegram_send(_REQ)
        assert result.ok is True
        assert result.message_id is None

    async def test_result_without_result_key_gives_none_message_id(self):
        mock_client = _make_mock_client({"ok": True})
        with patch("obase.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            result = await telegram_send(_REQ)
        assert result.ok is True
        assert result.message_id is None

    async def test_post_called_with_correct_url(self):
        mock_client = _make_mock_client()
        with patch("obase.notify.telegram.httpx.AsyncClient", return_value=mock_client):
            await telegram_send(TelegramRequest(bot_token="MYTOKEN", chat_id="789", text="x"))
        url_called = mock_client.post.call_args[0][0]
        assert "MYTOKEN" in url_called
