"""obase.channel_adapter — 消息通道传输适配器 (WAVE I).

ProviderRegistry(category="channel") 为唯一注册入口。
最小 transport contract: send / receive-poll / ack / metadata.

ChannelWatcherEngine 只负责 generic watcher lifecycle (见 oservi);
adapter 不持有 Bot identity / conversation policy / approval policy /
user business state,仅持传输凭证与游标。

真实传输 (httpx, api_base 可注入,默认官方 API):
- TelegramChannelAdapter (Bot API: sendMessage/getUpdates)
- SlackChannelAdapter    (Web API: chat.postMessage/conversations.history)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CHANNEL_CATEGORY",
    "ChannelAdapter",
    "ChannelMessage",
    "BaseChannelAdapter",
    "TelegramChannelAdapter",
    "SlackChannelAdapter",
    "register_channel_adapters",
]

CHANNEL_CATEGORY = "channel"


@dataclass
class ChannelMessage:
    """传输层消息 (形状 only,无业务语义)。"""

    message_id: str
    chat: str
    text: str
    ts: float = 0.0
    native: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ChannelAdapter(Protocol):
    """最小 transport contract。"""

    @property
    def name(self) -> str: ...
    async def send(self, chat: str, text: str) -> bool: ...
    async def receive(self, *, limit: int = 10) -> list[ChannelMessage]: ...
    async def ack(self, message_id: str) -> bool: ...
    async def metadata(self) -> dict[str, Any]: ...


class ChannelAdapterError(RuntimeError):
    """channel transport 错误。"""


class BaseChannelAdapter:
    """传输基类:仅凭证 + 游标,不持业务态。"""

    adapter_name: str = "base"

    def __init__(self, *, token: str, default_chat: str = "", api_base: str = "") -> None:
        self.token = token
        self.default_chat = default_chat
        self.api_base = api_base.rstrip("/")
        self._offset: str = ""  # 传输游标 (offset/cursor),非业务态

    @property
    def name(self) -> str:
        return self.adapter_name

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def send(self, chat: str, text: str) -> bool:
        raise NotImplementedError

    async def receive(self, *, limit: int = 10) -> list[ChannelMessage]:
        raise NotImplementedError

    async def ack(self, message_id: str) -> bool:
        raise NotImplementedError

    async def metadata(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter_name,
            "configured": self.configured,
            "default_chat": self.default_chat,
            "cursor": self._offset,
        }


class TelegramChannelAdapter(BaseChannelAdapter):
    """Telegram Bot API 传输 (sendMessage/getUpdates)。"""

    adapter_name = "telegram"

    def __init__(
        self, *, token: str, default_chat: str = "", api_base: str = "https://api.telegram.org"
    ) -> None:
        super().__init__(token=token, default_chat=default_chat, api_base=api_base)

    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    async def send(self, chat: str, text: str) -> bool:
        import httpx

        if not self.configured or not text:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    self._url("sendMessage"),
                    json={"chat_id": chat or self.default_chat, "text": text},
                )
                resp.raise_for_status()
                return True
        except Exception:
            return False

    async def receive(self, *, limit: int = 10) -> list[ChannelMessage]:
        import httpx

        if not self.configured:
            return []
        params: dict[str, Any] = {"limit": limit, "timeout": 0}
        if self._offset:
            params["offset"] = self._offset
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self._url("getUpdates"), params=params)
                resp.raise_for_status()
                updates = resp.json().get("result", [])
        except Exception:
            return []
        messages: list[ChannelMessage] = []
        for update in updates if isinstance(updates, list) else []:
            msg = update.get("message") or update.get("edited_message") or {}
            messages.append(
                ChannelMessage(
                    message_id=str(update.get("update_id", "")),
                    chat=str(msg.get("chat", {}).get("id", "")),
                    text=str(msg.get("text", "")),
                    ts=float(msg.get("date", 0)),
                    native=update if isinstance(update, dict) else {},
                )
            )
        if updates:
            self._offset = str(max(int(u.get("update_id", 0)) for u in updates) + 1)
        return messages

    async def ack(self, message_id: str) -> bool:
        if not message_id:
            return False
        try:
            nxt = int(message_id) + 1
        except ValueError:
            return False
        if not self._offset or nxt > int(self._offset):
            self._offset = str(nxt)
        return True


class SlackChannelAdapter(BaseChannelAdapter):
    """Slack Web API 传输 (chat.postMessage/conversations.history)。"""

    adapter_name = "slack"

    def __init__(
        self, *, token: str, default_chat: str = "", api_base: str = "https://slack.com/api"
    ) -> None:
        super().__init__(token=token, default_chat=default_chat, api_base=api_base)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def send(self, chat: str, text: str) -> bool:
        import httpx

        if not self.configured or not text:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.api_base}/chat.postMessage",
                    headers=self._headers(),
                    json={"channel": chat or self.default_chat, "text": text},
                )
                resp.raise_for_status()
                return bool(resp.json().get("ok", False))
        except Exception:
            return False

    async def receive(self, *, limit: int = 10) -> list[ChannelMessage]:
        import httpx

        if not self.configured:
            return []
        params: dict[str, Any] = {
            "channel": self.default_chat,
            "limit": limit,
        }
        if self._offset:
            params["oldest"] = self._offset
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.api_base}/conversations.history",
                    headers=self._headers(),
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok", False):
                    return []
                raw = data.get("messages", [])
        except Exception:
            return []
        messages = [
            ChannelMessage(
                message_id=str(m.get("ts", "")),
                chat=self.default_chat,
                text=str(m.get("text", "")),
                ts=time.time(),
                native=m if isinstance(m, dict) else {},
            )
            for m in raw
            if isinstance(m, dict)
        ]
        if messages:
            self._offset = messages[0].message_id
        return messages

    async def ack(self, message_id: str) -> bool:
        if not message_id:
            return False
        self._offset = message_id
        return True


def register_channel_adapters(registry: Any | None = None, **configs: Any) -> list[str]:
    """注册 channel adapters (category="channel"); configs 透传构造参数。"""
    from obase.provider_registry import ProviderRegistry

    reg = registry or ProviderRegistry.get()
    adapters = [
        TelegramChannelAdapter(**configs.get("telegram", {})) if configs.get("telegram") else None,
        SlackChannelAdapter(**configs.get("slack", {})) if configs.get("slack") else None,
    ]
    names: list[str] = []
    for adapter in adapters:
        if adapter is None:
            continue
        reg.register(CHANNEL_CATEGORY, adapter.name, adapter, replace=True)
        names.append(adapter.name)
    return names
