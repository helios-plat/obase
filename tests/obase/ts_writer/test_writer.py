"""Tests for obase.ts_writer."""

from __future__ import annotations

from typing import Any

import pytest

from obase.ts_writer import TsWriterError, write_fusion_ts, write_regime_ts, write_timeframes_ts


class _MockSession:
    def __init__(self) -> None:
        self.executed: list = []

    async def execute(self, statement: Any, parameters: Any = None) -> None:
        self.executed.append((statement, parameters))

    async def commit(self) -> None:
        pass


class _MockSessionFactory:
    def __init__(self) -> None:
        self.session = _MockSession()

    async def __aenter__(self) -> _MockSession:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_write_fusion_ts_success():
    sf = _MockSessionFactory()
    result = {
        "dimensions": [
            {
                "name": "trend",
                "value": 0.5,
                "weight": 0.2,
                "weighted_contribution": 0.1,
                "layer": "L1",
                "side": "long",
                "category": "core",
                "confidence": 0.8,
            }
        ],
        "core": {"long": 0.6, "short": 0.3, "alignment": "bullish", "direction": "up"},
        "adjustments": {"total": 0.1},
        "redlines": [],
        "finalScore": 72,
        "finalTier": "bullish",
        "finalLabel": "Buy",
        "confidenceTier": "high",
    }
    await write_fusion_ts(symbol="BTC", result=result, session_factory=sf)
    assert len(sf.session.executed) >= 2


@pytest.mark.asyncio
async def test_write_fusion_ts_empty_dimensions():
    sf = _MockSessionFactory()
    result = {"dimensions": [], "core": {}, "adjustments": {}, "redlines": []}
    await write_fusion_ts(symbol="BTC", result=result, session_factory=sf)
    assert len(sf.session.executed) >= 1


@pytest.mark.asyncio
async def test_write_fusion_ts_exception_swallowed():
    class _FailFactory:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            pass

    await write_fusion_ts(symbol="BTC", result={}, session_factory=_FailFactory())


@pytest.mark.asyncio
async def test_write_timeframes_ts_success():
    sf = _MockSessionFactory()
    result = {
        "tf1": {
            "frames": {
                "1d": {
                    "current_price": 50000,
                    "key_ma": {"label": "MA200", "value": 48000, "deviation_pct": 4.0},
                    "trend": "up",
                    "indicator": {"name": "RSI", "value": 55},
                }
            },
            "strategic": {
                "state": "bullish",
                "confidence": 0.8,
                "triggers": [],
                "available_sources": [],
                "unavailable_sources": [],
                "candidate_state": None,
                "confirmed_state": "bullish",
                "sustained_days": 3,
                "satisfied_count": 4,
            },
        },
        "tf2": {
            "frames": {},
            "trend": {"daily_direction": "up", "h4_direction": "up", "alignment": "aligned"},
        },
        "tf3": {
            "frames": {},
            "entry": {
                "support": 47000,
                "resistance": 53000,
                "current": 50000,
                "distance_to_support_pct": 6.0,
                "distance_to_resistance_pct": 6.0,
                "rating": "neutral",
            },
        },
    }
    await write_timeframes_ts(symbol="BTC", result=result, session_factory=sf)
    assert len(sf.session.executed) >= 4


@pytest.mark.asyncio
async def test_write_regime_ts_success():
    sf = _MockSessionFactory()
    result = {
        "as_of": "2024-01-01T00:00:00+00:00",
        "regime": "risk_on",
        "confidence": 0.85,
        "components": {
            "trend": "up",
            "trend_confidence": 0.9,
            "volatility": "low",
            "vol_confidence": 0.8,
        },
        "partial_history": False,
    }
    await write_regime_ts(symbol="BTC", result=result, session_factory=sf)
    assert len(sf.session.executed) == 1


@pytest.mark.asyncio
async def test_write_regime_ts_exception_swallowed():
    class _FailFactory:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            pass

    await write_regime_ts(symbol="BTC", result={}, session_factory=_FailFactory())


def test_ts_writer_error_is_exception():
    assert issubclass(TsWriterError, Exception)
