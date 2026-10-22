"""OKX v5 read-only signing and account endpoint tests."""

from __future__ import annotations

import httpx
import pytest

from obase.brokers.okx_readonly import OKXReadonlyBrokerAdapter, generate_okx_signature

OFFICIAL_TIMESTAMP = "2020-12-08T09:08:57.715Z"
OFFICIAL_SECRET = "22582BD0CFF14C41EDBF1AB98506286D"
OFFICIAL_BALANCE_PATH = "/api/v5/account/balance?ccy=BTC"
OFFICIAL_SIGNATURE = "HiZhvSfMtWJA3uUIVXV3a/bSXNPCWvYFXoGCVS8V4zY="


def test_signature_matches_official_okx_documentation_vector() -> None:
    """Inputs follow OKX REST Authentication docs, Signing Messages subsection.

    https://www.okx.com/docs-v5/en/#overview-rest-authentication-signature
    The timestamp, GET request path and example SecretKey are copied from that
    official page; the expected Base64 value is the direct HMAC-SHA256 result.
    """
    assert generate_okx_signature(
        OFFICIAL_TIMESTAMP,
        "GET",
        OFFICIAL_BALANCE_PATH,
        "",
        OFFICIAL_SECRET,
    ) == OFFICIAL_SIGNATURE


def test_signing_uses_uppercase_method_and_exact_body() -> None:
    path = "/api/v5/account/balance"
    get_signature = generate_okx_signature(
        OFFICIAL_TIMESTAMP, "get", path, "", OFFICIAL_SECRET
    )
    upper_signature = generate_okx_signature(
        OFFICIAL_TIMESTAMP, "GET", path, "", OFFICIAL_SECRET
    )
    assert get_signature == upper_signature
    assert generate_okx_signature(
        OFFICIAL_TIMESTAMP, "POST", "/api/v5/account/balance", "{}", OFFICIAL_SECRET
    ) != get_signature


@pytest.mark.asyncio
async def test_missing_credentials_degrade_without_http_requests() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": "0", "data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OKXReadonlyBrokerAdapter(client=client)
        balance = await adapter.get_balance("BTC")
        positions = await adapter.get_positions(instrument_type="SWAP")

    assert balance == {"status": "degraded", "reason": "missing_credentials", "balance": []}
    assert positions == {"status": "degraded", "reason": "missing_credentials", "positions": []}
    assert requests == []


@pytest.mark.asyncio
async def test_balance_get_is_signed_with_exact_path_and_headers() -> None:
    timestamp = OFFICIAL_TIMESTAMP
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"code": "0", "data": [{"details": [{"ccy": "BTC"}]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OKXReadonlyBrokerAdapter(
            api_key="key-id",
            api_secret=OFFICIAL_SECRET,
            passphrase="passphrase",
            client=client,
            timestamp_provider=lambda: timestamp,
        )
        result = await adapter.get_balance("BTC")

    request = captured[0]
    expected_path = "/api/v5/account/balance?ccy=BTC"
    assert request.method == "GET"
    assert request.url.path + "?" + request.url.query.decode() == expected_path
    assert request.headers["OK-ACCESS-TIMESTAMP"] == timestamp
    assert request.headers["OK-ACCESS-SIGN"] == generate_okx_signature(
        timestamp, "GET", expected_path, "", OFFICIAL_SECRET
    )
    assert result["status"] == "success"
    assert result["balance"][0]["details"][0]["ccy"] == "BTC"


@pytest.mark.asyncio
async def test_positions_are_signed_and_query_is_part_of_request_path() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"code": "0", "data": [{"instId": "BTC-USDT-SWAP"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OKXReadonlyBrokerAdapter(
            api_key="key-id",
            api_secret=OFFICIAL_SECRET,
            passphrase="passphrase",
            client=client,
            timestamp_provider=lambda: OFFICIAL_TIMESTAMP,
        )
        result = await adapter.get_positions(
            instrument_type="SWAP", instrument_id="BTC-USDT-SWAP"
        )

    request = captured[0]
    signed_path = request.url.path + "?" + request.url.query.decode()
    assert signed_path == "/api/v5/account/positions?instType=SWAP&instId=BTC-USDT-SWAP"
    assert request.headers["OK-ACCESS-SIGN"] == generate_okx_signature(
        OFFICIAL_TIMESTAMP, "GET", signed_path, "", OFFICIAL_SECRET
    )
    assert result["positions"] == [{"instId": "BTC-USDT-SWAP"}]


@pytest.mark.asyncio
async def test_api_error_and_transport_failure_degrade_without_leaking_secrets() -> None:
    async def api_error(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "51000", "msg": "invalid request"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(api_error)) as client:
        adapter = OKXReadonlyBrokerAdapter(
            "sample-key", "sample-secret", "sample-pass", client=client
        )
        result = await adapter.get_balance()
    assert result["status"] == "degraded"
    assert result["reason"] == "okx_error:51000"
    assert "sample-secret" not in result["reason"]

    async def network_error(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    async with httpx.AsyncClient(transport=httpx.MockTransport(network_error)) as client:
        adapter = OKXReadonlyBrokerAdapter(
            "sample-key", "sample-secret", "sample-pass", client=client
        )
        result = await adapter.get_positions()
    assert result["status"] == "degraded"
    assert result["reason"] == "request_failed:ConnectError"
    assert "sample-secret" not in result["reason"]


def test_adapter_exposes_no_order_or_transfer_surface() -> None:
    adapter = OKXReadonlyBrokerAdapter()
    assert not hasattr(adapter, "place_order")
    assert not hasattr(adapter, "create_order")
    assert not hasattr(adapter, "transfer")
