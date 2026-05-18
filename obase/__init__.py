"""obase — Helios 生态横切基础设施库 (OBASE_SPEC v0.2)."""
from __future__ import annotations

__version__ = "0.1.0"

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

__all__ = [
    "__version__",
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
