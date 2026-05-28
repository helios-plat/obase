"""Email sender functions using Resend API."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class EmailClientError(Exception):
    """Base error for email_client submodule."""


def _send(
    *,
    api_key: str,
    from_addr: str,
    to: str,
    subject: str,
    html: str,
    text_body: str,
) -> None:
    """Low-level send via resend. Raises EmailClientError on failure."""
    import resend

    resend.api_key = api_key
    try:
        resend.Emails.send(
            {
                "from": from_addr,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text_body,
            }
        )
    except Exception as exc:
        raise EmailClientError(f"Email send failed to={to}: {exc}") from exc


async def send_magic_link_email(
    *,
    to: str,
    magic_url: str,
    api_key: str,
    from_addr: str,
    product_name: str = "App",
) -> None:
    """Send a magic-link login email.

    Args:
        to: Recipient email address.
        magic_url: One-time login URL (time-limited).
        api_key: Resend API key.
        from_addr: Sender address (e.g. "Name <noreply@example.com>").
        product_name: Product name shown in email body.

    Raises:
        EmailClientError: On send failure.

    Example:
        >>> await send_magic_link_email(
        ...     to="user@example.com", magic_url="https://...",
        ...     api_key="re_xxx", from_addr="App <no-reply@app.com>",
        ... )
    """
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;padding:40px;">
  <h2>{product_name} Login</h2>
  <p>Click below to log in (valid 15 minutes):</p>
  <a href="{magic_url}" style="display:inline-block;padding:12px 24px;
     background:#3b82f6;color:#fff;text-decoration:none;border-radius:6px;">
    Log in to {product_name}
  </a>
  <p style="font-size:13px;color:#666;">Or copy: {magic_url}</p>
</body></html>"""
    _send(
        api_key=api_key,
        from_addr=from_addr,
        to=to,
        subject=f"Login to {product_name}",
        html=html,
        text_body=f"Login link (15 min): {magic_url}",
    )
    log.info("magic_link_sent to=%s", to)


async def send_notification_email(
    *,
    to: str,
    title: str,
    body: str,
    api_key: str,
    from_addr: str,
) -> None:
    """Send a generic notification email.

    Args:
        to: Recipient email address.
        title: Email subject and heading.
        body: Plain text body content.
        api_key: Resend API key.
        from_addr: Sender address.

    Raises:
        EmailClientError: On send failure.

    Example:
        >>> await send_notification_email(
        ...     to="u@x.com", title="Alert", body="...",
        ...     api_key="re_xxx", from_addr="App <no-reply@app.com>",
        ... )
    """
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;padding:40px;">
  <h3>{title}</h3>
  <p style="white-space:pre-line;">{body}</p>
</body></html>"""
    _send(
        api_key=api_key,
        from_addr=from_addr,
        to=to,
        subject=title,
        html=html,
        text_body=body,
    )
    log.info("notification_email_sent to=%s title=%s", to, title)


async def send_upgrade_request_notification(
    *,
    request_id: str,
    user_email: str,
    target_tier: str,
    message: str,
    api_key: str,
    from_addr: str,
    admin_email: str,
    admin_url: str = "",
) -> None:
    """Notify admin of a user upgrade request.

    Args:
        request_id: Unique request identifier.
        user_email: Requesting user's email.
        target_tier: Tier being requested.
        message: User's message (may be empty).
        api_key: Resend API key.
        from_addr: Sender address.
        admin_email: Admin recipient address.
        admin_url: URL to admin panel.

    Raises:
        EmailClientError: On send failure.

    Example:
        >>> await send_upgrade_request_notification(
        ...     request_id="abc", user_email="u@x.com", target_tier="pro",
        ...     message="", api_key="re_xxx", from_addr="App <no-reply@app.com>",
        ...     admin_email="admin@x.com",
        ... )
    """
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;padding:40px;">
  <h2>Upgrade Request: {target_tier}</h2>
  <p>User: {user_email}</p>
  <p>Tier: {target_tier}</p>
  <p>Message: {message or "(none)"}</p>
  <p>Request ID: {request_id}</p>
  {f'<a href="{admin_url}">Admin Panel</a>' if admin_url else ""}
</body></html>"""
    _send(
        api_key=api_key,
        from_addr=from_addr,
        to=admin_email,
        subject=f"Upgrade Request - {target_tier}",
        html=html,
        text_body=f"Upgrade request from {user_email} to {target_tier}. ID: {request_id}",
    )
    log.info("upgrade_request_notified request_id=%s", request_id)


async def send_tier_approved_email(
    *,
    user_email: str,
    new_tier: str,
    features: list[str] | None = None,
    api_key: str,
    from_addr: str,
    app_url: str = "",
) -> None:
    """Notify user their tier upgrade was approved.

    Args:
        user_email: User's email address.
        new_tier: Newly activated tier name.
        features: List of feature descriptions for the tier.
        api_key: Resend API key.
        from_addr: Sender address.
        app_url: Application base URL for settings link.

    Raises:
        EmailClientError: On send failure.

    Example:
        >>> await send_tier_approved_email(
        ...     user_email="u@x.com", new_tier="pro",
        ...     api_key="re_xxx", from_addr="App <no-reply@app.com>",
        ... )
    """
    feat_list = features or []
    feat_html = "".join(f"<li>{f}</li>" for f in feat_list)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;padding:40px;">
  <h2>Your {new_tier} tier is now active</h2>
  {"<ul>" + feat_html + "</ul>" if feat_html else ""}
  {f'<a href="{app_url}/settings">Go to Settings</a>' if app_url else ""}
</body></html>"""
    _send(
        api_key=api_key,
        from_addr=from_addr,
        to=user_email,
        subject=f"Your {new_tier} tier is active",
        html=html,
        text_body=f"Your {new_tier} tier is now active.",
    )
    log.info("tier_approved_email_sent to=%s tier=%s", user_email, new_tier)
