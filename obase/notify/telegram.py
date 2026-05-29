"""notify.telegram — Pydantic-typed fire-and-return Telegram sendMessage helper.

depends_on_external: httpx
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramRequest(BaseModel):
    """Inputs for a single Telegram sendMessage call.

    Attributes:
        bot_token: Telegram Bot API token.
        chat_id: Target chat identifier (user id or @channel).
        text: Message body.
        parse_mode: Telegram markup mode. Defaults to ``"HTML"``.
        disable_notification: Send silently if True.

    Example:
        >>> req = TelegramRequest(bot_token="123:ABC", chat_id="456", text="Hello")
        >>> req.parse_mode
        'HTML'
    """

    bot_token: str = Field(..., min_length=1)
    chat_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    parse_mode: str = "HTML"
    disable_notification: bool = False


class TelegramResult(BaseModel):
    """Result of a :func:`telegram_send` call.

    Attributes:
        ok: True on success, False on any error.
        message_id: Telegram message id returned by the API on success.
        error: Human-readable error description when ``ok`` is False.

    Example:
        >>> result = TelegramResult(ok=True, message_id=42)
        >>> result.ok
        True
    """

    ok: bool
    message_id: int | None = None
    error: str | None = None


class TelegramSendError(Exception):
    """Raised only on hard programming errors (invalid input types).

    Network and API errors are captured and returned as
    ``TelegramResult(ok=False, error=...)`` — callers do not need try/except
    for the normal error path.
    """


async def telegram_send(request: TelegramRequest) -> TelegramResult:
    """Send a single Telegram message via Bot API and return a typed result.

    Network and HTTP errors are captured and surfaced as
    ``TelegramResult(ok=False, error=...)`` rather than raised, so callers
    can inspect ``.ok`` without wrapping in try/except.

    Args:
        request: :class:`TelegramRequest` with all required fields.

    Returns:
        :class:`TelegramResult` — ``ok=True`` with ``message_id`` on success;
        ``ok=False`` with ``error`` on any failure.

    Example:
        >>> req = TelegramRequest(bot_token="123:ABC", chat_id="456", text="Hi")
        >>> result = await telegram_send(req)
        >>> result.ok
        True
    """
    payload: dict[str, Any] = {
        "chat_id": request.chat_id,
        "text": request.text,
        "parse_mode": request.parse_mode,
        "disable_notification": request.disable_notification,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _SEND_URL.format(token=request.bot_token),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            message_id: int | None = None
            if isinstance(data.get("result"), dict):
                message_id = data["result"].get("message_id")
            return TelegramResult(ok=True, message_id=message_id)
    except httpx.HTTPStatusError as exc:
        log.warning("notify.telegram_send HTTP error: %s", exc)
        return TelegramResult(ok=False, error=str(exc))
    except Exception as exc:
        log.warning("notify.telegram_send failed: %s", exc)
        return TelegramResult(ok=False, error=str(exc))
