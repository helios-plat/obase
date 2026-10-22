"""Public Deribit and OKX option adapter contract tests."""

from __future__ import annotations

import httpx
import pytest

from obase.options_marketdata import OptionsMarketDataAdapter, OptionsMarketDataError


@pytest.mark.asyncio
async def test_deribit_public_chain_is_normalized() -> None:
    expiry_ms = 1792569600000
    payloads = {
        "/api/v2/public/get_instruments": {"result": [{
            "instrument_name": "BTC-21OCT26-80000-C",
            "expiration_timestamp": expiry_ms,
            "contract_size": 1.0,
        }]},
        "/api/v2/public/get_book_summary_by_currency": {"result": [{
            "instrument_name": "BTC-21OCT26-80000-C",
            "open_interest": 12.5,
            "mark_iv": 52.0,
            "underlying_price": 81000.0,
        }]},
        "/api/v2/public/get_time": {"result": 1792489200000},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OptionsMarketDataAdapter(client=client).fetch_options("deribit")

    assert result["exchange"] == "deribit"
    assert result["spot"] == 81000.0
    assert result["provider_timestamp"] == 1792489200000
    assert result["options"][0]["expiry"] == "261021"
    assert result["options"][0]["mark_iv"] == pytest.approx(0.52)
    assert result["options"][0]["open_interest"] == 12.5


@pytest.mark.asyncio
async def test_okx_public_chain_joins_instrument_oi_and_greeks() -> None:
    expiry_ms = 1792569600000
    payloads = {
        "/api/v5/public/instruments": {"code": "0", "data": [{
            "instId": "BTC-USD-261021-80000-P",
            "expTime": str(expiry_ms),
            "ctMult": "0.1",
        }]},
        "/api/v5/public/open-interest": {"code": "0", "data": [{
            "instId": "BTC-USD-261021-80000-P", "oi": "7", "oiUsd": "567000", "ts": "1792489200000",
        }]},
        "/api/v5/public/opt-summary": {"code": "0", "data": [{
            "instId": "BTC-USD_UM-261021-80000-P",
            "markVol": "0.48", "deltaBS": "-0.24", "gammaBS": "0.00002", "ts": "1792489200000",
        }]},
        "/api/v5/market/index-tickers": {"code": "0", "data": [{"idxPx": "81000"}]},
        "/api/v5/public/time": {"code": "0", "data": [{"ts": "1792489200000"}]},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OptionsMarketDataAdapter(client=client).fetch_options("okx")

    assert result["spot"] == 81000.0
    assert result["provider_timestamp"] == 1792489200000
    assert result["options"][0]["expiry"] == "261021"
    assert result["options"][0]["open_interest"] == 7.0
    assert result["options"][0]["mark_iv"] == pytest.approx(0.48)
    assert result["options"][0]["delta"] == pytest.approx(-0.24)
    assert result["options"][0]["contract_multiplier"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_retry_transient_status_and_cache_successful_json() -> None:
    requests = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(200, json={"result": 4242})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OptionsMarketDataAdapter(client=client, max_retries=1, cache_ttl=30)
        first = await adapter._get_json("deribit", "/public/get_time", {})
        second = await adapter._get_json("deribit", "/public/get_time", {})

    assert first == second == 4242
    assert requests == 2


@pytest.mark.asyncio
async def test_timeout_is_forwarded_to_httpx_request() -> None:
    observed_timeout = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_timeout
        observed_timeout = request.extensions["timeout"]
        return httpx.Response(200, json={"result": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await OptionsMarketDataAdapter(client=client, timeout=0.75)._get_json(
            "deribit", "/public/get_time", {}
        )

    assert observed_timeout["read"] == 0.75


@pytest.mark.asyncio
async def test_non_retryable_client_error_fails_without_extra_attempts() -> None:
    requests = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(404, json={"error": "not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OptionsMarketDataAdapter(client=client, max_retries=2)
        with pytest.raises(OptionsMarketDataError, match="failed after 1"):
            await adapter._get_json("deribit", "/public/get_time", {})

    assert requests == 1


@pytest.mark.asyncio
async def test_exchange_error_payload_is_not_silently_accepted() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "51000", "msg": "invalid parameter"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OptionsMarketDataError, match="51000"):
            await OptionsMarketDataAdapter(client=client)._get_json("okx", "/public/time", {})


def test_adapter_rejects_bad_configuration_and_exchange() -> None:
    with pytest.raises(ValueError):
        OptionsMarketDataAdapter(timeout=0)
    with pytest.raises(ValueError, match="exchange"):
        # Validation happens before any network request.
        import asyncio

        asyncio.run(OptionsMarketDataAdapter().fetch_options("unknown"))
