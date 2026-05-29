from unittest.mock import patch

import jwt as pyjwt
import pytest

from obase.auth._jwt import JWTSignError, JWTVerifyError, jwt_sign_hs256, jwt_verify_hs256

SECRET = "x" * 32


def test_jwt_sign_returns_three_part_token() -> None:
    token = jwt_sign_hs256(payload={"uid": 1}, secret=SECRET)
    assert token.count(".") == 2


def test_jwt_sign_adds_iat_and_exp() -> None:
    token = jwt_sign_hs256(payload={"uid": 1}, secret=SECRET, expires_in_seconds=3600)
    payload = jwt_verify_hs256(token=token, secret=SECRET)
    assert "iat" in payload
    assert "exp" in payload


def test_jwt_sign_no_exp_when_none() -> None:
    token = jwt_sign_hs256(payload={"uid": 1}, secret=SECRET, expires_in_seconds=None)
    payload = jwt_verify_hs256(token=token, secret=SECRET)
    assert "exp" not in payload
    assert "iat" in payload


def test_jwt_sign_short_secret_raises() -> None:
    with pytest.raises(JWTSignError, match="secret too short"):
        jwt_sign_hs256(payload={"uid": 1}, secret="short")


def test_jwt_sign_unserializable_payload_raises() -> None:
    with pytest.raises(JWTSignError):
        jwt_sign_hs256(payload={"key": object()}, secret=SECRET)


def test_jwt_sign_nested_payload_roundtrip() -> None:
    token = jwt_sign_hs256(payload={"user": {"id": 1, "role": "admin"}}, secret=SECRET)
    payload = jwt_verify_hs256(token=token, secret=SECRET)
    assert payload["user"]["id"] == 1
    assert payload["user"]["role"] == "admin"


def test_jwt_verify_roundtrip_returns_payload() -> None:
    token = jwt_sign_hs256(payload={"uid": 42}, secret=SECRET)
    payload = jwt_verify_hs256(token=token, secret=SECRET)
    assert payload["uid"] == 42


def test_jwt_verify_wrong_secret_raises() -> None:
    token = jwt_sign_hs256(payload={"uid": 1}, secret=SECRET)
    with pytest.raises(JWTVerifyError):
        jwt_verify_hs256(token=token, secret="y" * 32)


def test_jwt_verify_malformed_token_raises() -> None:
    with pytest.raises(JWTVerifyError):
        jwt_verify_hs256(token="not.a.jwt", secret=SECRET)


def test_jwt_verify_expired_token_raises() -> None:
    token = jwt_sign_hs256(payload={"uid": 1}, secret=SECRET, expires_in_seconds=-1)
    with pytest.raises(JWTVerifyError):
        jwt_verify_hs256(token=token, secret=SECRET)


def test_jwt_verify_check_exp_false_accepts_expired() -> None:
    token = jwt_sign_hs256(payload={"uid": 1}, secret=SECRET, expires_in_seconds=-1)
    payload = jwt_verify_hs256(token=token, secret=SECRET, check_exp=False)
    assert payload["uid"] == 1


def test_jwt_verify_nested_payload_preserved() -> None:
    token = jwt_sign_hs256(payload={"data": {"x": [1, 2, 3]}}, secret=SECRET)
    payload = jwt_verify_hs256(token=token, secret=SECRET)
    assert payload["data"]["x"] == [1, 2, 3]


def test_jwt_verify_different_algorithm_rejected() -> None:
    token = pyjwt.encode({"uid": 1}, SECRET, algorithm="HS512")
    with pytest.raises(JWTVerifyError):
        jwt_verify_hs256(token=token, secret=SECRET)


def test_jwt_verify_unexpected_exception_raises_jwt_verify_error() -> None:
    token = jwt_sign_hs256(payload={"uid": 1}, secret=SECRET)
    with patch("obase.auth._jwt.pyjwt.decode", side_effect=RuntimeError("unexpected")):
        with pytest.raises(JWTVerifyError, match="jwt verify failed"):
            jwt_verify_hs256(token=token, secret=SECRET)
