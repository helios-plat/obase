"""obase.notification_providers — 内置 obase.NotificationProvider 实现。

LogNotificationProvider：不接真实邮件/短信网关,只把消息记进内存列表——
真实商户对接见 SendGrid/Twilio 等外部 SDK,不在本模块。用于没有真实网关
凭据的环境里跑集成测试,以及作为"通知先不接,但接口占位"场景的兜底实现。
"""

from __future__ import annotations

from typing import Any


class LogNotificationProvider:
    """把待发消息记进内存列表,不真的对外发送。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_email(self, *, to: str, subject: str, body: str) -> dict[str, Any]:
        record = {"channel": "email", "to": to, "subject": subject, "body": body}
        self.sent.append(record)
        return {"status": "sent", **record}

    async def send_sms(self, *, to: str, message: str) -> dict[str, Any]:
        record = {"channel": "sms", "to": to, "message": message}
        self.sent.append(record)
        return {"status": "sent", **record}
