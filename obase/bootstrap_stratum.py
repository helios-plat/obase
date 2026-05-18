"""Stratum bootstrap — lightweight one-shot initializer for the oprim layer."""
from __future__ import annotations

from pathlib import Path

from obase import config as cfg
from obase import logging as olog


def bootstrap(config_path: Path | None = None, log_level: str = "INFO") -> None:
    olog.setup_logging(log_level)
    cfg.load_config(config_path)
    stratum_dir = Path.home() / ".stratum"
    for d in ["inbox", "data/substrate", "_archive", "index/lance", "index/tantivy"]:
        (stratum_dir / d).mkdir(parents=True, exist_ok=True)
    olog.info("bootstrap complete", config_path=str(config_path or "default"))
