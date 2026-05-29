from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


class ArgonHashError(Exception):
    """Argon2 operation failed."""


def argon2_hash(*, password: str) -> str:
    """Argon2id password hash (OWASP recommended).

    Uses module-level PasswordHasher singleton (defaults: time_cost=3,
    memory_cost=64MB, parallelism=4, hash_len=32, salt_len=16).

    Args:
        password: Plaintext password (UTF-8 string).

    Returns:
        Argon2 hash string in format
        ``$argon2id$v=19$m=...,t=...,p=...$<salt>$<hash>``.

    Raises:
        ArgonHashError: Hash operation failed (rare — underlying library error).

    Example:
        >>> h = argon2_hash(password="my_secret")
        >>> h.startswith("$argon2id$")
        True
        >>> argon2_verify(password="my_secret", hash=h)
        True
    """
    try:
        return _hasher.hash(password)
    except Exception as e:
        raise ArgonHashError(f"argon2 hash failed: {e}") from e


def argon2_verify(*, password: str, hash: str) -> bool:
    """Verify a password against an Argon2 hash.

    Args:
        password: Plaintext password.
        hash: Hash string produced by :func:`argon2_hash`.

    Returns:
        ``True`` if password matches, ``False`` if it does not.

    Raises:
        ArgonHashError: ``hash`` is not a valid Argon2 hash string.

    Note:
        Password mismatch returns ``False``; it does not raise.
        An invalid hash format raises to distinguish "wrong password"
        from "tampered hash field".

    Example:
        >>> h = argon2_hash(password="secret")
        >>> argon2_verify(password="secret", hash=h)
        True
        >>> argon2_verify(password="wrong", hash=h)
        False
    """
    try:
        _hasher.verify(hash, password)
        return True
    except VerifyMismatchError:
        return False
    except (InvalidHashError, Exception) as e:
        raise ArgonHashError(f"argon2 verify failed: invalid hash: {e}") from e
