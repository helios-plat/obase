"""obase.sha256_hash — Raw SHA-256 digest helper."""
from __future__ import annotations

import hashlib


def sha256_hash(data: bytes) -> bytes:
    """Return the 32-byte SHA-256 digest of *data*.

    Args:
        data: Arbitrary bytes to hash.

    Returns:
        32-byte digest (not hex-encoded).
    """
    return hashlib.sha256(data).digest()
