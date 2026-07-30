"""obase — Helios 生态横切基础设施库 (OBASE_SPEC v0.2)."""

from __future__ import annotations

__version__ = "0.21.0"

# text — fuzzy matching utilities
# B6 — notify + audit submodules
# B1 — webhook signing submodule
# W抽-01 — 8 new submodules from Helios extraction
from obase import (
    audit,
    collector_base,
    email_client,
    environ_processor_base,
    notify,
    ohlcv_store,
    price_store,
    symbol_normalize,
    telegram_client,
    text,
    ts_writer,
    webhook,
)
from obase.bootstrap import bootstrap, load_env
from obase.cache import Cache, DistributedLock, cached
from obase.cost_tracker import (
    CostBreakdown,
    CostTracker,
    PricingEntry,
    PricingTable,
    StepUsage,
    convert_currency,
)
from obase.exceptions import (
    BudgetExceeded,
    CacheError,
    EnvLoadError,
    FSError,
    LockAcquisitionError,
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

# Sprint 11 — Notification Compliance (D2)
from obase.notification import NotificationComplianceFilter
from obase.orchestrator import Pipeline, RunState, Stage, run_pipeline
from obase.provider_registry import ProviderRegistry
from obase.rate_limit import RateLimiter, RateLimitRegistry

# Sprint 13 — Intraday Poll Scheduler (D1)
from obase.scheduler import IntradayPollScheduler
from obase.tool_registry import ToolMeta, ToolRegistry, ToolRegistryConflict, register_tool
from obase.trail import Trail, load_trail, query_trail
from obase.uuid7 import uuid7

__all__ = [
    "__version__",
    "bootstrap",
    "load_env",
    "uuid7",
    "Cache",
    "cached",
    "DistributedLock",
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
    "LockAcquisitionError",
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
    # cost_tracker shared types
    "CostBreakdown",
    "StepUsage",
    "convert_currency",
    # config loader
    "config_loader",
    # git
    "GitResult",
    "run_git",
    # lsp
    "LspClientManager",
    "LspServerHandle",
    # mcp_client
    "McpClientHandle",
    "McpClientRegistry",
]

# --- Stratum B3 obase submodules (v0.8.0) ---
# --- Stratum B1 obase submodules (v0.10.0) ---
# --- v0.11.0 persistence submodule ---
# v0.13.0 — sympy_runtime sandbox (M-0 batch)
# v0.15.6 — obase.gpu
from obase import (
    circuit_breaker,
    crypto,
    gpu,
    http,
    migration,
    observability,
    persistence,
    retry,
    sympy_runtime,
)
from obase import config as config_loader
from obase.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from obase.crypto import CryptoError, decrypt_token, derive_master_key, encrypt_token
from obase.git import GitResult, run_git
from obase.gpu import GpuScheduler, LocalModelProvider, ModelRegistry
from obase.http.dns_pinned_transport import (
    SSRFBlockedError,
    is_safe_ip,
    make_ssrf_safe_opener,
    resolve_and_check,
)
from obase.lsp import LspClientManager, LspServerHandle
from obase.mcp_client import McpClientHandle, McpClientRegistry
from obase.migration import MigrationResult, run_migration
from obase.observability.tracer import Span, Tracer, get_tracer
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
from obase.retry import RetryPolicy, retry_with_backoff
