from __future__ import annotations

import os

import argon2.low_level as _argon2

from obase.crypto.token_encryptor import CryptoError


def derive_master_key(
    *,
    password: str,
    salt: bytes | None = None,
    memory_cost: int = 65536,  # 64 MB
    time_cost: int = 2,
    parallelism: int = 1,
) -> tuple[bytes, bytes]:
    """Derive a 256-bit master key from a password using Argon2id.

    Args:
        password: User password (unicode string)
        salt: 16-byte salt. If None, generates a random salt.
        memory_cost: Memory in KiB (default 64 MB)
        time_cost: Iterations (default 2)
        parallelism: Parallel threads (default 1)

    Returns:
        Tuple of (master_key: bytes[32], salt: bytes[16])

    Raises:
        CryptoError: Derivation failure

    Example:
        >>> key, salt = derive_master_key(password="my_password")
        >>> len(key) == 32 and len(salt) == 16
        True
    """
    if salt is None:
        salt = os.urandom(16)
    if len(salt) != 16:
        raise CryptoError(f"salt must be 16 bytes, got {len(salt)}")
    try:
        key = _argon2.hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            type=_argon2.Type.ID,
        )
        return key, salt
    except Exception as e:
        raise CryptoError(f"derive_master_key failed: {e}") from e
