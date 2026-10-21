"""Read-only public OHLCV history from OKX or Deribit with bounded caching."""
from __future__ import annotations

import copy
import hashlib
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

import httpx

OKX_URL = "https://www.okx.com/api/v5/market/history-candles"
DERIBIT_URL = "https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
_MAX_LIMIT = 300
_BAR_MAP: dict[str, tuple[str, str | None, int]] = {
    "1m": ("1m", "1", 60_000), "3m": ("3m", "3", 180_000),
    "5m": ("5m", "5", 300_000), "15m": ("15m", "15", 900_000),
    "30m": ("30m", "30", 1_800_000), "1h": ("1H", "60", 3_600_000),
    "2h": ("2H", "120", 7_200_000), "4h": ("4H", "240", 14_400_000),
    "6h": ("6Hutc", "360", 21_600_000), "12h": ("12Hutc", "720", 43_200_000),
    "1d": ("1Dutc", "1D", 86_400_000), "1w": ("1Wutc", None, 604_800_000),
}
_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


class MarketHistoryError(RuntimeError):
    """Public market data could not be fetched or normalized."""


def _timestamp_ms(value: str | int | float | None) -> int | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        numeric = int(text)
        return numeric * 1000 if abs(numeric) < 100_000_000_000 else numeric
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {value!r}; use Unix seconds/ms or ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _iso_utc(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, UTC).isoformat().replace("+00:00", "Z")


def _normalize_symbol(exchange: str, symbol: str) -> str:
    value = symbol.strip().upper().replace("/", "-")
    if not value:
        raise ValueError("symbol is required")
    if exchange == "okx":
        if "-" not in value:
            value = f"{value[:-4]}-USDT" if value.endswith("USDT") and len(value) > 4 else f"{value}-USDT"
        return value
    if "-" not in value:
        return f"{value}-PERPETUAL"
    if value.endswith("-USDT") or value.endswith("-USD"):
        return f"{value.rsplit('-', 1)[0]}-PERPETUAL"
    return value


def _parse_okx_candle(row: list[Any]) -> dict[str, Any]:
    if len(row) < 6:
        raise MarketHistoryError("OKX returned a malformed candle row")
    try:
        ts = int(row[0])
        candle: dict[str, Any] = {
            "timestamp_ms": ts, "timestamp": _iso_utc(ts),
            "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
            "close": float(row[4]), "volume": float(row[5]),
        }
        if len(row) > 8:
            candle["confirmed"] = str(row[8]) == "1"
        elif len(row) > 6:
            candle["volume_currency"] = float(row[6])
        return candle
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketHistoryError("OKX returned a non-numeric candle row") from exc


def _proxy_url() -> str | None:
    configured = os.getenv("GLOOM3O_HTTPS_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if configured:
        return configured
    # NET.md distinguishes the host proxy from the Docker-network alias.
    return "http://proxy:2080" if os.path.exists("/.dockerenv") else "http://127.0.0.1:7890"


def fetch_price_history(
    *, exchange: str = "okx", symbol: str = "BTC-USDT", bar: str = "1h",
    start: str | int | None = None, end: str | int | None = None, limit: int = 100,
    timeout_s: float = 8.0, cache_ttl_s: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch public candles. Timestamps accept ISO-8601, Unix seconds, or Unix ms.

    ``transport`` is an injection seam for fixed-sample unit tests. Live requests
    use the verified HTTPS proxy recorded in NET.md and require no API credentials.
    """
    selected_exchange = exchange.strip().lower()
    if selected_exchange not in {"okx", "deribit"}:
        raise ValueError("exchange must be 'okx' or 'deribit'")
    normalized_bar = bar.strip().lower()
    if normalized_bar not in _BAR_MAP:
        raise ValueError(f"unsupported bar {bar!r}; supported bars: {', '.join(_BAR_MAP)}")
    okx_bar, deribit_resolution, interval_ms = _BAR_MAP[normalized_bar]
    if selected_exchange == "deribit" and deribit_resolution is None:
        raise ValueError(f"Deribit does not support bar={normalized_bar!r}")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {_MAX_LIMIT}")
    timeout = max(0.5, min(float(timeout_s), 30.0))
    end_ms = _timestamp_ms(end) or int(time.time() * 1000)
    start_ms = _timestamp_ms(start)
    if start_ms is None:
        start_ms = end_ms - interval_ms * limit
    if start_ms > end_ms:
        raise ValueError("start must be earlier than or equal to end")
    normalized_symbol = _normalize_symbol(selected_exchange, symbol)
    cache_key = (selected_exchange, normalized_symbol, normalized_bar, start_ms, end_ms, limit)
    if cache_ttl_s > 0:
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and time.monotonic() - cached[0] <= cache_ttl_s:
                result = copy.deepcopy(cached[1])
                result["cached"] = True
                return result

    client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
    if transport is None:
        proxy = _proxy_url()
        if proxy:
            client_kwargs["proxy"] = proxy
    else:
        client_kwargs["transport"] = transport
    endpoint = OKX_URL if selected_exchange == "okx" else DERIBIT_URL
    try:
        with httpx.Client(**client_kwargs) as client:
            if selected_exchange == "okx":
                params = {"instId": normalized_symbol, "bar": okx_bar, "limit": str(limit),
                          "after": str(end_ms), "before": str(start_ms)}
            else:
                params = {"instrument_name": normalized_symbol, "resolution": deribit_resolution,
                          "start_timestamp": start_ms, "end_timestamp": end_ms}
            response = client.get(endpoint, params=params, headers={"Accept": "application/json"})
            response.raise_for_status()
            raw_bytes = response.content
            try:
                payload = response.json()
            except ValueError as exc:
                raise MarketHistoryError(f"{selected_exchange} returned invalid JSON") from exc
    except MarketHistoryError:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise MarketHistoryError(f"{selected_exchange} public candles request failed: {type(exc).__name__}") from exc

    raw_records: list[Any]
    if selected_exchange == "okx":
        if not isinstance(payload, dict) or payload.get("code") != "0":
            message = payload.get("msg", "unexpected provider response") if isinstance(payload, dict) else "unexpected provider response"
            raise MarketHistoryError(f"OKX candles rejected request: {message}")
        raw_records = payload.get("data", [])
        if not isinstance(raw_records, list):
            raise MarketHistoryError("OKX response data must be a list")
        candles = [_parse_okx_candle(row) for row in raw_records]
    else:
        if not isinstance(payload, dict) or payload.get("error"):
            error = payload.get("error", {}) if isinstance(payload, dict) else "invalid response"
            raise MarketHistoryError(f"Deribit candles rejected request: {error}")
        chart = payload.get("result", {})
        if not isinstance(chart, dict) or chart.get("status") not in {"ok", "no_data"}:
            raise MarketHistoryError("Deribit returned an unexpected chart response")
        ticks = chart.get("ticks", [])
        arrays = [chart.get(key, []) for key in ("open", "high", "low", "close", "volume")]
        if any(not isinstance(values, list) for values in [ticks, *arrays]):
            raise MarketHistoryError("Deribit response candle arrays are malformed")
        if any(len(values) != len(ticks) for values in arrays):
            raise MarketHistoryError("Deribit response candle arrays have different lengths")
        raw_records = [{"tick": ticks[i], "open": arrays[0][i], "high": arrays[1][i],
                        "low": arrays[2][i], "close": arrays[3][i], "volume": arrays[4][i]}
                       for i in range(len(ticks))]
        candles = []
        try:
            for row in raw_records:
                ts = int(row["tick"])
                candles.append({"timestamp_ms": ts, "timestamp": _iso_utc(ts),
                                "open": float(row["open"]), "high": float(row["high"]),
                                "low": float(row["low"]), "close": float(row["close"]),
                                "volume": float(row["volume"])})
        except (TypeError, ValueError, OverflowError) as exc:
            raise MarketHistoryError("Deribit returned a non-numeric candle row") from exc

    candles = sorted((c for c in candles if start_ms <= c["timestamp_ms"] <= end_ms), key=lambda c: c["timestamp_ms"])
    if len(candles) > limit:
        candles = candles[-limit:]
    result = {
        "status": "success", "exchange": selected_exchange, "symbol": normalized_symbol,
        "bar": normalized_bar, "start": _iso_utc(start_ms), "end": _iso_utc(end_ms),
        "start_ms": start_ms, "end_ms": end_ms,
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "cached": False, "count": len(candles), "candles": candles, "source_endpoint": endpoint,
        "raw_response_summary": {
            "http_status": response.status_code,
            "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
            "provider_code": payload.get("code") if isinstance(payload, dict) else None,
            "provider_message": payload.get("msg") if isinstance(payload, dict) else None,
            "raw_record_count": len(raw_records),
            "raw_first_record": raw_records[0] if raw_records else None,
            "raw_last_record": raw_records[-1] if raw_records else None,
            "sha256": hashlib.sha256(raw_bytes).hexdigest(), "size_bytes": len(raw_bytes),
        },
    }
    if cache_ttl_s > 0:
        with _CACHE_LOCK:
            _CACHE[cache_key] = (time.monotonic(), copy.deepcopy(result))
    return result
