"""Telegram Bot API client implementation."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramClient:
    """Stateless Telegram Bot API client.

    Args:
        token: Telegram Bot API token.
        chat_id: Default chat ID for messages.

    Example:
        >>> client = TelegramClient(token="123:ABC", chat_id="456")
        >>> await client.send("Hello")
        True
    """

    def __init__(self, *, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    @property
    def enabled(self) -> bool:
        """Check if client is configured with token and chat_id."""
        return bool(self._token and self._chat_id)

    async def send(
        self,
        text: str,
        *,
        parse_mode: str = "MarkdownV2",
        chat_id: str | None = None,
    ) -> bool:
        """Send a message via Telegram Bot API.

        Args:
            text: Message text content.
            parse_mode: Telegram parse mode (MarkdownV2, HTML, Markdown).
            chat_id: Override default chat_id for this message.

        Returns:
            True on success, False on failure.

        Example:
            >>> await client.send("*bold*", parse_mode="MarkdownV2")
            True
        """
        if not self.enabled:
            log.debug("telegram_client: not configured, skipping")
            return False
        target_chat = chat_id or self._chat_id
        return await send_message(
            token=self._token,
            chat_id=target_chat,
            text=text,
            parse_mode=parse_mode,
        )


async def send_message(
    *,
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "MarkdownV2",
) -> bool:
    """Send a single Telegram message.

    Args:
        token: Bot API token.
        chat_id: Target chat identifier.
        text: Message text.
        parse_mode: Telegram parse mode.

    Returns:
        True on success, False on failure (never raises).

    Example:
        >>> await send_message(token="123:ABC", chat_id="456", text="hi")
        True
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                _SEND_URL.format(token=token),
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            )
            r.raise_for_status()
            return True
    except Exception as exc:
        log.warning("telegram_client.send_failed: %s", exc)
        return False
