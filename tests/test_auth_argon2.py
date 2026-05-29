from unittest.mock import MagicMock, patch

import pytest

from obase.auth._argon2 import ArgonHashError, argon2_hash, argon2_verify


def test_argon2_hash_returns_argon2id_format() -> None:
    h = argon2_hash(password="my_secret")
    assert h.startswith("$argon2id$")


def test_argon2_hash_same_password_different_hashes() -> None:
    h1 = argon2_hash(password="same")
    h2 = argon2_hash(password="same")
    assert h1 != h2


def test_argon2_hash_empty_password_allowed() -> None:
    h = argon2_hash(password="")
    assert h.startswith("$argon2id$")


def test_argon2_hash_long_password() -> None:
    h = argon2_hash(password="x" * 1000)
    assert h.startswith("$argon2id$")


def test_argon2_hash_unicode_password() -> None:
    h = argon2_hash(password="中文密码🔑")
    assert h.startswith("$argon2id$")
    assert argon2_verify(password="中文密码🔑", hash=h) is True


def test_argon2_hash_format_contains_parameters() -> None:
    h = argon2_hash(password="test")
    assert "v=19" in h
    assert "m=" in h
    assert "t=" in h
    assert "p=" in h


def test_argon2_verify_correct_password_returns_true() -> None:
    h = argon2_hash(password="correct")
    assert argon2_verify(password="correct", hash=h) is True


def test_argon2_verify_wrong_password_returns_false() -> None:
    h = argon2_hash(password="correct")
    assert argon2_verify(password="wrong", hash=h) is False


def test_argon2_verify_empty_vs_nonempty_hash() -> None:
    h = argon2_hash(password="notempty")
    assert argon2_verify(password="", hash=h) is False


def test_argon2_verify_invalid_hash_raises() -> None:
    with pytest.raises(ArgonHashError):
        argon2_verify(password="any", hash="not_a_hash")


def test_argon2_verify_bcrypt_hash_raises() -> None:
    with pytest.raises(ArgonHashError):
        argon2_verify(password="any", hash="$2b$12$abc")


def test_argon2_verify_deterministic() -> None:
    h = argon2_hash(password="test")
    assert argon2_verify(password="test", hash=h) is True
    assert argon2_verify(password="test", hash=h) is True


def test_argon2_hash_library_error_raises_argon_hash_error() -> None:
    mock_hasher = MagicMock()
    mock_hasher.hash.side_effect = RuntimeError("internal")
    with patch("obase.auth._argon2._hasher", mock_hasher):
        with pytest.raises(ArgonHashError, match="argon2 hash failed"):
            argon2_hash(password="test")
