"""notify — Outbound notification helpers.

depends_on_external: httpx (telegram)
"""

from __future__ import annotations

from obase.notify.telegram import TelegramRequest, TelegramResult, TelegramSendError, telegram_send

__all__ = [
    "telegram_send",
    "TelegramRequest",
    "TelegramResult",
    "TelegramSendError",
]
