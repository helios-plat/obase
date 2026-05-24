import time

import pytest

from obase.auth.jwt import jwt_create, jwt_verify
from obase.auth.password import bcrypt_hash, bcrypt_verify
from obase.auth.totp import totp_qr_url, totp_secret_generate, totp_verify
from obase.exceptions import ObaseAuthError


# JWT Tests
def test_jwt_roundtrip():
    secret = "super-secret"
    payload = {"user_id": 123, "role": "admin"}
    token = jwt_create(payload=payload, secret=secret)
    decoded = jwt_verify(token=token, secret=secret)
    assert decoded["user_id"] == 123
    assert decoded["role"] == "admin"
    assert "exp" in decoded


def test_jwt_expired():
    secret = "super-secret"
    token = jwt_create(payload={"sub": "test"}, secret=secret, expires_in_minutes=-1)
    with pytest.raises(ObaseAuthError, match="Token has expired"):
        jwt_verify(token=token, secret=secret)


def test_jwt_invalid_secret():
    secret = "super-secret"
    token = jwt_create(payload={"sub": "test"}, secret=secret)
    with pytest.raises(ObaseAuthError, match="Invalid token"):
        jwt_verify(token=token, secret="wrong-secret")


def test_jwt_create_error():
    # Unserializable payload
    with pytest.raises(ObaseAuthError, match="Failed to create JWT"):
        jwt_create(payload={"key": object()}, secret="secret")


def test_jwt_verify_error():
    with pytest.raises(ObaseAuthError, match="Invalid token"):
        jwt_verify(token="invalid-token", secret="secret")


# Bcrypt Tests
def test_bcrypt_roundtrip():
    password = "secure-password"
    hashed = bcrypt_hash(password=password)
    assert hashed != password
    assert bcrypt_verify(password=password, hashed=hashed) is True
    assert bcrypt_verify(password="wrong-password", hashed=hashed) is False


def test_bcrypt_invalid_hash():
    assert bcrypt_verify(password="password", hashed="not-a-hash") is False


# TOTP Tests
def test_totp_roundtrip():
    secret = totp_secret_generate()
    assert len(secret) == 32
    # This is a bit tricky to test without waiting, but we can use pyotp directly to get current code
    import pyotp

    totp = pyotp.TOTP(secret)
    code = totp.now()
    assert totp_verify(secret=secret, code=code) is True
    assert totp_verify(secret=secret, code="000000") is False


def test_totp_qr_url():
    secret = totp_secret_generate()
    url = totp_qr_url(secret=secret, account_name="user@example.com", issuer="Helios")
    assert url.startswith("data:image/png;base64,")


def test_totp_window():
    import pyotp

    secret = totp_secret_generate()
    totp = pyotp.TOTP(secret)
    # Get code for 30 seconds ago
    code = totp.at(time.time() - 30)
    assert totp_verify(secret=secret, code=code, valid_window=1) is True
