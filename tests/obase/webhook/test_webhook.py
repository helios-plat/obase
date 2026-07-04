"""Tests for obase.webhook.sign_payload."""

from __future__ import annotations

import datetime

import pytest

from obase.webhook import WebhookSignError, sign_payload

_SECRET_32 = "a" * 32


class TestSignPayload:
    def test_dict_payload_sha256_returns_64_char_hex(self):
        result = sign_payload(payload={"event": "push"}, secret=_SECRET_32)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_bytes_payload_sha256_returns_64_char_hex(self):
        result = sign_payload(payload=b"raw body", secret=_SECRET_32)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_sha512_returns_128_char_hex(self):
        result = sign_payload(payload={"event": "push"}, secret=_SECRET_32, algo="sha512")
        assert len(result) == 128
        assert all(c in "0123456789abcdef" for c in result)

    def test_secret_too_short_raises(self):
        with pytest.raises(WebhookSignError, match="secret too short"):
            sign_payload(payload={"x": 1}, secret="short")

    def test_non_serializable_uses_default_str_no_raise(self):
        dt = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        result = sign_payload(payload={"ts": dt}, secret=_SECRET_32)
        assert len(result) == 64

    def test_same_inputs_deterministic(self):
        r1 = sign_payload(payload={"a": 1}, secret=_SECRET_32)
        r2 = sign_payload(payload={"a": 1}, secret=_SECRET_32)
        assert r1 == r2

    def test_different_secret_different_signature(self):
        secret2 = "b" * 32
        r1 = sign_payload(payload={"a": 1}, secret=_SECRET_32)
        r2 = sign_payload(payload={"a": 1}, secret=secret2)
        assert r1 != r2

    def test_key_order_irrelevant_same_signature(self):
        r1 = sign_payload(payload={"a": 1, "b": 2}, secret=_SECRET_32)
        r2 = sign_payload(payload={"b": 2, "a": 1}, secret=_SECRET_32)
        assert r1 == r2

    def test_unsupported_algo_raises(self):
        with pytest.raises(WebhookSignError, match="unsupported algo"):
            sign_payload(payload={"x": 1}, secret=_SECRET_32, algo="sha1")  # type: ignore[arg-type]

    def test_wrong_type_payload_raises(self) -> None:
        with pytest.raises(WebhookSignError, match="payload must be dict or bytes"):
            sign_payload(payload="a string", secret=_SECRET_32)  # type: ignore[arg-type]
