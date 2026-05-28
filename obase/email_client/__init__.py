"""email_client — HTML email sending via Resend API.

Provides send functions for transactional emails (magic link, notification,
upgrade request, tier approval).

depends_on_external: resend
"""
from __future__ import annotations

from obase.email_client.sender import EmailClientError

__all__ = [
    "send_magic_link_email",
    "send_notification_email",
    "send_tier_approved_email",
    "send_upgrade_request_notification",
    "EmailClientError",
]


def __getattr__(name: str):  # noqa: ANN204
    """Lazy import to avoid requiring 'resend' at import time."""
    if name in (
        "send_magic_link_email",
        "send_notification_email",
        "send_tier_approved_email",
        "send_upgrade_request_notification",
    ):
        from obase.email_client.sender import (
            send_magic_link_email,
            send_notification_email,
            send_tier_approved_email,
            send_upgrade_request_notification,
        )

        _funcs = {
            "send_magic_link_email": send_magic_link_email,
            "send_notification_email": send_notification_email,
            "send_tier_approved_email": send_tier_approved_email,
            "send_upgrade_request_notification": send_upgrade_request_notification,
        }
        return _funcs[name]
    raise AttributeError(
        f"module 'obase.email_client' has no attribute {name!r}"
    )
