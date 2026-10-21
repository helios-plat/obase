"""obase — Helios 生态横切基础设施库 (OBASE_SPEC v0.2)."""

from __future__ import annotations

__version__ = "0.31.0"

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
    # veya/3O — decision_logger
    "DecisionTrail",
    "begin_trail",
    "end_trail",
    "get_trail",
    "record_decision",
    # veya/3O — pseudo_anonymizer
    "PseudoAnonymizer",
    "pseudo_anonymize",
    "pseudo_anonymize_user",
    # veya/3O — browser_runner
    "BrowserError",
    "BrowserPageHandle",
    "BrowserRunner",
    # veya/3O — plugin_loader
    "PluginSandboxError",
    "PluginSpec",
    "load_plugin",
    "load_python_plugin",
    "load_wasm_plugin",
    # veya/3O — docker_pool（docker SDK 惰性加载，此处仅导出类定义）
    "ContainerSlot",
    "DockerPool",
    "DockerPoolError",
    # veya/3O — git_worktree
    "GitWorktreeError",
    "add_worktree",
    "list_worktrees",
    "prune_worktrees",
    "remove_worktree",
    # veya/3O — cognitive_store
    "MemoryChunk",
    "MemoryStore",
    "PgVectorMemoryStore",
    "SqliteMemoryStore",
    "make_memory_store",
    # veya/3O — version_store
    "SnapshotMeta",
    "VersionStore",
    "VersionStoreError",
    # veya/3O — cost_tracker ContextVar 全局计数器
    "bind_cost_tracker",
    "get_cost_tracker",
    "current_cost",
    "record_cost",
    "record_tokens",
    # 3O Paradigm Phase 4 — omodul 基座
    "OmodulBaseConfig",
    "DaemonBusProvider",
    "LocalEventBarrier",
    "JSONValue",
    "ResultDict",
    "ErrorDict",
    "ContextSlot",
    # 3O 范式内化 — Graft / OpenRSI / ReasoningBank 基建
    "GraphNode",
    "GraphRelation",
    "MarkdownGraphStore",
    "TrajectoryEntry",
    "TrajectoryLog",
    "append_trajectory",
    "load_trajectories",
    "LocalSandboxRunner",
    "DockerSandboxRunner",
    "MemoryItem",
    "MemoryBank",
    "cosine_similarity",
    # veya/3O — treesitter_indexer
    "AstFallbackIndexer",
    "CodeIndex",
    "SymbolIndexer",
    "SymbolRecord",
    "TreesitterIndexer",
    # veya/3O — hitl_signal_bus
    "ApprovalRequest",
    "HitlSignalBus",
    "bind_bus",
    "get_bus",
    "interrupted",
    "request_approval",
    "signal_interrupt",
    "wait_for_decision",
    # veya/3O — P1/P2 顶级 Agent 功能复现 (9)
    "ZeroMQBus",
    "ZeroMQBusError",
    "DurableLeaseQueue",
    "LeaseQueueError",
    "NETWORK_COMMANDS",
    "SandboxError",
    "SandboxResult",
    "ZeroEgressSandbox",
    "LiveKitError",
    "LiveKitRoom",
    "LiveKitWebRTC",
    "EnergyVAD",
    "VADError",
    "VADPipeline",
    "speech_segments",
    "SignedTokenSession",
    "TokenError",
    "TokenExpiredError",
    "TokenRevokedError",
    "MediaItem",
    "MediaScraper",
    "MediaScraperError",
    "extract_from_html",
    "DebouncedMemoryQueue",
    "HarnessBridge",
    "HarnessBridgeError",
    "HarnessAdapter",
    "HarnessAdapterError",
    "HarnessCapabilities",
    "HarnessRunResult",
    "HarnessRunRequest",
    "HarnessActivity",
    "ActivityKind",
    "HarnessErrorKind",
    "RESULT_STATUSES",
    "TERMINAL_STATUSES",
    "normalize_status",
    "apply_cleanup_outcome",
    "BaseCLIHarnessAdapter",
    "CodexHarnessAdapter",
    "ClaudeCodeHarnessAdapter",
    "OpenCodeHarnessAdapter",
    "register_harness_adapters",
    "discover_harness_capabilities",
    "A2AAgentAdapter",
    "A2AAdapterError",
    "A2ACapabilities",
    "A2AResult",
    "normalize_a2a_result",
    "ACPAgentAdapter",
    "ACPAdapterError",
    "ACPCapabilities",
    "ACPSession",
    "ChannelAdapter",
    "ChannelMessage",
    "BaseChannelAdapter",
    "TelegramChannelAdapter",
    "SlackChannelAdapter",
    "register_channel_adapters",
    # veya/3O — 前沿探索 (形式化验证)
    "SMTUnavailableError",
    "SMTSolverAdapter",
    "LeanFormalProver",
    "LeanProverError",
    # veya/3O — 终极前沿认知能力
    "KVCacheError",
    "KVCacheSharedMemory",
    # veya/3O — checkpoint_store
    "CheckpointStore",
    # veya/3O — browser_vision_runner
    "BrowserVisionRunner",
    "PageElement",
    "PageState",
    "VisionRunnerError",
    # veya/3O — ssrf_safe_network
    "SSRFSafeNetwork",
    "SSRFSafeNetworkError",
    # veya/3O — skills_registry
    "SkillsRegistry",
    "SkillsRegistryError",
    # veya/3O — adaptive_scraper (D0: Veya-lineage element = callable entry point)
    "adaptive_scraper",
    # veya/3O — dlt_pipeline_store
    "DltPipelineStore",
    "DltPipelineStoreError",
    # 3O Paradigm Phase 1 — obase 契约层 + 基础实现
    "IDaemon_Bus",
    "IEvent_Barrier",
    "IKV_Store",
    "ILLM_Client",
    "IVFS_Sandbox",
    "VFSProvider",
    "KVStoreProvider",
    "LocalVFS",
    "HttpLLMClient",
    "SQLiteKVStore",
    # ------------------------------------------------------------------
    # D0 canonical lineage reconciliation — Veya-lineage obase elements
    # ------------------------------------------------------------------
    "ActionDecision",
    "ActionEffect",
    "ActionRequest",
    "ActionVerdict",
    "AuditRecord",
    "PolicyRule",
    "redact_value",
    "AgentRegistry",
    "RegistryConflictError",
    "register_agent",
    "registry",
    "BrowserAdapter",
    "BrowserControlState",
    "BrowserProfile",
    "BrowserSessionHandle",
    "BrowserSessionState",
    "PlaywrightBrowserAdapter",
    "ComputerBackend",
    "ComputerHandle",
    "ComputerProfile",
    "ComputerState",
    "Event",
    "EventBus",
    "HierarchicalContextError",
    "HierarchicalContextStore",
    "RetrievalResult",
    "RetrievalStep",
    "TokenBudgetExceeded",
    "retrieve",
    "KnowledgeStore",
    "HoneypotAccessError",
    "LocalSandboxPool",
    "SandboxExecutionResult",
    "BreakerState",
    "get_breaker",
    "init_breaker",
    "reset_breaker",
    "AppendOnlyEventStore",
    "EVENT_SCHEMA_VERSION",
    "LoopStoreError",
    "QuotaTracker",
    "VerifyResult",
    "ensure_synthetic_data",
    "get_market_data_schema",
    "load_asset",
    "resolve_data_dir",
    "HttpMcpError",
    "StreamableHttpMcpClient",
    "StdioMcpClient",
    "StdioMcpError",
    "PluginRegistry",
    "HookNotFoundError",
    "HookRegistry",
    "default_hook_runner",
    "make_default_check_runner",
    "register_hook",
    "RunbookParseError",
    "load_runbook_yaml",
    "parse_runbook",
    "SecretsStore",
    "TeamRegistry",
    "make_message",
    "make_task",
    "make_team_config",
    "make_team_member",
    "VectorMemory",
    "WorkspaceInspector",
    "WorkspaceSnapshot",
    "ModelSpec",
    "Pricing",
    "ProviderCallRequest",
    "ProviderHealth",
    "ProviderSpec",
    "UsageRecord",
    "ProtocolFamily",
    "tool_kind_to_protocol_family",
    "CredentialRef",
    "Grant",
    "MCPServerSpec",
    "SecretRef",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolEffect",
    "ToolKind",
    "ToolSpec",
    "redact_payload",
    "CausalGraphError",
    "CausalGraphStore",
    "get_runtime_causal_store",
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
from obase.a2a_adapter import (
    A2AAdapterError,
    A2AAgentAdapter,
    A2ACapabilities,
    A2AResult,
    normalize_a2a_result,
)
from obase.acp_adapter import (
    ACPAdapterError,
    ACPAgentAdapter,
    ACPCapabilities,
    ACPSession,
)

# ---------------------------------------------------------------------------
# D0 canonical lineage reconciliation — Veya-lineage obase elements (2026-09)
# ---------------------------------------------------------------------------
from obase.action import (
    ActionDecision,
    ActionEffect,
    ActionRequest,
    ActionVerdict,
    AuditRecord,
    PolicyRule,
    redact_value,
)

# Veya/3O — adaptive_scraper
from obase.adaptive_scraper import adaptive_scraper
from obase.agent_registry import (
    AgentRegistry,
    RegistryConflictError,
    register_agent,
    registry,
)
from obase.base_types import ErrorDict, JSONValue, ResultDict
from obase.browser import (
    BrowserAdapter,
    BrowserControlState,
    BrowserProfile,
    BrowserSessionHandle,
    BrowserSessionState,
    PlaywrightBrowserAdapter,
)
from obase.browser_runner import BrowserError, BrowserPageHandle, BrowserRunner

# Veya/3O — browser_vision_runner
from obase.browser_vision_runner import (
    BrowserVisionRunner,
    PageElement,
    PageState,
    VisionRunnerError,
)
from obase.channel_adapter import (
    BaseChannelAdapter,
    ChannelAdapter,
    ChannelMessage,
    SlackChannelAdapter,
    TelegramChannelAdapter,
    register_channel_adapters,
)

# Veya/3O — checkpoint_store
from obase.checkpoint_store import CheckpointStore
from obase.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from obase.cognitive_store import (
    MemoryChunk,
    MemoryStore,
    PgVectorMemoryStore,
    SqliteMemoryStore,
    make_memory_store,
)
from obase.computer import ComputerBackend, ComputerHandle, ComputerProfile, ComputerState
from obase.context_vars import ContextSlot

# --- 3O Paradigm Phase 1 — obase 契约层 + 基础实现 ---
from obase.contracts import (
    IDaemon_Bus,
    IEvent_Barrier,
    IKV_Store,
    ILLM_Client,
    IVFS_Sandbox,
    KVStoreProvider,
    VFSProvider,
)
from obase.cost_tracker import (
    bind_cost_tracker,
    current_cost,
    get_cost_tracker,
    record_cost,
    record_tokens,
)
from obase.crypto import CryptoError, decrypt_token, derive_master_key, encrypt_token
from obase.daemon_bus import DaemonBusProvider
from obase.debounced_memory_queue import DebouncedMemoryQueue
from obase.decision_logger import (
    DecisionTrail,
    begin_trail,
    end_trail,
    get_trail,
    record_decision,
)

# Veya/3O — dlt_pipeline_store
from obase.dlt_pipeline_store import DltPipelineStore, DltPipelineStoreError
from obase.docker_pool import ContainerSlot, DockerPool, DockerPoolError
from obase.durable_lease_queue import DurableLeaseQueue, LeaseQueueError
from obase.event_barrier import LocalEventBarrier
from obase.event_bus import Event, EventBus
from obase.git import GitResult, run_git
from obase.git_worktree import (
    GitWorktreeError,
    add_worktree,
    list_worktrees,
    prune_worktrees,
    remove_worktree,
)
from obase.gpu import GpuScheduler, LocalModelProvider, ModelRegistry
from obase.graph_storage import GraphNode, GraphRelation, MarkdownGraphStore
from obase.harness_adapter import (
    RESULT_STATUSES,
    TERMINAL_STATUSES,
    ActivityKind,
    BaseCLIHarnessAdapter,
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    HarnessActivity,
    HarnessAdapter,
    HarnessAdapterError,
    HarnessCapabilities,
    HarnessErrorKind,
    HarnessRunRequest,
    HarnessRunResult,
    OpenCodeHarnessAdapter,
    apply_cleanup_outcome,
    discover_harness_capabilities,
    normalize_status,
    register_harness_adapters,
)
from obase.harness_bridge import HarnessBridge, HarnessBridgeError
from obase.hierarchical_context import (
    HierarchicalContextError,
    HierarchicalContextStore,
    RetrievalResult,
    RetrievalStep,
    TokenBudgetExceeded,
    retrieve,
)
from obase.hitl_signal_bus import (
    ApprovalRequest,
    HitlSignalBus,
    bind_bus,
    get_bus,
    interrupted,
    request_approval,
    signal_interrupt,
    wait_for_decision,
)
from obase.http.dns_pinned_transport import (
    SSRFBlockedError,
    is_safe_ip,
    make_ssrf_safe_opener,
    resolve_and_check,
)
from obase.knowledge_store import KnowledgeStore
from obase.kv_cache_shared_memory import KVCacheError, KVCacheSharedMemory
from obase.kv_store import SQLiteKVStore
from obase.lean_formal_prover import LeanFormalProver, LeanProverError
from obase.livekit_webrtc import LiveKitError, LiveKitRoom, LiveKitWebRTC
from obase.llm_client import HttpLLMClient
from obase.local_sandbox_pool import (
    HoneypotAccessError,
    LocalSandboxPool,
    SandboxExecutionResult,
)
from obase.loop_breaker import BreakerState, get_breaker, init_breaker, reset_breaker
from obase.loop_event_store import (
    EVENT_SCHEMA_VERSION,
    AppendOnlyEventStore,
    LoopStoreError,
    QuotaTracker,
    VerifyResult,
)
from obase.lsp import LspClientManager, LspServerHandle
from obase.market_data import (
    ensure_synthetic_data,
    get_market_data_schema,
    load_asset,
    resolve_data_dir,
)
from obase.mcp_client import McpClientHandle, McpClientRegistry
from obase.mcp_http import HttpMcpError, StreamableHttpMcpClient
from obase.mcp_stdio import StdioMcpClient, StdioMcpError
from obase.media_scraper import MediaItem, MediaScraper, MediaScraperError, extract_from_html
from obase.memory_bank import MemoryBank, MemoryItem, cosine_similarity
from obase.migration import MigrationResult, run_migration
from obase.observability.tracer import Span, Tracer, get_tracer
from obase.omodul_base_config import OmodulBaseConfig
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
from obase.plugin_loader import (
    PluginSandboxError,
    PluginSpec,
    load_plugin,
    load_python_plugin,
    load_wasm_plugin,
)
from obase.plugin_registry import PluginRegistry
from obase.provider_routing import (
    ModelSpec,
    Pricing,
    ProtocolFamily,
    ProviderCallRequest,
    ProviderHealth,
    ProviderSpec,
    UsageRecord,
    tool_kind_to_protocol_family,
)
from obase.pseudo_anonymizer import (
    PseudoAnonymizer,
    pseudo_anonymize,
    pseudo_anonymize_user,
)
from obase.retry import RetryPolicy, retry_with_backoff
from obase.runbook_loader import RunbookParseError, load_runbook_yaml, parse_runbook
from obase.runbook_runtime import (
    HookNotFoundError,
    HookRegistry,
    default_hook_runner,
    make_default_check_runner,
    register_hook,
)
from obase.sandbox_runner import DockerSandboxRunner, LocalSandboxRunner
from obase.secrets_store import SecretsStore
from obase.signed_token_session import (
    SignedTokenSession,
    TokenError,
    TokenExpiredError,
    TokenRevokedError,
)

# Veya/3O — skills_registry
from obase.skills_registry import SkillsRegistry, SkillsRegistryError
from obase.smt_solver_adapter import SMTSolverAdapter, SMTUnavailableError

# Veya/3O — ssrf_safe_network
from obase.ssrf_safe_network import SSRFSafeNetwork, SSRFSafeNetworkError
from obase.team_registry import (
    TeamRegistry,
    make_message,
    make_task,
    make_team_config,
    make_team_member,
)
from obase.tool_governance import (
    CredentialRef,
    Grant,
    MCPServerSpec,
    SecretRef,
    ToolCallRequest,
    ToolCallResult,
    ToolEffect,
    ToolKind,
    ToolSpec,
    redact_payload,
)
from obase.trajectory_logger import (
    TrajectoryEntry,
    TrajectoryLog,
    append_trajectory,
    load_trajectories,
)
from obase.treesitter_indexer import (
    AstFallbackIndexer,
    CodeIndex,
    SymbolIndexer,
    SymbolRecord,
    TreesitterIndexer,
)
from obase.vad_pipeline import EnergyVAD, VADError, VADPipeline, speech_segments
from obase.vector_memory import VectorMemory
from obase.versionstore import (
    SnapshotMeta,
    VersionStore,
    VersionStoreError,
)
from obase.vfs_sandbox import LocalVFS
from obase.workspace_snapshot import WorkspaceInspector, WorkspaceSnapshot
from obase.zero_egress_sandbox import (
    NETWORK_COMMANDS,
    SandboxError,
    SandboxResult,
    ZeroEgressSandbox,
)
from obase.zeromq_bus import ZeroMQBus, ZeroMQBusError

# causal_graph_store 依赖可选重依赖 networkx(本仓 pyproject 未声明)。
# 与 Veya pin 的 lazy 语义一致:缺失时该 element 视为不可解析(resolve_element -> None),
# 而不是让 `import obase` 整体失败。
try:  # pragma: no cover - 取决于环境是否安装 networkx
    from obase.causal_graph_store import (
        CausalGraphError,
        CausalGraphStore,
        get_runtime_causal_store,
    )
except ImportError:  # pragma: no cover
    pass

# TODO: Import daemon_bus and event_barrier implementations once finalized
