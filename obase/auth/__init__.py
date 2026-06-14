from __future__ import annotations

from typing import Any

from obase.auth._argon2 import ArgonHashError, argon2_hash, argon2_verify
from obase.auth._jwt import JWTSignError, JWTVerifyError, jwt_sign_hs256, jwt_verify_hs256
from obase.auth.jwt import jwt_create, jwt_verify
from obase.auth.password import bcrypt_hash, bcrypt_verify
from obase.auth.totp import totp_qr_url, totp_secret_generate, totp_verify


def create_access_token(payload: dict[str, Any], *, expires_in: int | None = None) -> str:
    """Create a signed JWT access token using settings.JWT_SECRET."""
    from obase.config import settings
    exp = expires_in if expires_in is not None else settings.JWT_EXPIRE_SECONDS
    return jwt_sign_hs256(payload=payload, secret=settings.JWT_SECRET, expires_in_seconds=exp)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Verify and decode a JWT access token. Returns payload or None on failure."""
    from obase.config import settings
    try:
        return jwt_verify_hs256(token=token, secret=settings.JWT_SECRET)
    except (JWTVerifyError, Exception):
        return None


__all__ = [
    "ArgonHashError",
    "argon2_hash",
    "argon2_verify",
    "JWTSignError",
    "JWTVerifyError",
    "jwt_sign_hs256",
    "jwt_verify_hs256",
    "jwt_create",
    "jwt_verify",
    "bcrypt_hash",
    "bcrypt_verify",
    "totp_qr_url",
    "totp_secret_generate",
    "totp_verify",
    "create_access_token",
    "decode_access_token",
]
