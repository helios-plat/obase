# Changelog

All notable changes to obase are documented in this file.

---

## [Unreleased]

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
