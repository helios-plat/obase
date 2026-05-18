"""obase — Stratum core utilities + Helios infrastructure library.

Stratum-native modules (errors, logging, config, cost_tracker_stratum,
bootstrap_stratum) are always importable without optional dependencies.
Legacy Helios modules (structlog/pydantic-based) are loaded only when
their dependencies are present.
"""
from __future__ import annotations

__version__ = "0.1.0"

# --- Stratum-native modules (no external deps beyond stdlib + pyyaml) ---
# These are always importable. Import them eagerly so that
# `from obase import logging as olog` works in oprim modules.
from obase.errors import (
    ConfigError,
    DuplicateSubstrateError,
    EmbeddingError,
    FulltextError,
    IngestError,
    LLMError,
    LLMRateLimitError,
    MetaDBError,
    PDFParseError,
    QuotaExceededError,
    StratumError,
    UnsupportedFileTypeError,
    UnsupportedImageError,
    VectorDBError,
)

__all__ = [
    "__version__",
    "StratumError",
    "ConfigError",
    "PDFParseError",
    "UnsupportedFileTypeError",
    "UnsupportedImageError",
    "EmbeddingError",
    "QuotaExceededError",
    "VectorDBError",
    "FulltextError",
    "MetaDBError",
    "LLMError",
    "LLMRateLimitError",
    "IngestError",
    "DuplicateSubstrateError",
]

# --- Legacy Helios modules (require structlog, pydantic, tenacity, …) ---
try:
    from obase.bootstrap import bootstrap, load_env
    from obase.cache import Cache, cached
    from obase.cost_tracker import CostTracker, PricingEntry, PricingTable
    from obase.exceptions import (
        BudgetExceeded,
        CacheError,
        EnvLoadError,
        FSError,
        OBaseError,
        PauseRequested,
        PricingNotConfiguredError,
        ProviderDiscoveryError,
        ProviderNotFoundError,
        RateLimitExceeded,
        StageContractViolation,
    )
    from obase.fs import FS
    from obase.orchestrator import Pipeline, RunState, Stage, run_pipeline
    from obase.provider_registry import ProviderRegistry
    from obase.rate_limit import RateLimiter, RateLimitRegistry
    from obase.trail import Trail, load_trail, query_trail

    __all__ += [
        "bootstrap",
        "load_env",
        "Cache",
        "cached",
        "CostTracker",
        "PricingEntry",
        "PricingTable",
        "OBaseError",
        "StageContractViolation",
        "PauseRequested",
        "BudgetExceeded",
        "PricingNotConfiguredError",
        "EnvLoadError",
        "CacheError",
        "RateLimitExceeded",
        "ProviderNotFoundError",
        "ProviderDiscoveryError",
        "FSError",
        "FS",
        "Pipeline",
        "RunState",
        "Stage",
        "run_pipeline",
        "ProviderRegistry",
        "RateLimitRegistry",
        "RateLimiter",
        "Trail",
        "load_trail",
        "query_trail",
    ]
except ImportError:
    pass
