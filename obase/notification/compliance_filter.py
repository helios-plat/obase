"""D2 — Notification compliance filter (quiet hours, disclaimer, blocked keywords)."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


class NotificationComplianceFilter:
    """Filter notifications based on quiet hours, disclaimers, and blocked keywords."""

    def __init__(self) -> None:
        self._quiet_hours: list[dict[str, object]] = []
        self._disclaimer_templates: dict[str, str] = {}
        self._blocked_keywords: list[str] = []

    def register_quiet_hours(
        self,
        *,
        start_time: time,
        end_time: time,
        timezone: str = "UTC",
        scope: str = "non_critical",
    ) -> None:
        """Register quiet hours. During quiet hours, non-critical notifications are blocked."""
        self._quiet_hours.append({
            "start": start_time,
            "end": end_time,
            "timezone": timezone,
            "scope": scope,
        })

    def register_disclaimer_template(
        self,
        *,
        channel: str,
        template: str,
    ) -> None:
        """Register a disclaimer template for a channel. Use '*' for wildcard."""
        self._disclaimer_templates[channel] = template

    def register_blocked_keywords(self, keywords: list[str]) -> None:
        """Register blocked keywords. Messages containing any keyword are blocked."""
        self._blocked_keywords.extend(keywords)

    def filter(self, message: dict[str, object]) -> dict[str, object] | None:
        """Apply compliance filters to a message.

        Returns None if message should be blocked, otherwise returns modified message.
        """
        channel = str(message.get("channel", ""))
        severity = str(message.get("severity", "info"))
        content = str(message.get("content", ""))
        timestamp = message.get("timestamp")

        # Check blocked keywords
        for kw in self._blocked_keywords:
            if kw in content:
                return None

        # Check quiet hours
        if timestamp is not None and self._is_in_quiet_hours(timestamp, severity):
            return None

        # Apply disclaimer
        content = self._apply_disclaimer(content, channel)

        return {**message, "content": content}

    def _is_in_quiet_hours(self, timestamp: object, severity: str) -> bool:
        if not isinstance(timestamp, datetime):
            return False
        for rule in self._quiet_hours:
            scope = str(rule["scope"])
            if scope == "non_critical" and severity == "critical":
                continue
            tz = ZoneInfo(str(rule["timezone"]))
            local_time = timestamp.astimezone(tz).time()
            start = rule["start"]
            end = rule["end"]
            assert isinstance(start, time)
            assert isinstance(end, time)
            if start <= end:
                if start <= local_time <= end:
                    return True
            else:
                # Cross-midnight: e.g. 22:00 - 07:00
                if local_time >= start or local_time <= end:
                    return True
        return False

    def _apply_disclaimer(self, content: str, channel: str) -> str:
        template = self._disclaimer_templates.get(channel)
        if template is None:
            template = self._disclaimer_templates.get("*")
        if template is not None:
            return template.format(content=content)
        return content
