"""obase — Helios 生态横切基础设施库 (OBASE_SPEC v0.2).

Lazy-import variant (backward compatible): core submodules that only depend on
stdlib / light deps (structlog, yaml) are imported eagerly; every submodule that
pulls heavy third-party dependencies (rapidfuzz, anthropic, asyncpg, mcp, ...)
is resolved lazily via module-level ``__getattr__`` so that
``import obase; from obase.cache import Cache`` works without installing the
full dependency surface. All previously-available names keep working.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

__version__ = "0.31.0"

# --- core imports: stdlib-only or light deps (structlog, yaml, httpx, pydantic) ---
from obase.bootstrap import bootstrap, load_env
from obase.action import (
    ActionDecision,
    ActionEffect,
    ActionRequest,
    ActionVerdict,
    AuditRecord,
    PolicyRule,
    redact_value,
)
from obase.cache import Cache, DistributedLock, cached
from obase.browser import (
    BrowserAdapter,
    BrowserControlState,
    BrowserProfile,
    BrowserSessionHandle,
    BrowserSessionState,
    PlaywrightBrowserAdapter,
)
from obase.computer import ComputerHandle, ComputerProfile
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
from obase.git import GitResult, run_git
from obase.hierarchical_context import (
    HierarchicalContextError,
    HierarchicalContextStore,
    RetrievalResult,
    RetrievalStep,
    TokenBudgetExceeded,
    retrieve,
)
from obase.loop_event_store import (
    EVENT_SCHEMA_VERSION,
    AppendOnlyEventStore,
    LoopStoreError,
    QuotaTracker,
    VerifyResult,
)
from obase.notification import NotificationComplianceFilter
from obase.orchestrator import (
    Check,
    CheckType,
    Edge,
    FileRunStateBackend,
    Node,
    Pipeline,
    Runbook,
    RunEntry,
    RunState,
    RunStateBackend,
    SqliteRunStateBackend,
    Stage,
    project_run_trajectory,
    register_dynamic_check,
    run_pipeline,
    runbook_current,
    runbook_goto,
    runbook_history,
    start_runbook,
)
from obase.provider_registry import ProviderRegistry
from obase.provider_routing import (
    ModelSpec,
    Pricing,
    ProviderCallRequest,
    ProviderHealth,
    ProviderSpec,
    UsageRecord,
)
from obase.rate_limit import RateLimiter, RateLimitRegistry
from obase.runbook_loader import RunbookParseError, load_runbook_yaml, parse_runbook
from obase.runbook_runtime import (
    HookNotFoundError,
    HookRegistry,
    default_hook_runner,
    make_default_check_runner,
    register_hook,
)
from obase.scheduler import IntradayPollScheduler
from obase.tool_registry import ToolMeta, ToolRegistry, ToolRegistryConflict, register_tool
from obase.trail import Trail, load_trail, query_trail
from obase.uuid7 import uuid7

__all__ = [
    "__version__",
    "bootstrap",
    "load_env",
    "ActionDecision",
    "ActionEffect",
    "ActionRequest",
    "ActionVerdict",
    "AuditRecord",
    "PolicyRule",
    "redact_value",
    "ComputerHandle",
    "ComputerProfile",
    "BrowserAdapter",
    "BrowserControlState",
    "BrowserProfile",
    "BrowserSessionHandle",
    "BrowserSessionState",
    "PlaywrightBrowserAdapter",
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
    "HierarchicalContextError",
    "HierarchicalContextStore",
    "RetrievalResult",
    "RetrievalStep",
    "TokenBudgetExceeded",
    "retrieve",
    "Pipeline",
    "RunState",
    "RunStateBackend",
    "FileRunStateBackend",
    "SqliteRunStateBackend",
    "Stage",
    "run_pipeline",
    "Check",
    "CheckType",
    "Edge",
    "Node",
    "Runbook",
    "RunEntry",
    "project_run_trajectory",
    "register_dynamic_check",
    "runbook_current",
    "runbook_goto",
    "runbook_history",
    "start_runbook",
    "HookNotFoundError",
    "HookRegistry",
    "default_hook_runner",
    "make_default_check_runner",
    "register_hook",
    "RunbookParseError",
    "load_runbook_yaml",
    "parse_runbook",
    "ProviderRegistry",
    "ModelSpec",
    "Pricing",
    "ProviderCallRequest",
    "ProviderHealth",
    "ProviderSpec",
    "UsageRecord",
    "RateLimitRegistry",
    "RateLimiter",
    "ToolMeta",
    "ToolRegistry",
    "ToolRegistryConflict",
    "register_tool",
    "Trail",
    "load_trail",
    "query_trail",
    "AppendOnlyEventStore",
    "QuotaTracker",
    "LoopStoreError",
    "VerifyResult",
    "EVENT_SCHEMA_VERSION",
    "NotificationComplianceFilter",
    "IntradayPollScheduler",
    "GitResult",
    "run_git",
]

# --- optional submodules (heavy third-party deps) — lazy via __getattr__ ---
_OPTIONAL_SUBMODULES = (
    "audit",
    "circuit_breaker",
    "loop_breaker",
    "sandbox",
    "token_counter",
    "cocoindex",
    "graph_store",
    "veya_workspace",
    "workspace_snapshot",
    "intent_brief",
    "collector_base",
    "config",
    "crypto",
    "email_client",
    "environ_processor_base",
    "event_bus",
    "gpu",
    "http",
    "llm",
    "lsp",
    "mcp_client",
    "migration",
    "notification",
    "notify",
    "observability",
    "ohlcv_store",
    "market_data",
    "persistence",
    "price_store",
    "rag_index_store",
    "retry",
    "sympy_runtime",
    "secrets_store",
    "task_store",
    "telegram_client",
    "text",
    "ts_writer",
    "webhook",
)

# names that used to be eagerly exported from optional submodules
_OPTIONAL_EXPORTS: dict[str, tuple[str, tuple[str, ...]]] = {
    # attr -> (module, names to pull from it)
    "RetryPolicy": ("retry", ("RetryPolicy",)),
    "retry_with_backoff": ("retry", ("retry_with_backoff",)),
    "CircuitBreaker": ("circuit_breaker", ("CircuitBreaker",)),
    "CircuitBreakerOpenError": ("circuit_breaker", ("CircuitBreakerOpenError",)),
    "PathJail": ("sandbox.path_jail", ("PathJail",)),
    "ProcessJail": ("sandbox.process_jail", ("ProcessJail",)),
    "BreakerState": ("loop_breaker", ("BreakerState",)),
    "get_breaker": ("loop_breaker", ("get_breaker",)),
    "init_breaker": ("loop_breaker", ("init_breaker",)),
    "reset_breaker": ("loop_breaker", ("reset_breaker",)),
    "token_counter": ("token_counter", ("token_counter",)),
    "ASTParser": ("cocoindex.parser", ("ASTParser",)),
    "FactNode": ("graph_store.models", ("FactNode",)),
    "GraphDBPool": ("graph_store.models", ("GraphDBPool",)),
    "SpecKitPaths": ("veya_workspace", ("SpecKitPaths",)),
    "TaskNode": ("veya_workspace", ("TaskNode",)),
    "WorkspaceSnapshot": ("workspace_snapshot", ("WorkspaceSnapshot",)),
    "WorkspaceInspector": ("workspace_snapshot", ("WorkspaceInspector",)),
    "IntentBrief": ("intent_brief", ("IntentBrief",)),
    "CryptoError": ("crypto", ("CryptoError",)),
    "encrypt_token": ("crypto", ("encrypt_token",)),
    "decrypt_token": ("crypto", ("decrypt_token",)),
    "derive_master_key": ("crypto", ("derive_master_key",)),
    "MigrationResult": ("migration", ("MigrationResult",)),
    "run_migration": ("migration", ("run_migration",)),
    "SSRFBlockedError": ("http", ("SSRFBlockedError",)),
    "is_safe_ip": ("http", ("is_safe_ip",)),
    "make_ssrf_safe_opener": ("http", ("make_ssrf_safe_opener",)),
    "resolve_and_check": ("http", ("resolve_and_check",)),
    "Span": ("observability", ("Span",)),
    "Tracer": ("observability", ("Tracer",)),
    "get_tracer": ("observability", ("get_tracer",)),
    "PgPool": ("persistence", ("PgPool",)),
    "VectorMetric": ("persistence", ("VectorMetric",)),
    "ensure_column": ("persistence", ("ensure_column",)),
    "ensure_extension": ("persistence", ("ensure_extension",)),
    "ensure_index": ("persistence", ("ensure_index",)),
    "ensure_table": ("persistence", ("ensure_table",)),
    "transaction": ("persistence", ("transaction",)),
    "upsert_batch": ("persistence", ("upsert_batch",)),
    "vector_search": ("persistence", ("vector_search",)),
    "GpuScheduler": ("gpu", ("GpuScheduler",)),
    "ModelRegistry": ("gpu", ("ModelRegistry",)),
    "LocalModelProvider": ("gpu", ("LocalModelProvider",)),
    "LspClientManager": ("lsp", ("LspClientManager",)),
    "LspServerHandle": ("lsp", ("LspServerHandle",)),
    "McpClientHandle": ("mcp_client", ("McpClientHandle",)),
    "McpClientRegistry": ("mcp_client", ("McpClientRegistry",)),
    "StdioMcpClient": ("mcp_stdio", ("StdioMcpClient",)),
    "StdioMcpError": ("mcp_stdio", ("StdioMcpError",)),
    "StreamableHttpMcpClient": ("mcp_http", ("StreamableHttpMcpClient",)),
    "HttpMcpError": ("mcp_http", ("HttpMcpError",)),
    "config_loader": ("config", ("config_loader",)),
    # --- heavy-SDK real implementations ---
    "CheckpointStore": ("checkpoint_store", ("CheckpointStore",)),
    "adaptive_scraper": ("adaptive_scraper", ("adaptive_scraper",)),
    "agent_registry": (
        "agent_registry",
        ("AgentRegistry", "registry", "register_agent", "register_tool"),
    ),
    "VectorMemory": ("vector_memory", ("VectorMemory",)),
}

# submodule aliases (e.g. `obase.text` was previously `from obase import text`)
_SUBMODULE_ALIASES = {
    "text": "text",
    "notify": "notify",
    "audit": "audit",
    "webhook": "webhook",
    "collector_base": "collector_base",
    "email_client": "email_client",
    "environ_processor_base": "environ_processor_base",
    "event_bus": "event_bus",
    "secrets_store": "secrets_store",
    "task_store": "task_store",
    "market_data": "market_data",
    "rag_index_store": "rag_index_store",
    "ohlcv_store": "ohlcv_store",
    "price_store": "price_store",
    "symbol_normalize": "symbol_normalize",
    "telegram_client": "telegram_client",
    "ts_writer": "ts_writer",
    "http": "http",
    "observability": "observability",
    "persistence": "persistence",
    "sympy_runtime": "sympy_runtime",
    "gpu": "gpu",
    "crypto": "crypto",
    "migration": "migration",
    "circuit_breaker": "circuit_breaker",
    "loop_breaker": "loop_breaker",
    "sandbox": "sandbox",
    "token_counter": "token_counter",
    "cocoindex": "cocoindex",
    "graph_store": "graph_store",
    "veya_workspace": "veya_workspace",
    "workspace_snapshot": "workspace_snapshot",
    "intent_brief": "intent_brief",
    "retry": "retry",
    "llm": "llm",
    "lsp": "lsp",
    "mcp_client": "mcp_client",
}

_log = logging.getLogger("obase")


def __getattr__(name: str) -> Any:
    """Lazily resolve optional submodules / exports (PEP 562)."""
    if name in _SUBMODULE_ALIASES:
        return importlib.import_module(f"obase.{_SUBMODULE_ALIASES[name]}")
    if name in _OPTIONAL_EXPORTS:
        module_name, names = _OPTIONAL_EXPORTS[name]
        module = importlib.import_module(f"obase.{module_name}")
        for attr in names:
            if hasattr(module, attr):
                return getattr(module, attr)
    raise AttributeError(f"module 'obase' has no attribute {name!r}")


# ── Phase 2: 认知因果 / 蜜罐博弈 基础设施 ──────────────────────────
from .causal_graph_store import (  # noqa: F401
    CausalGraphError,
    CausalGraphStore,
    get_runtime_causal_store,
)
from .debounced_memory_queue import DebouncedMemoryQueue  # noqa: F401
from .knowledge_store import KnowledgeStore  # noqa: F401
from .local_sandbox_pool import (  # noqa: F401
    HoneypotAccessError,
    LocalSandboxPool,
    SandboxExecutionResult,
)
from .plugin_registry import PluginRegistry  # noqa: F401
from .support_bundle_pack import support_bundle_pack  # noqa: F401
from .team_registry import (  # noqa: F401
    TeamRegistry,
    make_message,
    make_task,
    make_team_config,
    make_team_member,
)
