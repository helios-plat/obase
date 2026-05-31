"""oauth2_provider — OAuth2 Authorization Code Flow protocol layer."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from pydantic import BaseModel, HttpUrl


class OAuth2ProviderConfig(BaseModel):
    name: str
    client_id: str
    client_secret: str
    authorize_url: HttpUrl
    token_url: HttpUrl
    userinfo_url: HttpUrl | None = None
    scope: str = "openid email profile"
    redirect_uri: HttpUrl


class OAuth2Token(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str = "Bearer"
    scope: str | None = None
    id_token: str | None = None


class OAuth2Error(Exception): ...


class OAuth2TokenExchangeError(OAuth2Error): ...


class OAuth2UserInfoError(OAuth2Error): ...


class OAuth2HTTPError(OAuth2Error): ...


def build_authorize_url(config: OAuth2ProviderConfig, state: str) -> str:
    """OAuth2 Authorization Code Flow Step 1: build the authorization URL.

    Constructs URL from config.authorize_url with query params:
    response_type=code, client_id, redirect_uri, scope, state.

    state is included verbatim (URL-encoded by urllib).
    """
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": str(config.redirect_uri),
        "scope": config.scope,
        "state": state,
    }
    base = str(config.authorize_url)
    parsed = urlparse(base)
    query = urlencode(params)
    return urlunparse(parsed._replace(query=query))


async def exchange_code_for_token(
    *,
    config: OAuth2ProviderConfig,
    code: str,
) -> OAuth2Token:
    """Step 2: POST to token_url with code, client_id, client_secret, redirect_uri.

    Raises:
        OAuth2TokenExchangeError: token endpoint returns OAuth2 error (error field in JSON)
        OAuth2HTTPError: HTTP 4xx/5xx response without OAuth2 error body
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "redirect_uri": str(config.redirect_uri),
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            str(config.token_url),
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body: dict[str, Any] = response.json()

    if "error" in body:
        description = body.get("error_description") or body["error"]
        raise OAuth2TokenExchangeError(f"OAuth2 token exchange failed: {description}")

    if response.status_code >= 400:
        raise OAuth2HTTPError(f"Token endpoint returned HTTP {response.status_code}")

    return OAuth2Token(**body)


async def fetch_userinfo_raw(
    *,
    config: OAuth2ProviderConfig,
    token: OAuth2Token,
) -> dict[str, Any]:
    """Step 3: GET userinfo_url with Bearer token. Returns raw dict.

    Does NOT normalize fields — that is the caller's responsibility.

    Raises:
        OAuth2UserInfoError: userinfo_url is None, or endpoint returns error
        OAuth2HTTPError: HTTP failure
    """
    if config.userinfo_url is None:
        raise OAuth2UserInfoError("userinfo_url not configured")

    async with httpx.AsyncClient() as client:
        response = await client.get(
            str(config.userinfo_url),
            headers={"Authorization": f"Bearer {token.access_token}"},
        )

    if response.status_code >= 400:
        raise OAuth2HTTPError(f"Userinfo endpoint returned HTTP {response.status_code}")

    result: dict[str, Any] = response.json()
    return result


__all__ = [
    "OAuth2ProviderConfig",
    "OAuth2Token",
    "OAuth2Error",
    "OAuth2TokenExchangeError",
    "OAuth2UserInfoError",
    "OAuth2HTTPError",
    "build_authorize_url",
    "exchange_code_for_token",
    "fetch_userinfo_raw",
]
