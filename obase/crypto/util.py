"""obase.crypto.util — CryptoUtil facade.

Composes the already-existing obase.auth.jwt / obase.auth.password /
obase.sha256_hash implementations under one class, matching the interface
SPEC's `obase.crypto.CryptoUtil` calls for (jwt_sign/jwt_decode/hash_password/
verify_password/sha256_hash). Deliberately thin — no new crypto logic, purely
a naming-consistent facade over what already exists elsewhere in obase.
"""

from __future__ import annotations

from typing import Any

from obase.auth.jwt import jwt_create, jwt_verify
from obase.auth.password import bcrypt_hash, bcrypt_verify
from obase.sha256_hash import sha256_hash as _sha256_hash


class CryptoUtil:
    """Stateless crypto helper facade. All methods are static."""

    @staticmethod
    def jwt_sign(
        *,
        payload: dict[str, Any],
        secret: str,
        expires_in_minutes: int = 720,
        algorithm: str = "HS256",
    ) -> str:
        """Sign a JWT. Delegates to obase.auth.jwt.jwt_create."""
        return jwt_create(
            payload=payload,
            secret=secret,
            expires_in_minutes=expires_in_minutes,
            algorithm=algorithm,
        )

    @staticmethod
    def jwt_decode(*, token: str, secret: str, algorithm: str = "HS256") -> dict[str, Any]:
        """Decode + verify a JWT. Delegates to obase.auth.jwt.jwt_verify.

        Raises:
            ObaseAuthError: Token expired, invalid, or signature mismatch.
        """
        return jwt_verify(token=token, secret=secret, algorithm=algorithm)

    @staticmethod
    def hash_password(*, password: str, rounds: int = 12) -> str:
        """Hash a password. Delegates to obase.auth.password.bcrypt_hash."""
        return bcrypt_hash(password=password, rounds=rounds)

    @staticmethod
    def verify_password(*, password: str, hashed: str) -> bool:
        """Verify a password against a hash. Delegates to bcrypt_verify."""
        return bcrypt_verify(password=password, hashed=hashed)

    @staticmethod
    def sha256_hash(data: bytes) -> bytes:
        """Raw SHA-256 digest. Delegates to obase.sha256_hash.sha256_hash."""
        return _sha256_hash(data)
