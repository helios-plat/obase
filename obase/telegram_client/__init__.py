"""telegram_client — Telegram Bot API sendMessage client.

Provides async message sending via Telegram Bot API.

depends_on_external: httpx
"""

from __future__ import annotations

from obase.telegram_client.client import TelegramClient, send_message

__all__ = ["TelegramClient", "send_message", "TelegramClientError"]


class TelegramClientError(Exception):
    """Base error for telegram_client submodule."""
