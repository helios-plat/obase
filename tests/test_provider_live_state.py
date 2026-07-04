"""Tests for C5 — ProviderLiveState + Rolling403Rate + fal_balance_probe."""

from __future__ import annotations

import asyncio

import pytest

from obase.provider_live_state import (
    ProviderLiveState,
    Rolling403Rate,
    fal_balance_probe,
)

# ── Rolling403Rate ──────────────────────────────────────────────────────────


def test_rolling_403_rate_and_health():
    r = Rolling403Rate(window=4)
    assert r.rate() == 0.0 and r.health() == 1.0  # empty
    for is_403 in (False, False, True, True):
        r.record(is_403=is_403)
    assert r.rate() == pytest.approx(0.5)
    assert r.health() == pytest.approx(0.5)


def test_rolling_403_window_evicts():
    r = Rolling403Rate(window=2)
    r.record(is_403=True)
    r.record(is_403=True)
    r.record(is_403=False)  # evicts oldest → [True, False]
    assert r.rate() == pytest.approx(0.5)


def test_rolling_403_window_validated():
    with pytest.raises(ValueError):
        Rolling403Rate(window=0)


# ── ProviderLiveState ───────────────────────────────────────────────────────


def test_live_state_update_and_get():
    s = ProviderLiveState()
    s.update("fal", balance_usd=12.5, health=0.9, updated_at=100.0)
    assert s.get("fal") == {"balance_usd": 12.5, "health": 0.9, "updated_at": 100.0}
    # partial update keeps prior fields
    s.update("fal", health=0.4, updated_at=200.0)
    got = s.get("fal")
    assert got["balance_usd"] == 12.5 and got["health"] == 0.4 and got["updated_at"] == 200.0


def test_live_state_get_unknown_is_empty():
    assert ProviderLiveState().get("nope") == {}


def test_healthy_gates_on_balance_and_health():
    s = ProviderLiveState()
    s.update("a", balance_usd=0.0, health=0.9)  # broke
    s.update("b", balance_usd=5.0, health=0.2)  # unhealthy
    s.update("c", balance_usd=5.0, health=0.9)  # ok
    assert s.healthy("a", min_balance_usd=1.0) is False
    assert s.healthy("b", min_health=0.5) is False
    assert s.healthy("c", min_balance_usd=1.0, min_health=0.5) is True
    # no record → True (don't kill un-probed providers)
    assert s.healthy("unseen") is True


# ── fal_balance_probe ───────────────────────────────────────────────────────


def test_probe_unknown_when_no_config():
    res = asyncio.run(fal_balance_probe())
    assert res == {"balance_usd": None, "ok": True, "source": "unknown"}


def test_probe_403_rate_proxy():
    ok = asyncio.run(fal_balance_probe(config={"error_rate_403": 0.1, "max_403_rate": 0.5}))
    assert ok == {"balance_usd": None, "ok": True, "source": "403_rate"}
    bad = asyncio.run(fal_balance_probe(config={"error_rate_403": 0.8, "max_403_rate": 0.5}))
    assert bad["ok"] is False and bad["source"] == "403_rate"


def test_probe_api_path(monkeypatch):
    class _Resp:
        def raise_for_status(self): ...
        def json(self):
            return {"balance_usd": 3.5}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    res = asyncio.run(
        fal_balance_probe(
            config={"FAL_BALANCE_URL": "https://x/bal", "FAL_API_KEY": "k", "min_balance_usd": 1.0}
        )
    )
    assert res == {"balance_usd": 3.5, "ok": True, "source": "api"}


def test_probe_api_failure_falls_back_to_403_rate(monkeypatch):
    import httpx

    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    res = asyncio.run(
        fal_balance_probe(
            config={
                "FAL_BALANCE_URL": "https://x/bal",
                "FAL_API_KEY": "k",
                "error_rate_403": 0.9,
                "max_403_rate": 0.5,
            }
        )
    )
    assert res["source"] == "403_rate" and res["ok"] is False
