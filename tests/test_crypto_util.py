"""Tests for obase.crypto.CryptoUtil — a facade over the existing
obase.auth.jwt / obase.auth.password / obase.sha256_hash implementations."""

from __future__ import annotations

import hashlib

import pytest

from obase.crypto import CryptoUtil
from obase.exceptions import ObaseAuthError


class TestJwtSignDecode:
    def test_roundtrip(self):
        token = CryptoUtil.jwt_sign(payload={"sub": "user1"}, secret="s3cr3t")
        decoded = CryptoUtil.jwt_decode(token=token, secret="s3cr3t")
        assert decoded["sub"] == "user1"

    def test_wrong_secret_rejected(self):
        token = CryptoUtil.jwt_sign(payload={"sub": "user1"}, secret="s3cr3t")
        with pytest.raises(ObaseAuthError):
            CryptoUtil.jwt_decode(token=token, secret="wrong")

    def test_expired_token_rejected(self):
        token = CryptoUtil.jwt_sign(
            payload={"sub": "user1"}, secret="s3cr3t", expires_in_minutes=-1
        )
        with pytest.raises(ObaseAuthError, match="expired"):
            CryptoUtil.jwt_decode(token=token, secret="s3cr3t")


class TestHashVerifyPassword:
    def test_roundtrip(self):
        hashed = CryptoUtil.hash_password(password="hunter2")
        assert CryptoUtil.verify_password(password="hunter2", hashed=hashed) is True

    def test_wrong_password_rejected(self):
        hashed = CryptoUtil.hash_password(password="hunter2")
        assert CryptoUtil.verify_password(password="wrong", hashed=hashed) is False

    def test_hash_is_not_plaintext(self):
        hashed = CryptoUtil.hash_password(password="hunter2")
        assert hashed != "hunter2"


class TestSha256Hash:
    def test_matches_stdlib_hashlib(self):
        assert CryptoUtil.sha256_hash(b"hello") == hashlib.sha256(b"hello").digest()

    def test_returns_32_bytes(self):
        assert len(CryptoUtil.sha256_hash(b"anything")) == 32

    def test_different_input_different_digest(self):
        assert CryptoUtil.sha256_hash(b"a") != CryptoUtil.sha256_hash(b"b")
