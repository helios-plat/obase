from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal


class WebhookSignError(Exception):
    """webhook 签名失败."""


def sign_payload(
    *,
    payload: dict[str, Any] | bytes,
    secret: str,
    algo: Literal["sha256", "sha512"] = "sha256",
) -> str:
    """HMAC 签名 payload (webhook 鉴权用)."""
    if len(secret) < 32:
        raise WebhookSignError(f"secret too short ({len(secret)} bytes), need ≥32")

    if algo not in ("sha256", "sha512"):
        raise WebhookSignError(f"unsupported algo: {algo}")

    if isinstance(payload, dict):
        try:
            payload_bytes = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")
        except (TypeError, ValueError) as e:
            raise WebhookSignError(f"payload not serializable: {e}") from e
    elif isinstance(payload, bytes):
        payload_bytes = payload
    else:
        raise WebhookSignError(f"payload must be dict or bytes, got {type(payload)}")

    hash_func = hashlib.sha256 if algo == "sha256" else hashlib.sha512
    mac = hmac.new(secret.encode("utf-8"), payload_bytes, hash_func)
    return mac.hexdigest()
