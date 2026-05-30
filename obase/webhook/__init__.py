"""webhook — HMAC webhook signing helpers."""

from __future__ import annotations

from obase.webhook._signer import WebhookSignError, sign_payload

__all__ = ["sign_payload", "WebhookSignError"]
