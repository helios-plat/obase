"""obase — Helios 生态横切基础设施库 (OBASE_SPEC v0.2)."""

from __future__ import annotations

__version__ = "0.16.1"

from obase.bootstrap import bootstrap, load_env
from obase.cache import Cache, cached
from obase.cost_tracker import CostTracker, PricingEntry, PricingTable, StepUsage, CostBreakdown, convert_currency
from obase.exceptions import (
    BudgetExceeded,
    CacheError,
    EnvLoadError,
    FSError,
    ObaseAuthError,
    OBaseError,
    ObaseSecretsError,
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
from obase.tool_registry import ToolMeta, ToolRegistry, ToolRegistryConflict, register_tool
from obase.trail import Trail, load_trail, query_trail
from obase.uuid7 import uuid7

# Sprint 11 — Notification Compliance (D2)
from obase.notification import NotificationComplianceFilter

# Sprint 13 — Intraday Poll Scheduler (D1)
from obase.scheduler import IntradayPollScheduler

# text — fuzzy matching utilities
from obase import text

# B6 — notify + audit submodules
from obase import notify
from obase import audit

# B1 — webhook signing submodule
from obase import webhook

# W抽-01 — 8 new submodules from Helios extraction
from obase import collector_base
from obase import email_client
from obase import environ_processor_base
from obase import ohlcv_store
from obase import price_store
from obase import symbol_normalize
from obase import telegram_client
from obase import ts_writer

__all__ = [
    "__version__",
    "bootstrap",
    "load_env",
    "uuid7",
    "Cache",
    "cached",
    "CostTracker",
    "PricingEntry",
    "PricingTable",
    "OBaseError",
    "ObaseAuthError",
    "ObaseSecretsError",
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
    "ToolMeta",
    "ToolRegistry",
    "ToolRegistryConflict",
    "register_tool",
    "Trail",
    "load_trail",
    "query_trail",
    "NotificationComplianceFilter",
    "IntradayPollScheduler",
    # text submodule
    "text",
    # B6 submodules
    "notify",
    "audit",
    # B1 submodule
    "webhook",
    # W抽-01 submodules
    "collector_base",
    "email_client",
    "environ_processor_base",
    "ohlcv_store",
    "price_store",
    "symbol_normalize",
    "telegram_client",
    "ts_writer",
    # Stratum B3 (v0.8.0)
    "crypto",
    "migration",
    "circuit_breaker",
    "retry",
    "CryptoError",
    "encrypt_token",
    "decrypt_token",
    "derive_master_key",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "RetryPolicy",
    "retry_with_backoff",
    "MigrationResult",
    "run_migration",
    # Stratum B1 (v0.10.0)
    "http",
    "observability",
    "SSRFBlockedError",
    "is_safe_ip",
    "make_ssrf_safe_opener",
    "resolve_and_check",
    "Span",
    "Tracer",
    "get_tracer",
    # v0.11.0 persistence submodule
    "persistence",
    "PgPool",
    "transaction",
    "upsert_batch",
    "vector_search",
    "VectorMetric",
    "ensure_table",
    "ensure_column",
    "ensure_index",
    "ensure_extension",
    # v0.13.0 sympy_runtime
    "sympy_runtime",
    # v0.15.6 obase.gpu
    "gpu",
    "GpuScheduler",
    "ModelRegistry",
    "LocalModelProvider",
]

# --- Stratum B3 obase submodules (v0.8.0) ---
from obase import crypto
from obase import migration
from obase import circuit_breaker
from obase import retry
from obase import config as config_loader
from obase.crypto import CryptoError, decrypt_token, derive_master_key, encrypt_token
from obase.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from obase.retry import RetryPolicy, retry_with_backoff
from obase.migration import MigrationResult, run_migration

# --- Stratum B1 obase submodules (v0.10.0) ---
from obase import http
from obase import observability
from obase.http.dns_pinned_transport import (
    SSRFBlockedError,
    is_safe_ip,
    make_ssrf_safe_opener,
    resolve_and_check,
)
from obase.observability.tracer import Span, Tracer, get_tracer

# --- v0.11.0 persistence submodule ---
from obase import persistence
from obase.persistence import (
    PgPool,
    VectorMetric,
    ensure_column,
    ensure_extension,
    ensure_index,
    ensure_table,
    transaction,
    upsert_batch,
    vector_search,
)
from obase.lsp import LspClientManager, LspServerHandle
from obase.mcp_client import McpClientRegistry, McpClientHandle

# v0.13.0 — sympy_runtime sandbox (M-0 batch)
from obase import sympy_runtime
from obase.git import run_git, GitResult

# v0.15.6 — obase.gpu
from obase import gpu
from obase.gpu import GpuScheduler, ModelRegistry, LocalModelProvider
