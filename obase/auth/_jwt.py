from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import jwt as pyjwt


class JWTSignError(Exception):
    """JWT signing failed."""


class JWTVerifyError(Exception):
    """JWT verification failed."""


def jwt_sign_hs256(
    *,
    payload: dict[str, Any],
    secret: str,
    expires_in_seconds: int | None = None,
) -> str:
    """HS256 JWT signing.

    HMAC-SHA256 symmetric-key signing, suitable for same-service
    issue-and-verify. Not appropriate for cross-service trust
    (use RS256 asymmetric keys instead).

    Args:
        payload: JWT claims dict. ``iat`` is always added; ``exp`` is
            added when *expires_in_seconds* is not ``None``.
        secret: HMAC secret (≥32 bytes).
        expires_in_seconds: Lifetime in seconds. ``None`` means no
            expiry (not recommended outside tests).

    Returns:
        JWT string in ``<header>.<payload>.<signature>`` format.

    Raises:
        JWTSignError: Secret too short, or payload not JSON-serialisable.

    Example:
        >>> token = jwt_sign_hs256(
        ...     payload={"user_id": "u123", "role": "admin"},
        ...     secret="my-secret-key-at-least-32-bytes!!",
        ...     expires_in_seconds=3600,
        ... )
        >>> token.count(".")
        2
    """
    if len(secret) < 32:
        raise JWTSignError(f"secret too short ({len(secret)} bytes), need ≥32")

    claims: dict[str, Any] = dict(payload)
    now = datetime.now(UTC)
    claims["iat"] = int(now.timestamp())
    if expires_in_seconds is not None:
        claims["exp"] = int((now + timedelta(seconds=expires_in_seconds)).timestamp())

    try:
        return cast(str, pyjwt.encode(claims, secret, algorithm="HS256"))
    except Exception as e:
        raise JWTSignError(f"jwt sign failed: {e}") from e


def jwt_verify_hs256(
    *,
    token: str,
    secret: str,
    check_exp: bool = True,
) -> dict[str, Any]:
    """HS256 JWT verification and decoding.

    Args:
        token: JWT string produced by :func:`jwt_sign_hs256`.
        secret: Same secret used during signing.
        check_exp: Whether to enforce ``exp`` claim (default ``True``).
            Set ``False`` only for debugging.

    Returns:
        Decoded payload dict.

    Raises:
        JWTVerifyError: Bad format, wrong secret, expired, or wrong algorithm.

    Example:
        >>> token = jwt_sign_hs256(payload={"uid": 1}, secret="x" * 32, expires_in_seconds=3600)
        >>> payload = jwt_verify_hs256(token=token, secret="x" * 32)
        >>> payload["uid"]
        1
    """
    try:
        options = {"verify_exp": check_exp}
        result: dict[str, Any] = pyjwt.decode(token, secret, algorithms=["HS256"], options=options)
        return result
    except pyjwt.ExpiredSignatureError as e:
        raise JWTVerifyError(f"jwt expired: {e}") from e
    except pyjwt.InvalidTokenError as e:
        raise JWTVerifyError(f"jwt invalid: {e}") from e
    except Exception as e:
        raise JWTVerifyError(f"jwt verify failed: {e}") from e
