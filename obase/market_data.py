"""obase.market_data — parquet market-data resource for the quant coprocessor.

3O layer: obase (I/O and resources).
Physical data plane: loads millions of rows in sandbox subprocesses and
exposes ONLY schema + head(5) to the LLM (control plane). Includes a GBM
synthetic-data generator for tests/demos.

Convention: {data_dir}/{asset_id}.parquet with DatetimeIndex and columns
open/high/low/close/volume.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

DEFAULT_DATA_DIR = str(Path.home() / ".veya" / "market_data")


def resolve_data_dir(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir or os.environ.get("VEYA_QUANT_DATA_DIR", DEFAULT_DATA_DIR)).expanduser()


def ensure_synthetic_data(
    asset_id: str,
    data_dir: str | Path | None = None,
    *,
    days: int = 750,
    start: str = "2022-01-01",
    seed: int = 42,
) -> Path:
    """Generate synthetic GBM market data (parquet) — tests/demos only."""
    import numpy as np
    import pandas as pd

    base = resolve_data_dir(data_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{asset_id}.parquet"
    if path.exists():
        return path

    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=days)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, days)))
    open_ = close * (1 + rng.normal(0, 0.004, days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, days)))
    volume = rng.integers(1_000_000, 10_000_000, days)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    df.index.name = "date"
    df.to_parquet(path)
    _log.info("synthetic data generated: %s (%d rows)", path, days)
    return path


def load_asset(asset_id: str, data_dir: str | Path | None = None) -> Any:
    """Load the full parquet frame (physical layer — never into LLM context)."""
    import pandas as pd

    path = resolve_data_dir(data_dir) / f"{asset_id}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"行情数据不存在: {path} (请先运行 ensure_synthetic_data 或放入真实 parquet)"
        )
    return pd.read_parquet(path)


def get_market_data_schema(asset_id: str, data_dir: str | Path | None = None) -> str:
    """Control-plane metadata injection: schema + first 5 rows only."""
    df = load_asset(asset_id, data_dir)
    df_sample = df.head(5)

    lines = [f"Dataset: {asset_id}", "Columns and Types:"]
    for col, dtype in df_sample.dtypes.items():
        lines.append(f"- {col}: {dtype}")
    lines.append("")
    lines.append(f"Total rows: {len(df)} (NOT loaded into context — computed in sandbox)")
    lines.append("")
    lines.append("Sample Data (First 5 rows):")
    lines.append(df_sample.to_string())
    return "\n".join(lines)
