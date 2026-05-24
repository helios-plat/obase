import datetime
from typing import Any, cast

import jwt

from obase.exceptions import ObaseAuthError


def jwt_create(
    *, payload: dict[str, Any], secret: str, expires_in_minutes: int = 720, algorithm: str = "HS256"
) -> str:
    """Create a JWT token.

    Args:
        payload: The payload to include in the token.
        secret: The secret key to sign the token.
        expires_in_minutes: Expiration time in minutes.
        algorithm: The algorithm to use.

    Returns:
        The encoded JWT token.
    """
    to_encode = payload.copy()
    expire = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=expires_in_minutes)
    to_encode.update({"exp": expire})
    try:
        return cast(str, jwt.encode(to_encode, secret, algorithm=algorithm))
    except Exception as e:
        raise ObaseAuthError(f"Failed to create JWT: {e}") from e


def jwt_verify(*, token: str, secret: str, algorithm: str = "HS256") -> dict[str, Any]:
    """Verify a JWT token.

    Args:
        token: The token to verify.
        secret: The secret key to verify the token.
        algorithm: The algorithm to use.

    Returns:
        The decoded payload.

    Raises:
        ObaseAuthError: If the token is invalid or expired.
    """
    try:
        return jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.ExpiredSignatureError:
        raise ObaseAuthError("Token has expired") from None
    except jwt.InvalidTokenError as e:
        raise ObaseAuthError(f"Invalid token: {e}") from e
    except Exception as e:
        raise ObaseAuthError(f"JWT verification failed: {e}") from e
