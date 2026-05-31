"""Tests for obase.oauth2_provider — OAuth2 Authorization Code Flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from obase.oauth2_provider import (
    OAuth2HTTPError,
    OAuth2ProviderConfig,
    OAuth2Token,
    OAuth2TokenExchangeError,
    OAuth2UserInfoError,
    build_authorize_url,
    exchange_code_for_token,
    fetch_userinfo_raw,
)


@pytest.fixture()
def config() -> OAuth2ProviderConfig:
    return OAuth2ProviderConfig(
        name="test-provider",
        client_id="client123",
        client_secret="secret456",
        authorize_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        userinfo_url="https://auth.example.com/userinfo",
        scope="openid email profile",
        redirect_uri="https://app.example.com/callback",
    )


@pytest.fixture()
def config_no_userinfo() -> OAuth2ProviderConfig:
    return OAuth2ProviderConfig(
        name="no-userinfo",
        client_id="client123",
        client_secret="secret456",
        authorize_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        userinfo_url=None,
        redirect_uri="https://app.example.com/callback",
    )


# ---------------------------------------------------------------------------
# build_authorize_url
# ---------------------------------------------------------------------------


def test_build_authorize_url_contains_required_params(config: OAuth2ProviderConfig) -> None:
    url = build_authorize_url(config, state="abc123")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == ["client123"]
    assert qs["redirect_uri"] == ["https://app.example.com/callback"]
    assert qs["scope"] == ["openid email profile"]
    assert qs["state"] == ["abc123"]


def test_build_authorize_url_state_is_url_encoded(config: OAuth2ProviderConfig) -> None:
    state = "hello world&foo=bar"
    url = build_authorize_url(config, state=state)
    # Raw URL string must not contain unencoded space or bare & in state value
    assert "hello+world" in url or "hello%20world" in url
    # Round-trip via parse_qs should recover original state
    qs = parse_qs(urlparse(url).query)
    assert qs["state"] == [state]


# ---------------------------------------------------------------------------
# exchange_code_for_token
# ---------------------------------------------------------------------------


async def test_exchange_code_for_token_success(config: OAuth2ProviderConfig) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "tok_abc",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "ref_xyz",
        "scope": "openid email",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("obase.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        token = await exchange_code_for_token(config=config, code="authcode123")

    assert isinstance(token, OAuth2Token)
    assert token.access_token == "tok_abc"
    assert token.expires_in == 3600
    assert token.refresh_token == "ref_xyz"


async def test_exchange_code_for_token_oauth2_error_raises(config: OAuth2ProviderConfig) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Authorization code expired",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("obase.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(OAuth2TokenExchangeError, match="Authorization code expired"):
            await exchange_code_for_token(config=config, code="bad_code")


async def test_exchange_code_for_token_http_error_raises(config: OAuth2ProviderConfig) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.json.return_value = {}  # no "error" key

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("obase.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(OAuth2HTTPError, match="500"):
            await exchange_code_for_token(config=config, code="any_code")


# ---------------------------------------------------------------------------
# fetch_userinfo_raw
# ---------------------------------------------------------------------------


async def test_fetch_userinfo_raw_success(config: OAuth2ProviderConfig) -> None:
    token = OAuth2Token(access_token="tok_abc")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"sub": "123", "email": "a@b.com"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("obase.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_userinfo_raw(config=config, token=token)

    assert result == {"sub": "123", "email": "a@b.com"}


async def test_fetch_userinfo_raw_no_url_raises(
    config_no_userinfo: OAuth2ProviderConfig,
) -> None:
    token = OAuth2Token(access_token="tok_abc")
    with pytest.raises(OAuth2UserInfoError, match="userinfo_url not configured"):
        await fetch_userinfo_raw(config=config_no_userinfo, token=token)


async def test_fetch_userinfo_raw_http_error_raises(config: OAuth2ProviderConfig) -> None:
    token = OAuth2Token(access_token="tok_abc")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("obase.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises((OAuth2HTTPError, OAuth2UserInfoError)):
            await fetch_userinfo_raw(config=config, token=token)


# ---------------------------------------------------------------------------
# OAuth2Token model
# ---------------------------------------------------------------------------


def test_oauth2_token_preserves_refresh_and_id_token() -> None:
    token = OAuth2Token(
        access_token="acc",
        refresh_token="ref",
        expires_in=7200,
        token_type="Bearer",
        scope="openid email",
        id_token="id_tok_xyz",
    )
    assert token.refresh_token == "ref"
    assert token.id_token == "id_tok_xyz"
    assert token.expires_in == 7200
    assert token.scope == "openid email"
