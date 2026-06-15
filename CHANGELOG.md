# Changelog

All notable changes to obase are documented in this file.

---

## [0.12.0] — 2026-06-12

### Added (batch-0: async CRUD + docker + cache + extras)

- **`obase.persistence.crud`** — 6 async CRUD primitives aligned to oprim.db_* semantics:
  `insert_one`, `read_one`, `update_one`, `soft_delete_one`, `query`, `write_one`.
  All use `PgPool` + `transaction`; no sync wrappers. (Owner D2 decision: pure async.)
- **`obase.docker`** — new subpackage migrating 24 docker_* functions + 5 aliases from
  `oprim._docker`. Submodules: `client` (models + helpers), `containers`, `images`,
  `networks`, `volumes`, `compose`. Uses `obase.exceptions`. `oprim._docker` NOT deleted
  (deprecated; removal in batch-4 / oprim v3.0.0).
- **`obase.cache.cache_invalidate`** — standalone Redis key invalidation function.
  Requires `obase[cache]`. `oprim.cache_invalidate` not deleted.
- **`alembic>=1.13`** added to core dependencies (was imported but missing from pyproject).

### Changed
- `pyproject.toml` version `0.11.0` → `0.12.0` (MINOR — additive only, zero breaking).
- New optional-dependency extras: `obase[docker]` (`docker>=7.0`), `obase[cache]` (`redis>=4.2`).

### Tests
- `tests/test_crud.py` — 19 tests (unit + PG integration) for all 6 CRUD functions.
- `tests/test_docker_module.py` — 37 mock-based tests covering all docker submodules.
- `tests/test_cache.py` extended — 4 new `TestCacheInvalidate` tests.

---

## [0.11.0] — 2026-06-05

### Added (persistence submodule)
- `obase.persistence` — new subpackage: PostgreSQL + pgvector connection pool and query
  primitives. Boundary: obase provides cross-cutting infrastructure; business schemas and
  thin service wrappers belong in consumer projects (AII, Stratum, Hevi, Tide, Aegis).
- `PgPool` — named asyncpg connection pool with class-level registry.
  `PgPool.create(name=..., dsn=..., enable_vector=True)` registers pgvector type codec per
  connection. `PgPool.get(name)` / `PgPool.list_pools()` / `pool.close()`.
- `transaction(pool)` — async context manager; commits on clean exit, rolls back on exception.
- `upsert_batch(pool, table, rows, conflict_columns, update_columns)` — batch
  `INSERT … ON CONFLICT` using asyncpg positional parameters; returns affected row count.
- `vector_search(pool, table, vector_column, query_vector, metric, top_k, …)` — pgvector
  HNSW nearest-neighbour retrieval; supports cosine / l2 / inner_product metrics with
  optional `filter_sql` and `select_columns`.
- `ensure_table` / `ensure_column` / `ensure_index` / `ensure_extension` — idempotent DDL
  helpers (`IF NOT EXISTS`); HNSW index WITH options supported.
- New dependencies: `asyncpg>=0.29`, `pgvector>=0.3`.
- 30 tests: 8 unit (mocked asyncpg) + 22 integration (real PG + pgvector; skip if unavailable).
- CI: `.github/workflows/ci.yml` adds `pgvector/pgvector:pg16` service for integration tests.

---

## [0.10.2] — 2026-06-05

### Fixed
- `dns_pinned_transport`: Narrowed Docker bridge allowlist from full `172.16.0.0/12` (too broad — 16M addresses) to only `172.17.0.0/16` (Docker default bridge — 65K addresses). Restored `172.16.0.0/12` to `_BLOCKED_NETWORKS`. Added `_ALLOWED_DOCKER_NETWORKS` checked before the blocklist. Non-default Docker subnets (`172.18.x`, `172.31.x`, etc.) remain blocked.

## [0.10.1] — 2026-06-05

### Fixed
- `dns_pinned_transport`: `DNSPinnedHTTPSHandler` rewritten with `_PinnedHTTPSConnection` subclass that overrides `connect()` using `ssl.create_default_context().wrap_socket(server_hostname=orig_hostname)` — eliminates use of `_server_hostname` private API, compatible with Python 3.14.
- `dns_pinned_transport`: Removed `172.16.0.0/12` from `_BLOCKED_NETWORKS` — Docker bridge is internal service mesh, not an SSRF attack surface. Metadata endpoint `169.254.0.0/16`, `10.0.0.0/8`, `192.168.0.0/16` remain blocked.
- `is_safe_ip`: switched from `is_private` attribute (which over-blocks Docker bridge) to explicit `_BLOCKED_NETWORKS` list check; loopback/link-local/multicast still use stdlib attributes.

### Tests
- Added 7 end-to-end integration tests (skip if network unavailable): DNS resolution for en.wikipedia.org / api.github.com / www.google.com passes; 127.x / 169.254.x / 192.168.x blocked; Docker bridge `172.17.0.2` allowed.

---

## [0.10.0] — 2026-06-04

### Added (Stratum B1)
- `obase.http.dns_pinned_transport` — DNS-pinned HTTP transport, SSRF/DNS-rebinding prevention (RFC1918 block)
- `obase.observability.tracer` — OpenTelemetry-compatible span tracer with in-memory noop default

---

## [0.9.0] - 2026-06-03 — B2+B3: edge-tts + DashScope wanxiang provider registration

### Added

- `obase.providers._tts.edge_tts` — `EdgeTTSProvider` (callable class) + `register()`: Microsoft Edge Read Aloud TTS, free cloud, 300+ voices, registers as `("tts", "edge_tts")` in ProviderRegistry
- `obase.providers._image.dashscope_wanxiang` — `DashScopeWanxiangProvider` + `register()`: DashScope wanxiang text-to-image via async task API (submit → poll → download), registers as `("image_gen", "wanxiang")` when `DASHSCOPE_API_KEY` present
- `obase.providers.register_default_providers()` — registers all built-in providers; silently skips missing deps/secrets
- `pyproject.toml`: `[project.optional-dependencies] tts = ["edge-tts>=6.1"]`

## [0.8.0] - 2026-06-01 — Stratum Batch 3: 5 new obase submodules

### Added — Stratum B3

- `obase.crypto` — AES-256-GCM token encryption + Argon2id key derivation (`encrypt_token`, `decrypt_token`, `derive_master_key`, `CryptoError`)
- `obase.migration` — Alembic wrapper (`run_migration`, `MigrationResult`); supports upgrade/downgrade/history/current/stamp
- `obase.circuit_breaker` — Thread-safe circuit breaker CLOSED/OPEN/HALF_OPEN state machine (`CircuitBreaker`, `CircuitBreakerOpenError`)
- `obase.retry` — Exponential backoff retry policy for async+sync functions (`RetryPolicy`)
- `obase.config` — Multi-path YAML config loader with deep merge + env var overrides (`load_config`, `watch_config`)
- `obase.mcp_client` — Deferred to v0.9.0 (complex protocol integration)

### Notes
- 34 new tests covering all 5 submodules
- alembic + sqlalchemy added to obase venv for obase.migration

---

## [Unreleased]

### Added — obase.oauth2_provider (v0.8.0)

- `obase.oauth2_provider.build_authorize_url(config, state)` → `str` — OAuth2 Authorization Code Flow Step 1. Builds authorization URL with query params: `response_type=code`, `client_id`, `redirect_uri`, `scope`, `state` (URL-encoded via `urllib.parse.urlencode`).
- `obase.oauth2_provider.exchange_code_for_token(*, config, code)` → `OAuth2Token` — Step 2. POST to `token_url` with `application/x-www-form-urlencoded`. Raises `OAuth2TokenExchangeError` when the response JSON has an `"error"` field; raises `OAuth2HTTPError` on HTTP 4xx/5xx without an OAuth2 error body.
- `obase.oauth2_provider.fetch_userinfo_raw(*, config, token)` → `dict[str, Any]` — Step 3. GET `userinfo_url` with `Authorization: Bearer`. Returns raw dict without normalizing fields. Raises `OAuth2UserInfoError` when `userinfo_url` is `None`; raises `OAuth2HTTPError` on HTTP failure.
- `obase.oauth2_provider.OAuth2ProviderConfig` — Pydantic v2 model: `name`, `client_id`, `client_secret`, `authorize_url`, `token_url`, `userinfo_url` (optional), `scope` (default `"openid email profile"`), `redirect_uri`.
- `obase.oauth2_provider.OAuth2Token` — Pydantic v2 model: `access_token`, `refresh_token`, `expires_in`, `token_type`, `scope`, `id_token` (all optional except `access_token`).
- `obase.oauth2_provider.OAuth2Error` — base exception; subclasses: `OAuth2TokenExchangeError`, `OAuth2UserInfoError`, `OAuth2HTTPError`.
- HTTP via `httpx.AsyncClient` (already a declared dependency at `>=0.27`).
- 9 tests: authorize URL params / state URL-encoding / token exchange success / OAuth2 error / HTTP 500 error / userinfo success / no-URL error / HTTP 401 error / token model optional fields.

### Added — obase.webhook.sign_payload (v0.7.0)

- obase 0.7.0: added obase.webhook.sign_payload (HMAC webhook signing, GitHub/Stripe-style)
- `obase.webhook.sign_payload(*, payload, secret, algo)` → `str` — HMAC-SHA256/SHA512 signing. Accepts `dict` (JSON-serialized, sort_keys=True) or raw `bytes`. Enforces `secret ≥ 32 bytes`. `default=str` handles non-serializable values (e.g. datetime). Returns lowercase hex digest.
- `obase.webhook.WebhookSignError` — raised on short secret, unsupported algo, or non-bytes/dict payload.
- 9 tests: dict+sha256 / bytes+sha256 / sha512 / short-secret / datetime-default-str / deterministic / different-secret / sort-keys / unsupported-algo.

### Added — obase.notify + obase.audit (v0.6.0)

- `obase.notify.telegram_send(request: TelegramRequest) -> TelegramResult` — Async Telegram Bot API sendMessage helper. Returns typed `TelegramResult(ok, message_id, error)` — network/HTTP errors captured as `ok=False`, never raised. `TelegramRequest` is a Pydantic model (bot_token, chat_id, text, parse_mode, disable_notification).
- `obase.audit.format_audit_entry(*, actor, action, resource_type, resource_id, detail)` — Pure sync factory returning a validated `AuditEntry` (Pydantic) with uuid7 id and UTC timestamp. No side effects.
- `obase.audit.AuditWriter` — `runtime_checkable Protocol` with `async write(entry: AuditEntry) -> None`. obase ships the contract; implementations live in consuming services.
- Dependency: `httpx>=0.27` added to `pyproject.toml` (was used by telegram_client but previously undeclared).
- notify: 7 tests (request validation / success / HTTP error / connection error / payload fields / missing message_id / URL token).
- audit: 11 tests (entry fields / uuid7 format / UTC timestamp / default detail / unique ids / nested detail / entry validation / Protocol isinstance / wrong method / concrete writer call).

### Added — obase.text.fuzzy_match (v0.5.0)

- `obase.text.fuzzy_match(*, query, candidates, threshold, top_k)` → `list[FuzzyMatchResult]` — Fuzzy string matching backed by `rapidfuzz.fuzz.WRatio`. Returns candidates scoring ≥ threshold (0.0–1.0), sorted by score descending, capped at top_k results. Supports Unicode/Chinese. Raises `FuzzyMatchError` on invalid arguments.
- `obase.text.FuzzyMatchResult` — Pydantic model with `candidate: str` and `score: float` fields.
- `obase.text.FuzzyMatchError` — Raised on invalid threshold (outside [0.0, 1.0]) or top_k < 1.
- Dependency: `rapidfuzz>=3.0` added to `pyproject.toml`.
- 12 tests across exact/no-match/threshold boundary/multi-candidate sorting/Unicode Chinese/invalid-args cases.

### Fixed

- fix: align __init__ version with pyproject (0.4.0)

### Added — Aegis Step 15 B1 — obase.auth Argon2 + JWT HS256

- `obase.auth.argon2_hash(*, password)` → `str` — Argon2id hash (OWASP recommended defaults: time_cost=3, memory_cost=64MB). Raises `ArgonHashError` on library failure.
- `obase.auth.argon2_verify(*, password, hash)` → `bool` — Returns `False` on mismatch, raises `ArgonHashError` on invalid hash format (distinguishes wrong-password from tampered-hash-field).
- `obase.auth.jwt_sign_hs256(*, payload, secret, expires_in_seconds)` → `str` — HS256 JWT signing. Enforces `secret ≥ 32 bytes`. Auto-adds `iat`; adds `exp` when `expires_in_seconds` is not `None`. Raises `JWTSignError`.
- `obase.auth.jwt_verify_hs256(*, token, secret, check_exp)` → `dict` — HS256 JWT decode. Algorithm locked to `HS256` (rejects HS512 etc.). `check_exp=False` for debug use. Raises `JWTVerifyError`.
- Dependency: `argon2-cffi>=23.0` added to `pyproject.toml` (`pyjwt>=2.8` already present).
- 25 tests, 100% line coverage on new files.

### Added — P7-B1 — MCP Server Facade

- `obase.mcp_server` — MCP (Model Context Protocol) FastMCP Facade.
  - `SkillDef` — Pydantic model for ergonomic MCP Tool definition.
    - Fields: `name`, `description`, `input_schema`, `output_schema` (optional), `handler`.
    - `alias_generator=to_camel` → serialises as `inputSchema`/`outputSchema` on MCP wire.
  - `MCPServer` — Fully-encapsulated FastMCP Facade.
    - `__init__(*, name, version)` — Reports name + version in MCP capability negotiation.
    - `register_skill(skill_def)` — Registers a `SkillDef` as a FastMCP tool.
    - `serve_stdio()` — stdio transport (Claude Desktop, etc.).
    - `serve_streamable_http(host, port)` — Streamable HTTP transport (MCP 2025-03+).
  - `MCPServerError` / `MCPProtocolError` — Error hierarchy.
  - Dependency: `mcp>=1.27` added to `pyproject.toml`.
  - Test coverage: 11 tests, 100% line coverage.

### Added — P6-B1 — Template Module

- `obase.template` — YAML prompt template loading, validation, and rendering.
  - `load(path)` — Load a Template from YAML file.
  - `validate(template)` — Re-validate a Template instance.
  - `render_prompt(template, vars)` — Substitute `{placeholder}` variables in system_prompt.
  - `Template` — Pydantic model with name (no whitespace), version (semver), system_prompt, metadata.
  - `TemplateError` / `TemplateValidationError` — Error hierarchy.

---

## [0.3.0] - 2026-05-24

### Added — Sprint 11 — Notification Compliance Filter (D2)

- `obase.notification.NotificationComplianceFilter` — Quiet hours, disclaimer injection, blocked keywords.
  - `register_quiet_hours(start_time, end_time, timezone, scope)` — Block non-critical during quiet hours.
  - `register_disclaimer_template(channel, template)` — Inject disclaimer into message content.
  - `register_blocked_keywords(keywords)` — Block messages containing keywords.
  - `filter(message)` — Apply all rules; returns None if blocked.

---

## v0.3.0 - 2026-05-24

**Hevi Batch 1 — obase v0.3.0**

### Added
- `obase.ffmpeg` submodule: Unified FFmpeg subprocess wrapper.
  - `run(args, timeout_s, cwd, expected_output)` — async FFmpeg execution with timeout, stderr capture, and output validation.
  - `FFmpegError` — raised on non-zero exit, timeout, or missing expected output.
  - `FFmpegNotFoundError` — raised when ffmpeg binary is not on PATH.
  - Example: `stderr = await run(args=["-i", "in.mp4", "-c", "copy", "out.mp4"])`
- `obase.versionstore` submodule: JSONL append-only version store.
  - `jsonl_append(path, entry, create_parents)` — append a dict as one JSON line.
  - `jsonl_read(path, skip_malformed)` — read all entries from JSONL file.
  - `jsonl_latest(path, by_key)` — get latest entry by key (last-entry-wins).
  - Example: `await jsonl_append(path=Path("log.jsonl"), entry={"id": "a", "v": 1})`

---

## v0.2.0 - 2026-05-24

**BATCH 19 — obase v0.2.0**

### Added
- `obase.uuid7`: RFC 9562 UUIDv7 implementation (36 characters, chronological).
- `obase.auth` submodule: Authentication utilities.
  - `jwt_create` / `jwt_verify` using `pyjwt`.
  - `bcrypt_hash` / `bcrypt_verify` using `bcrypt`.
  - `totp_secret_generate` / `totp_qr_url` / `totp_verify` using `pyotp` and `qrcode`.
- `obase.secrets` submodule: Secrets management.
  - `SecretsBackend` protocol and registry.
  - `EnvFileBackend` for reading secrets from `.env` files.
  - `get_secret` / `set_secret` global APIs.

---

## v0.1.0 - 2026-05-18

**obase 第一个稳定版本**(干净版,移除 v0.1 实施期间临时引入的 Stratum-native 污染)。

### Modules (8 个,按 OBASE_SPEC v0.2)
- **orchestrator**: 流水线 stage 调度 + 失败重试 + 暂停/恢复(含 PauseRequested + resume_data, PB6)
- **trail**: 决策日志落盘 + 查询(jsonl + query_trail 跨 run 查询)
- **cost_tracker**: 多供应商 API 成本累加 + 上限保护(含 strict_pricing PB3)
- **fs**: 工作目录管理 + 跨平台路径(WSL2 / Windows / macOS)
- **cache**: 输入复用 + 失败重跑跳过(filesystem backend, Redis 留 v0.3)
- **rate_limit**: Token Bucket 限流 + 多 provider 池
- **provider_registry**: 运行时 provider 注册与切换
- **bootstrap**: Layer 4 入口一键初始化(含 load_env PB4: 行内注释剥离 / 空值不注入 / URL 校验)

### Quality
- 134 tests passed, 99% coverage
- ruff clean, mypy strict 通过
- 4 个 example 可运行(basic_pipeline / with_human_gate / multi_provider / bootstrap_minimal)
- 2 个 doc(migration_from_hevi_base / design_principles)

### PB 验收(OBASE_SPEC v0.2 §5.2 全部通过)
- PB1: Stage 双轨设计(input_keys/output_keys Optional 默认 None,hevi 兼容 + 新项目强校验)
- PB3: cost_tracker strict_pricing 控制(漏定价默认抛 PricingNotConfiguredError)
- PB4: load_env 行内注释剥离 + 空值不注入 + URL 校验
- PB5: 失败不静默全模块测试
- PB6: PauseRequested 完整定义 + resume_data + paused_at_stage

### Cleanup(v0.1 实施收尾)
本次发布移除 v0.1 实施期间(commit 244c3f6 / 8cf415a)临时引入的 Stratum-native 污染,使 obase 完全符合 OBASE_SPEC v0.2 §1.1 横切原则:

**删除文件**(违反 §1.1 横切原则,Stratum 业务假设不应进 obase):
- `obase/errors.py`(Stratum 异常,跟 obase.exceptions 平行重叠)
- `obase/logging.py`(Stratum logging 包装,obase 用 structlog)
- `obase/config.py`(Stratum config 系统,obase 用 obase.fs + load_env)

**删除 cost_tracker.py 模块级 API**(违反 §1.4 DI 原则 + §1.7 失败不静默 + 多 run 隔离):
- `track()` / `total_cost()` / `get_records()` / `reset()` 模块级函数
- 支撑全局状态的 `CostRecord` dataclass / `_records` / `_lock`
- 保留 `CostTracker` class 完整 API(record / check_budget / summary)

**清理涉及测试**:
- `tests/test_obase.py` 整个删除(含 17 个污染测试: TestErrors / TestLogging / TestConfig)
- cost_tracker 模块级函数相关测试 6 个删除

### Compatibility
- **hevi cut-over 验证通过**: hevi v0.0.x cut-over(commit 7bc0212)使用 obase 主路径(CostTracker class / bootstrap / 等),205 non-integration tests 通过,完全不受 cleanup 影响
- **Stratum 后续集成**: 按 OBASE_SPEC v0.2 §1.1 横切原则,Stratum 业务假设应在 stratum 仓库内或通过 oskill/omodul 正式贡献,不进 obase

### Known Issues(留 v0.1.1)
- `OBaseRegistryConflict` 异常类定义在 `provider_registry.py` 而非 `exceptions.py`,轻微架构 inconsistency,不阻塞使用,留 v0.1.1 微调

## [0.4.0] - 2026-05-25

### Added — Sprint 13 — Intraday Poll Scheduler (D1)

- `obase.scheduler.IntradayPollScheduler` — Schedule handlers at intraday time windows with exception isolation.

## [0.12.2] — 2026-06-13
### Added
- `obase.lsp`: LspServerHandle Protocol + LspClientManager (lsp_* oprim 的 server handle)
- `obase.mcp_client`: McpClientHandle Protocol + McpClientRegistry (mcp_* oprim 的 client handle)

## [0.12.2] — 2026-06-13
### Added
- `obase.lsp`: LspServerHandle Protocol + LspClientManager (lsp_* oprim 的 server handle)
- `obase.mcp_client`: McpClientHandle Protocol + McpClientRegistry (mcp_* oprim 的 client handle)

## [0.15.1] — 2026-06-13
### Added
- obase.git: run_git + GitResult (git subprocess 底座，供 git_* oprim 使用)

## [0.15.3] — 2026-06-14
### Added
- ProviderRegistry: image_gen 分类 (register_image_gen / image_gen / has / register 兼容旧 API)
- ImageGenCaller Protocol
### Fixed
- 修复 omodul/illustration_agent + oprim/image_generate + obase/providers/dashscope_wanxiang
  因 image_gen 分类缺失导致的 AttributeError
