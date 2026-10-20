"""Strictly read-only authenticated OKX v5 account adapter.

Authentication follows OKX's official REST Authentication documentation:
https://www.okx.com/docs-v5/en/#overview-rest-authentication-signature

Gloomberb (https://github.com/gloom-sh/gloomberb, MIT) was reviewed as the
requested reference; no Gloomberb source code is copied. This adapter exposes
only GET /account/balance and GET /account/positions. It contains no order,
transfer, or account-mutation method.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

_BASE_URL = "https://www.okx.com/api/v5"
_READ_ONLY_PATHS = frozenset({"/account/balance", "/account/positions"})


def generate_okx_signature(
    timestamp: str,
    method: str,
    request_path: str,
    body: str,
    secret: str,
) -> str:
    """Generate the OKX v5 Base64 HMAC-SHA256 request signature."""
    prehash = f"{timestamp}{method.upper()}{request_path}{body}"
    digest = hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class OKXReadonlyBrokerAdapter:
    """Read account balance and positions using signed OKX v5 GET requests only."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None,
        *,
        timeout: float = 5.0,
        base_url: str = _BASE_URL,
        client: httpx.AsyncClient | None = None,
        timestamp_provider: Callable[[], str] = _utc_timestamp,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._timestamp_provider = timestamp_provider

    def _credentials_ready(self) -> bool:
        return bool(self.api_key and self.api_secret and self.passphrase)

    async def _readonly_get(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        if path not in _READ_ONLY_PATHS:
            raise ValueError("only the allow-listed read-only account endpoints are supported")
        if not self._credentials_ready():
            return {"status": "degraded", "reason": "missing_credentials", "data": []}

        query = httpx.QueryParams(params or {})
        endpoint_path = path
        if query:
            endpoint_path = f"{path}?{query}"
        base_path = httpx.URL(self.base_url).path.rstrip("/")
        request_path = f"{base_path}{endpoint_path}"
        request_url = f"{self.base_url}{endpoint_path}"
        timestamp = self._timestamp_provider()
        headers = {
            "OK-ACCESS-KEY": self.api_key or "",
            "OK-ACCESS-SIGN": generate_okx_signature(
                timestamp, "GET", request_path, "", self.api_secret or ""
            ),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase or "",
            "Content-Type": "application/json",
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self.timeout, trust_env=True) as client:
                    response = await client.get(request_url, headers=headers)
            else:
                response = await self._client.get(
                    request_url, headers=headers, timeout=self.timeout
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Do not echo response bodies, request headers, or credentials to callers.
            return {
                "status": "degraded",
                "reason": f"request_failed:{type(exc).__name__}",
                "data": [],
            }
        if not isinstance(payload, dict):
            return {"status": "degraded", "reason": "invalid_response_schema", "data": []}
        if str(payload.get("code", "")) != "0":
            return {
                "status": "degraded",
                "reason": f"okx_error:{payload.get('code', 'unknown')}",
                "data": [],
            }
        rows = payload.get("data")
        if not isinstance(rows, list):
            return {"status": "degraded", "reason": "invalid_response_schema", "data": []}
        return {"status": "success", "data": rows}

    async def get_balance(self, currency: str | None = None) -> dict[str, Any]:
        """Fetch OKX account balances; missing credentials degrade without a request."""
        params = {"ccy": currency} if currency else None
        result = await self._readonly_get("/account/balance", params)
        if result["status"] == "success":
            return {"status": "success", "balance": result["data"]}
        return {
            "status": "degraded",
            "reason": result["reason"],
            "balance": [],
        }

    async def get_positions(
        self,
        *,
        instrument_type: str | None = None,
        instrument_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch OKX positions; method supports only the account/positions GET endpoint."""
        params = {}
        if instrument_type:
            params["instType"] = instrument_type
        if instrument_id:
            params["instId"] = instrument_id
        result = await self._readonly_get("/account/positions", params or None)
        if result["status"] == "success":
            return {"status": "success", "positions": result["data"]}
        return {
            "status": "degraded",
            "reason": result["reason"],
            "positions": [],
        }
