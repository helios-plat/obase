from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoError(Exception):
    """Encryption/decryption failure."""


def encrypt_token(*, plaintext: str, master_key: bytes) -> str:
    """Encrypt a string using AES-256-GCM.

    Args:
        plaintext: String to encrypt (e.g. OAuth access token)
        master_key: 32-byte AES key (derive with derive_master_key)

    Returns:
        base64url-encoded string: nonce(12) + ciphertext + tag

    Raises:
        CryptoError: Invalid key length or encryption failure
    """
    if len(master_key) != 32:
        raise CryptoError(f"master_key must be 32 bytes, got {len(master_key)}")
    try:
        aesgcm = AESGCM(master_key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    except CryptoError:
        raise
    except Exception as e:
        raise CryptoError(f"encrypt_token failed: {e}") from e


def decrypt_token(*, ciphertext: str, master_key: bytes) -> str:
    """Decrypt a string encrypted with encrypt_token.

    Args:
        ciphertext: base64url-encoded ciphertext from encrypt_token
        master_key: Same 32-byte AES key used for encryption

    Returns:
        Decrypted plaintext string

    Raises:
        CryptoError: Wrong key, tampered ciphertext, or decode failure
    """
    if len(master_key) != 32:
        raise CryptoError(f"master_key must be 32 bytes, got {len(master_key)}")
    try:
        raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        nonce, ct = raw[:12], raw[12:]
        aesgcm = AESGCM(master_key)
        plaintext_bytes = aesgcm.decrypt(nonce, ct, None)
        return plaintext_bytes.decode("utf-8")
    except CryptoError:
        raise
    except Exception as e:
        raise CryptoError(f"decrypt_token failed: {e}") from e
