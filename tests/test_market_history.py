from __future__ import annotations

import httpx
import pytest

from obase.market_history import MarketHistoryError, fetch_price_history


def test_okx_history_normalizes_fixed_sample_and_uses_requested_range() -> None:
    rows = [
        ["1792454400000", "61000", "62000", "60000", "61500", "12.5", "765000", "765000", "1"],
        ["1792458000000", "61500", "63000", "61000", "62500", "8.0", "500000", "500000", "1"],
    ]
    seen = {}

    def respond(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"code": "0", "msg": "", "data": rows}, request=request)

    result = fetch_price_history(
        exchange="okx",
        symbol="BTCUSDT",
        bar="1h",
        start=1792454400000,
        end=1792461600000,
        limit=2,
        transport=httpx.MockTransport(respond),
        cache_ttl_s=0,
    )
    assert result["status"] == "success" and result["symbol"] == "BTC-USDT"
    assert [item["close"] for item in result["candles"]] == [61500.0, 62500.0]
    assert result["count"] == 2 and result["raw_response_summary"]["raw_record_count"] == 2
    assert (
        seen["bar"] == "1H"
        and seen["after"] == "1792461600000"
        and seen["before"] == "1792454400000"
    )


def test_deribit_history_normalizes_fixed_sample() -> None:
    sample = {
        "jsonrpc": "2.0",
        "result": {
            "status": "ok",
            "ticks": [1792454400000, 1792458000000],
            "open": [10, 11],
            "high": [12, 13],
            "low": [9, 10],
            "close": [11, 12],
            "volume": [3, 4],
        },
    }

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["instrument_name"] == "BTC-PERPETUAL"
        assert request.url.params["resolution"] == "60"
        return httpx.Response(200, json=sample, request=request)

    result = fetch_price_history(
        exchange="deribit",
        symbol="BTC",
        bar="1h",
        start=1792454400000,
        end=1792460000000,
        limit=2,
        transport=httpx.MockTransport(respond),
        cache_ttl_s=0,
    )
    assert result["count"] == 2 and result["candles"][1]["close"] == 12.0
    assert result["raw_response_summary"]["raw_record_count"] == 2


def test_cache_marks_second_result_and_returns_copy() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"code": "0", "msg": "", "data": []}, request=request)

    kwargs = dict(
        exchange="okx",
        symbol="BTC",
        bar="1h",
        start=1792454400000,
        end=1792461600000,
        limit=2,
        transport=httpx.MockTransport(respond),
        cache_ttl_s=60,
    )
    first = fetch_price_history(**kwargs)
    second = fetch_price_history(**kwargs)
    second["candles"].append({"close": -1})
    assert calls == 1 and first["cached"] is False
    assert fetch_price_history(**kwargs)["candles"] == []


def test_invalid_provider_bar_limit_and_bad_payload_fail_explicitly() -> None:
    with pytest.raises(ValueError, match="exchange"):
        fetch_price_history(exchange="private", cache_ttl_s=0)
    with pytest.raises(ValueError, match="Deribit does not support"):
        fetch_price_history(exchange="deribit", bar="1w", cache_ttl_s=0)
    with pytest.raises(ValueError, match="limit"):
        fetch_price_history(limit=0, cache_ttl_s=0)

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": "51000", "msg": "bad instrument", "data": []}, request=request
        )

    with pytest.raises(MarketHistoryError, match="bad instrument"):
        fetch_price_history(exchange="okx", transport=httpx.MockTransport(reject), cache_ttl_s=0)
