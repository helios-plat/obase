"""Tests for obase.notification.NotificationComplianceFilter (D2)."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from obase.notification import NotificationComplianceFilter


def _make_filter() -> NotificationComplianceFilter:
    f = NotificationComplianceFilter()
    f.register_quiet_hours(start_time=time(22, 0), end_time=time(7, 0), timezone="Asia/Shanghai", scope="non_critical")
    f.register_disclaimer_template(channel="*", template="{content}\n\n—— 本信息仅供参考,不构成投资建议")
    return f


class TestNotificationComplianceFilter:
    def test_quiet_hours_blocks_non_critical(self) -> None:
        f = _make_filter()
        msg = {"channel": "telegram", "severity": "info", "content": "Test", "timestamp": datetime(2026, 5, 23, 23, 30, tzinfo=ZoneInfo("Asia/Shanghai"))}
        assert f.filter(msg) is None

    def test_quiet_hours_passes_critical(self) -> None:
        f = _make_filter()
        msg = {"channel": "telegram", "severity": "critical", "content": "Alert", "timestamp": datetime(2026, 5, 23, 23, 30, tzinfo=ZoneInfo("Asia/Shanghai"))}
        result = f.filter(msg)
        assert result is not None
        assert "Alert" in str(result["content"])

    def test_disclaimer_template_injected(self) -> None:
        f = _make_filter()
        msg = {"channel": "telegram", "severity": "info", "content": "茅台涨停", "timestamp": datetime(2026, 5, 23, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))}
        result = f.filter(msg)
        assert result is not None
        assert "本信息仅供参考" in str(result["content"])

    def test_multi_channel_template_independent(self) -> None:
        f = NotificationComplianceFilter()
        f.register_disclaimer_template(channel="email", template="{content}\n-- Email disclaimer")
        f.register_disclaimer_template(channel="sms", template="{content} [SMS]")
        msg_email = {"channel": "email", "severity": "info", "content": "Hi"}
        msg_sms = {"channel": "sms", "severity": "info", "content": "Hi"}
        r1 = f.filter(msg_email)
        r2 = f.filter(msg_sms)
        assert r1 is not None and "Email disclaimer" in str(r1["content"])
        assert r2 is not None and "[SMS]" in str(r2["content"])

    def test_wildcard_template_fallback(self) -> None:
        f = NotificationComplianceFilter()
        f.register_disclaimer_template(channel="*", template="{content} [WILD]")
        msg = {"channel": "unknown_channel", "severity": "info", "content": "X"}
        result = f.filter(msg)
        assert result is not None
        assert "[WILD]" in str(result["content"])

    def test_blocked_keyword_returns_none(self) -> None:
        f = NotificationComplianceFilter()
        f.register_blocked_keywords(["违禁词"])
        msg = {"channel": "telegram", "severity": "info", "content": "包含违禁词的消息"}
        assert f.filter(msg) is None

    def test_timezone_cross_midnight(self) -> None:
        """22:00-07:00 quiet hours cross midnight."""
        f = _make_filter()
        # 06:30 Shanghai = within quiet hours (after midnight)
        msg = {"channel": "telegram", "severity": "info", "content": "Early", "timestamp": datetime(2026, 5, 24, 6, 30, tzinfo=ZoneInfo("Asia/Shanghai"))}
        assert f.filter(msg) is None
        # 08:00 Shanghai = outside quiet hours
        msg2 = {"channel": "telegram", "severity": "info", "content": "Morning", "timestamp": datetime(2026, 5, 24, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))}
        assert f.filter(msg2) is not None

    def test_quiet_end_before_start_same_day(self) -> None:
        """When start > end, it means cross-midnight."""
        f = NotificationComplianceFilter()
        f.register_quiet_hours(start_time=time(23, 0), end_time=time(5, 0), timezone="UTC", scope="non_critical")
        # 00:30 UTC = within quiet (after midnight)
        msg = {"channel": "x", "severity": "info", "content": "Y", "timestamp": datetime(2026, 5, 24, 0, 30, tzinfo=ZoneInfo("UTC"))}
        assert f.filter(msg) is None
        # 12:00 UTC = outside
        msg2 = {"channel": "x", "severity": "info", "content": "Y", "timestamp": datetime(2026, 5, 24, 12, 0, tzinfo=ZoneInfo("UTC"))}
        assert f.filter(msg2) is not None

    def test_combined_quiet_and_keyword(self) -> None:
        f = _make_filter()
        f.register_blocked_keywords(["spam"])
        # Blocked by keyword even during business hours
        msg = {"channel": "telegram", "severity": "info", "content": "spam content", "timestamp": datetime(2026, 5, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))}
        assert f.filter(msg) is None
