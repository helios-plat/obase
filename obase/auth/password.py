import bcrypt


def bcrypt_hash(*, password: str, rounds: int = 12) -> str:
    """Hash a password using bcrypt.

    Args:
        password: The password to hash.
        rounds: The number of rounds to use for salting.

    Returns:
        The hashed password as a string.
    """
    salt = bcrypt.gensalt(rounds=rounds)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def bcrypt_verify(*, password: str, hashed: str) -> bool:
    """Verify a password against a hash.

    Args:
        password: The password to verify.
        hashed: The hashed password to check against.

    Returns:
        True if the password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
