"""Timeseries writer — fire-and-forget writes to hypertables."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

log = logging.getLogger(__name__)

_SQL_DIM = (
    "INSERT INTO ts_fusion_dimensions"
    " (time, symbol, dim_name, pack_id, value, weight,"
    " weighted_contribution, layer, side, category, confidence)"
    " VALUES (:time, :symbol, :dim_name, :pack_id, :value, :weight,"
    " :wc, :layer, :side, :category, :confidence)"
    " ON CONFLICT DO NOTHING"
)

_SQL_LAYER = (
    "INSERT INTO ts_fusion_layers"
    " (time, symbol, redline_status, redline_count,"
    " core_long, core_short, core_alignment, core_direction,"
    " adjustments_score, final_score, final_tier,"
    " final_label, confidence_tier)"
    " VALUES (:time, :symbol, :rs, :rc, :cl, :cs, :ca, :cd,"
    " :adj, :fs, :ft, :fl, :ct)"
    " ON CONFLICT DO NOTHING"
)

_SQL_TF = (
    "INSERT INTO ts_timeframes"
    " (time, symbol, frame, current_price, key_ma_label,"
    " key_ma_value, key_ma_deviation_pct, trend,"
    " indicator_name, indicator_value)"
    " VALUES (:time, :symbol, :frame, :current_price,"
    " :key_ma_label, :key_ma_value, :key_ma_deviation_pct,"
    " :trend, :indicator_name, :indicator_value)"
    " ON CONFLICT DO NOTHING"
)

_SQL_STRATEGIC = (
    "INSERT INTO ts_timeframes_strategic"
    " (time, symbol, state, confidence, triggers_json,"
    " available_sources, unavailable_sources,"
    " candidate_state, confirmed_state,"
    " sustained_days, satisfied_count)"
    " VALUES (:time, :symbol, :state, :confidence,"
    " :triggers_json, :available_sources,"
    " :unavailable_sources, :candidate_state,"
    " :confirmed_state, :sustained_days, :satisfied_count)"
    " ON CONFLICT DO NOTHING"
)

_SQL_TREND = (
    "INSERT INTO ts_timeframes_trend"
    " (time, symbol, daily_direction, h4_direction, alignment)"
    " VALUES (:time, :symbol, :daily_direction,"
    " :h4_direction, :alignment)"
    " ON CONFLICT DO NOTHING"
)

_SQL_ENTRY = (
    "INSERT INTO ts_timeframes_entry"
    " (time, symbol, support, resistance, current_price,"
    " distance_to_support_pct, distance_to_resistance_pct, rating)"
    " VALUES (:time, :symbol, :support, :resistance,"
    " :current_price, :dist_s, :dist_r, :rating)"
    " ON CONFLICT DO NOTHING"
)

_SQL_REGIME = (
    "INSERT INTO ts_regime"
    " (time, symbol, regime, confidence, trend,"
    " trend_confidence, volatility, vol_confidence,"
    " partial_history)"
    " VALUES (:time, :symbol, :regime, :confidence,"
    " :trend, :trend_confidence, :volatility,"
    " :vol_confidence, :partial_history)"
    " ON CONFLICT DO NOTHING"
)


class DbSession(Protocol):
    """Protocol for async DB session (execute + commit)."""

    async def execute(self, statement: Any, parameters: Any = None) -> Any: ...
    async def commit(self) -> None: ...


class SessionFactory(Protocol):
    """Protocol for async context manager producing DbSession."""

    async def __aenter__(self) -> DbSession: ...
    async def __aexit__(self, *args: Any) -> None: ...


async def write_fusion_ts(
    *,
    symbol: str,
    result: dict,
    session_factory: SessionFactory,
    pack_id: str = "default",
) -> None:
    """Write one fusion-score computation to timeseries tables.

    Args:
        symbol: Asset symbol.
        result: Fusion computation result dict.
        session_factory: Async context manager yielding a DB session.
        pack_id: Weight pack identifier.

    Raises:
        TsWriterError: Never (fire-and-forget, logs warnings).

    Example:
        >>> await write_fusion_ts(
        ...     symbol="BTC", result=fusion_result, session_factory=sf
        ... )
    """
    try:
        now = datetime.now(UTC)
        dimensions = result.get("dimensions", [])
        core = result.get("core", {})
        adjustments = result.get("adjustments", {})
        redlines = result.get("redlines", [])

        breached = [r for r in redlines if r.get("status") == "breached"]
        has_warning = any(r.get("status") == "warning" for r in redlines)
        redline_status = (
            "breached" if breached else ("warning" if has_warning else "pass")
        )

        dim_params = [
            {
                "time": now,
                "symbol": symbol,
                "dim_name": d["name"],
                "pack_id": pack_id,
                "value": float(d.get("value") or 0),
                "weight": float(d.get("weight") or 0),
                "wc": float(d.get("weighted_contribution") or 0),
                "layer": d.get("layer"),
                "side": d.get("side"),
                "category": d.get("category"),
                "confidence": float(d.get("confidence") or 0),
            }
            for d in dimensions
        ]

        layer_params = {
            "time": now,
            "symbol": symbol,
            "rs": redline_status,
            "rc": len(breached),
            "cl": core.get("long"),
            "cs": core.get("short"),
            "ca": core.get("alignment"),
            "cd": core.get("direction"),
            "adj": adjustments.get("total"),
            "fs": result.get("finalScore"),
            "ft": result.get("finalTier"),
            "fl": result.get("finalLabel"),
            "ct": result.get("confidenceTier"),
        }

        async with session_factory as session:
            if dim_params:
                for p in dim_params:
                    await session.execute(_SQL_DIM, p)
            await session.execute(_SQL_LAYER, layer_params)
            await session.commit()
    except Exception:
        log.warning("ts_write_fusion_failed symbol=%s", symbol, exc_info=True)


async def write_timeframes_ts(
    *,
    symbol: str,
    result: dict,
    session_factory: SessionFactory,
) -> None:
    """Write one timeframes computation to timeseries tables.

    Args:
        symbol: Asset symbol.
        result: Timeframes computation result dict.
        session_factory: Async context manager yielding a DB session.

    Raises:
        TsWriterError: Never (fire-and-forget, logs warnings).

    Example:
        >>> await write_timeframes_ts(
        ...     symbol="BTC", result=tf_result, session_factory=sf
        ... )
    """
    try:
        now = datetime.now(UTC)
        tf1 = result.get("tf1", {})
        tf2 = result.get("tf2", {})
        tf3 = result.get("tf3", {})

        all_frames = {
            **tf1.get("frames", {}),
            **tf2.get("frames", {}),
            **tf3.get("frames", {}),
        }

        frame_params = []
        for frame_key, fd in all_frames.items():
            key_ma = fd.get("key_ma") or {}
            ind = fd.get("indicator") or {}
            frame_params.append({
                "time": now,
                "symbol": symbol,
                "frame": frame_key,
                "current_price": fd.get("current_price"),
                "key_ma_label": key_ma.get("label"),
                "key_ma_value": key_ma.get("value"),
                "key_ma_deviation_pct": key_ma.get("deviation_pct"),
                "trend": fd.get("trend"),
                "indicator_name": ind.get("name"),
                "indicator_value": ind.get("value"),
            })

        strategic = tf1.get("strategic", {})
        trend = tf2.get("trend", {})
        entry = tf3.get("entry", {})

        async with session_factory as session:
            for p in frame_params:
                await session.execute(_SQL_TF, p)
            await session.execute(
                _SQL_STRATEGIC,
                {
                    "time": now,
                    "symbol": symbol,
                    "state": strategic.get("state"),
                    "confidence": strategic.get("confidence"),
                    "triggers_json": json.dumps(
                        strategic.get("triggers", [])
                    ),
                    "available_sources": strategic.get(
                        "available_sources", []
                    ),
                    "unavailable_sources": strategic.get(
                        "unavailable_sources", []
                    ),
                    "candidate_state": strategic.get("candidate_state"),
                    "confirmed_state": strategic.get("confirmed_state"),
                    "sustained_days": strategic.get("sustained_days", 0),
                    "satisfied_count": strategic.get("satisfied_count", 0),
                },
            )
            await session.execute(
                _SQL_TREND,
                {
                    "time": now,
                    "symbol": symbol,
                    "daily_direction": trend.get("daily_direction"),
                    "h4_direction": trend.get("h4_direction"),
                    "alignment": trend.get("alignment"),
                },
            )
            await session.execute(
                _SQL_ENTRY,
                {
                    "time": now,
                    "symbol": symbol,
                    "support": entry.get("support"),
                    "resistance": entry.get("resistance"),
                    "current_price": entry.get("current"),
                    "dist_s": entry.get("distance_to_support_pct"),
                    "dist_r": entry.get("distance_to_resistance_pct"),
                    "rating": entry.get("rating"),
                },
            )
            await session.commit()
    except Exception:
        log.warning(
            "ts_write_timeframes_failed symbol=%s", symbol, exc_info=True
        )


async def write_regime_ts(
    *,
    symbol: str,
    result: dict,
    session_factory: SessionFactory,
) -> None:
    """Write one regime classification to timeseries table.

    Args:
        symbol: Asset symbol.
        result: Regime classification result dict.
        session_factory: Async context manager yielding a DB session.

    Raises:
        TsWriterError: Never (fire-and-forget, logs warnings).

    Example:
        >>> await write_regime_ts(
        ...     symbol="BTC", result=regime_result, session_factory=sf
        ... )
    """
    try:
        raw_as_of = result.get("as_of")
        now = (
            datetime.fromisoformat(raw_as_of)
            if isinstance(raw_as_of, str)
            else raw_as_of
        )
        components = result.get("components") or {}

        async with session_factory as session:
            await session.execute(
                _SQL_REGIME,
                {
                    "time": now,
                    "symbol": symbol,
                    "regime": result.get("regime"),
                    "confidence": result.get("confidence"),
                    "trend": components.get("trend"),
                    "trend_confidence": components.get("trend_confidence"),
                    "volatility": components.get("volatility"),
                    "vol_confidence": components.get("vol_confidence"),
                    "partial_history": result.get("partial_history", False),
                },
            )
            await session.commit()
    except Exception:
        log.warning(
            "ts_write_regime_failed symbol=%s", symbol, exc_info=True
        )
