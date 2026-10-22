"""Read-only public options market data for Deribit and OKX.

Gloomberb (https://github.com/gloom-sh/gloomberb, MIT) was reviewed as a
reference for the requested integration. No Gloomberb source code is copied;
exchange payload mappings follow the official Deribit and OKX public API
contracts. Requests use httpx's ``HTTPS_PROXY`` environment support.
"""

from __future__ import annotations

import asyncio
import copy
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

_BASE_URLS = {
    "deribit": "https://www.deribit.com/api/v2",
    "okx": "https://www.okx.com/api/v5",
}
_OPTION_ID = re.compile(
    r"-(?P<expiry>\d{6}|\d{1,2}[A-Z]{3}\d{2})-"
    r"(?P<strike>\d+(?:\.\d+)?)-(?P<right>[CP])$"
)


class OptionsMarketDataError(RuntimeError):
    """Raised when public exchange option data cannot be fetched or normalized."""


def _expiration_key(instrument_id: str, timestamp_ms: Any = None) -> tuple[str, float, str] | None:
    match = _OPTION_ID.search(instrument_id)
    if not match:
        return None
    expiry_ms = float(timestamp_ms) if timestamp_ms not in (None, "") else 0.0
    expiry_text = match.group("expiry")
    if expiry_ms <= 0.0:
        try:
            date_format = "%y%m%d" if len(expiry_text) == 6 else "%d%b%y"
            expiry_date = datetime.strptime(expiry_text, date_format).replace(tzinfo=UTC)
        except ValueError:
            return None
        expiry_ms = expiry_date.timestamp() * 1000.0
    try:
        normalized_expiry = datetime.fromtimestamp(expiry_ms / 1000.0, UTC).strftime("%y%m%d")
    except (OverflowError, OSError, ValueError):
        return None
    option_type = "call" if match.group("right") == "C" else "put"
    return normalized_expiry, float(match.group("strike")), option_type


class OptionsMarketDataAdapter:
    """Fetch normalized public option chains with timeout, retry, and in-memory TTL cache.

    Args:
        timeout: Per-request timeout in seconds.
        max_retries: Number of retries after the first attempt for network errors,
            HTTP 429, and HTTP 5xx responses.
        cache_ttl: Successful GET response cache lifetime in seconds.
        client: Optional caller-owned httpx client, primarily for tests.
    """

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_retries: int = 2,
        cache_ttl: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if timeout <= 0 or max_retries < 0 or cache_ttl < 0:
            raise ValueError(
                "timeout must be positive; max_retries and cache_ttl must be non-negative"
            )
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache_ttl = cache_ttl
        self._client = client
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = asyncio.Lock()

    async def _get_json(self, exchange: str, path: str, params: dict[str, str]) -> Any:
        url = f"{_BASE_URLS[exchange]}{path}"
        key = f"{url}?{httpx.QueryParams(params)}"
        async with self._cache_lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return copy.deepcopy(cached[1])

        last_error: Exception | None = None
        attempts_made = 0
        for attempt in range(self.max_retries + 1):
            attempts_made = attempt + 1
            try:
                if self._client is None:
                    async with httpx.AsyncClient(timeout=self.timeout, trust_env=True) as client:
                        response = await client.get(url, params=params)
                else:
                    response = await self._client.get(url, params=params, timeout=self.timeout)

                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                payload = response.json()
                if exchange == "deribit":
                    if payload.get("error"):
                        raise OptionsMarketDataError(f"Deribit API error: {payload['error']}")
                    result = payload.get("result")
                else:
                    if payload.get("code") != "0":
                        raise OptionsMarketDataError(
                            f"OKX API error code={payload.get('code')}: {payload.get('msg', '')}"
                        )
                    result = payload.get("data")
                async with self._cache_lock:
                    self._cache[key] = (time.monotonic() + self.cache_ttl, result)
                return copy.deepcopy(result)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code < 500 and exc.response.status_code != 429:
                    break
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
            if attempt < self.max_retries:
                await asyncio.sleep(0.2 * (2**attempt))
        message = f"GET {url} failed after {attempts_made} attempt(s): {last_error}"
        raise OptionsMarketDataError(message) from last_error

    async def fetch_options(self, exchange: str, *, underlying: str = "BTC") -> dict[str, Any]:
        """Fetch a normalized active option chain for one supported exchange."""
        exchange_name = exchange.lower()
        if exchange_name not in _BASE_URLS:
            raise ValueError("exchange must be 'deribit' or 'okx'")
        if not underlying or not underlying.strip():
            raise ValueError("underlying must not be empty")
        base = underlying.upper().strip().split("-")[0]
        fetched_at = datetime.now(UTC).isoformat()
        if exchange_name == "deribit":
            instruments, summaries, server_time = await asyncio.gather(
                self._get_json("deribit", "/public/get_instruments", {
                    "currency": base, "kind": "option", "expired": "false",
                }),
                self._get_json("deribit", "/public/get_book_summary_by_currency", {
                    "currency": base, "kind": "option",
                }),
                self._get_json("deribit", "/public/get_time", {}),
            )
            instrument_map = {item["instrument_name"]: item for item in instruments or []}
            chain: list[dict[str, Any]] = []
            spots: list[float] = []
            for summary in summaries or []:
                instrument_id = summary.get("instrument_name", "")
                instrument = instrument_map.get(instrument_id, {})
                parsed = _expiration_key(instrument_id, instrument.get("expiration_timestamp"))
                if parsed is None:
                    continue
                expiry, strike, option_type = parsed
                spot = float(summary.get("underlying_price") or 0.0)
                if spot > 0:
                    spots.append(spot)
                iv_percent = summary.get("mark_iv")
                chain.append({
                    "exchange": exchange_name,
                    "underlying": base,
                    "instrument_id": instrument_id,
                    "expiry": expiry,
                    "expiration_timestamp": float(instrument.get("expiration_timestamp") or 0),
                    "strike": strike,
                    "option_type": option_type,
                    "open_interest": float(summary.get("open_interest") or 0.0),
                    "mark_iv": float(iv_percent) / 100.0 if iv_percent not in (None, "") else None,
                    "delta": _float_or_none(summary.get("delta")),
                    "gamma": _float_or_none(summary.get("gamma")),
                    "contract_multiplier": float(instrument.get("contract_size") or 1.0),
                    "underlying_price": spot or None,
                    "provider_timestamp": int(summary.get("creation_timestamp") or 0),
                })
            spot_price = sum(spots) / len(spots) if spots else None
            provider_timestamp = int(server_time) if server_time is not None else None
        else:
            uly = f"{base}-USD"
            (
                instruments,
                open_interest,
                summaries,
                index_tickers,
                server_time,
            ) = await asyncio.gather(
                self._get_json("okx", "/public/instruments", {"instType": "OPTION", "uly": uly}),
                self._get_json("okx", "/public/open-interest", {"instType": "OPTION", "uly": uly}),
                self._get_json("okx", "/public/opt-summary", {"uly": uly}),
                self._get_json("okx", "/market/index-tickers", {"instId": uly}),
                self._get_json("okx", "/public/time", {}),
            )
            instrument_map = {}
            for instrument in instruments or []:
                parsed = _expiration_key(instrument.get("instId", ""), instrument.get("expTime"))
                if parsed:
                    instrument_map[parsed] = instrument
            oi_map: dict[tuple[str, float, str], dict[str, Any]] = {}
            for row in open_interest or []:
                parsed = _expiration_key(row.get("instId", ""))
                if parsed:
                    oi_map[parsed] = row
            summary_map: dict[tuple[str, float, str], dict[str, Any]] = {}
            for row in summaries or []:
                parsed = _expiration_key(row.get("instId", ""))
                if parsed:
                    summary_map[parsed] = row
            chain = []
            for parsed, instrument in instrument_map.items():
                expiry, strike, option_type = parsed
                summary = summary_map.get(parsed, {})
                oi = oi_map.get(parsed, {})
                mark_iv = summary.get("markVol")
                chain.append({
                    "exchange": exchange_name,
                    "underlying": uly,
                    "instrument_id": instrument.get("instId"),
                    "expiry": expiry,
                    "expiration_timestamp": float(instrument.get("expTime") or 0),
                    "strike": strike,
                    "option_type": option_type,
                    "open_interest": float(oi.get("oi") or 0.0),
                    "open_interest_usd": _float_or_none(oi.get("oiUsd")),
                    "mark_iv": float(mark_iv) if mark_iv not in (None, "") else None,
                    "delta": _float_or_none(summary.get("deltaBS", summary.get("delta"))),
                    "gamma": _float_or_none(summary.get("gammaBS", summary.get("gamma"))),
                    "contract_multiplier": float(instrument.get("ctMult") or 1.0),
                    "underlying_price": _float_or_none(summary.get("fwdPx")),
                    "provider_timestamp": int(summary.get("ts") or oi.get("ts") or 0),
                })
            index_row = (index_tickers or [{}])[0]
            spot_price = _float_or_none(index_row.get("idxPx"))
            if spot_price is None:
                forwards = [r["underlying_price"] for r in chain if r.get("underlying_price")]
                spot_price = sum(forwards) / len(forwards) if forwards else None
            time_row = (server_time or [{}])[0]
            provider_timestamp = int(time_row.get("ts") or 0) or None

        if not chain:
            raise OptionsMarketDataError(
                f"{exchange_name} returned no active {base} option instruments"
            )
        return {
            "exchange": exchange_name,
            "underlying": base,
            "fetched_at": fetched_at,
            "provider_timestamp": provider_timestamp,
            "spot": spot_price,
            "options": chain,
        }


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None
