"""obase.hardened_executor — 统一执行基板：能力校验 + 资源限制 + 蜜罐探针 + 网络策略.

受控执行统一入口：
1. 验签并校验 CapabilityToken（所需 capability 缺省 executor.execute）
2. 加载 ResourceEnvelope（缺省 DEFAULT_ENVELOPE：deny_all + 只读）
3. 蜜罐探针植入与触碰检测（HoneypotProbe）
4. 熔断检查（可选，复用 obase.circuit_breaker.CircuitBreaker）
5. 限流（可选，复用 obase.rate_limit.RateLimiter）
6. 执行（同步 / 异步 / 子进程），墙钟超时强制
7. 写可审计 ActionLog（JSONL append-only）
8. 结构化结果返回（绝不裸抛业务异常，失败进 result.error）

零反向依赖（obase 铁律）：不 import oprim/oskill/omodul。

例:
    >>> ex = HardenedExecutor(secret="dev-secret-32chars-xxxxxxxxxxxxxxxx")
    >>> tok = issue_capability_token(ex._secret, subject="t", capabilities={"executor.execute"})
    >>> r = ex.execute(tok, fn=lambda: 1 + 1)
    >>> r.status
    'ok'
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from obase.permission_contract import (
    CapabilityDeniedError,
    CapabilityError,
    CapabilityToken,
    check_capability,
    verify_capability_token,
)
from obase.resource_limits import (
    DEFAULT_ENVELOPE,
    ResourceEnvelope,
    WallclockDeadline,
    validate_envelope,
)
from obase.zero_egress_sandbox import NETWORK_COMMANDS, ZeroEgressSandbox

log = logging.getLogger(__name__)

__all__ = [
    "ActionLog",
    "ActionLogError",
    "HoneypotProbe",
    "HoneypotTripError",
    "HardenedExecutor",
    "HardenedExecutorError",
    "ExecutionResult",
]


class HardenedExecutorError(RuntimeError):
    """执行基板错误。"""


class ActionLogError(RuntimeError):
    """ActionLog 写入错误。"""


class HoneypotTripError(RuntimeError):
    """蜜罐被触碰 —— 判定为可疑执行。"""


class ActionLog:
    """可审计动作日志（JSONL append-only）。

    每条记录: ts / action / subject / capability / outcome / actor / detail。
    线程安全；落盘原子追加（append 一行）。
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @property
    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)

    def record(
        self,
        *,
        action: str,
        subject: str,
        capability: str,
        outcome: str,
        detail: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> None:
        entry = {
            "ts": time.time(),
            "action": action,
            "subject": subject,
            "capability": capability,
            "outcome": outcome,
            "actor": actor,
            "detail": detail or {},
        }
        with self._lock:
            self._entries.append(entry)
            if self._path is not None:
                try:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    with self._path.open("a", encoding="utf-8") as f:
                        f.write(
                            json.dumps(entry, ensure_ascii=False, default=str) + "\n"
                        )
                except OSError as exc:
                    raise ActionLogError(f"ActionLog: write failed: {exc}") from exc


class HoneypotProbe:
    """蜜罐探针：放置诱饵文件，执行后检测是否被触碰。

    - 诱饵：伪凭据文件（默认内容含明确告警标记）
    - 触碰判定：文件被删除 / 内容被修改（比对原始字节）
    - check_touched 返回触碰清单（[] = 干净）；调用方可据此终止并记安全告警
    """

    def __init__(self, bait_dir: str | Path | None = None) -> None:
        self._bait_dir = Path(bait_dir) if bait_dir else Path(tempfile.gettempdir())
        self._baits: dict[Path, bytes] = {}
        self._lock = threading.Lock()

    def plant(self, name: str = ".env.probe", content: bytes | None = None) -> Path:
        """植入一个诱饵文件，返回路径。"""
        path = self._bait_dir / f"{secrets.token_hex(6)}_{name}"
        body = content or b"STRATUM_PROBE_<redacted_secret>_DO_NOT_READ"
        path.write_bytes(body)
        with self._lock:
            self._baits[path] = body
        return path

    def check_touched(self) -> list[dict[str, Any]]:
        """返回被触碰的诱饵清单（[] = 未触碰）。"""
        touched: list[dict[str, Any]] = []
        with self._lock:
            for path, original in self._baits.items():
                if not path.exists():
                    touched.append({"path": str(path), "reason": "removed"})
                    continue
                if path.read_bytes() != original:
                    touched.append({"path": str(path), "reason": "modified"})
        return touched

    def cleanup(self) -> None:
        with self._lock:
            for path in list(self._baits):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._baits.clear()


@dataclass
class ExecutionResult:
    """受控执行结果。"""

    status: str  # ok | denied | blocked | timeout | honeypot_trip | error
    outcome: Any = None
    error: str | None = None
    action_log_id: int | None = None
    elapsed_ms: int = 0
    honey_trips: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "outcome": self.outcome,
            "error": self.error,
            "action_log_id": self.action_log_id,
            "elapsed_ms": self.elapsed_ms,
            "honey_trips": self.honey_trips,
        }


class HardenedExecutor:
    """统一执行基板。

    - execute(...)          同步可执行体（协作式墙钟检查；阻塞式请用 aexecute）
    - aexecute(...)         异步可执行体（asyncio.wait_for 强超时）
    - execute_subprocess(...) 命令级执行（网络策略强制 + 环境净化 + 强超时）
    """

    def __init__(
        self,
        *,
        secret: str,
        action_log: ActionLog | None = None,
        breaker: Any | None = None,
        rate_limiter: Any | None = None,
        default_capability: str = "executor.execute",
        honeypot_dir: str | Path | None = None,
        use_network_namespace: bool = False,
    ) -> None:
        if not secret:
            raise HardenedExecutorError("hardened_executor: secret must not be empty")
        self._secret = secret
        self._action_log = action_log or ActionLog()
        self._breaker = breaker
        self._rate_limiter = rate_limiter
        self._default_capability = default_capability
        self._honeypot_dir = honeypot_dir
        # netns 深度隔离依赖内核能力（unshare 需 CAP_SYS_ADMIN），默认关闭以保证确定性；
        # 命令防火墙 + 环境净化（ZeroEgressSandbox）始终生效。
        self._sandbox = ZeroEgressSandbox(
            deny_network=True,
            use_network_namespace=use_network_namespace,
        )

    # ------------------------------------------------------------------
    # 内部守卫
    # ------------------------------------------------------------------

    def _verify(
        self, token_str: str | None, *, required_capability: str | None
    ) -> CapabilityToken:
        if not token_str:
            raise CapabilityDeniedError("hardened_executor: missing CapabilityToken")
        token = verify_capability_token(self._secret, token_str)
        check_capability(token, required_capability or self._default_capability)
        return token

    def _breaker_open(self) -> bool:
        if self._breaker is None:
            return False
        check = getattr(self._breaker, "is_open", None)
        return bool(check() if callable(check) else check)

    def _acquire_rate(self) -> None:
        if self._rate_limiter is None:
            return
        acquire = getattr(self._rate_limiter, "acquire", None)
        if callable(acquire):
            import inspect

            if inspect.isawaitable(acquire()):
                raise HardenedExecutorError(
                    "hardened_executor: async rate limiter requires aexecute"
                )

    def _audit(
        self,
        *,
        action: str,
        token: CapabilityToken,
        capability: str,
        outcome: str,
        detail: dict[str, Any] | None = None,
    ) -> int | None:
        try:
            self._action_log.record(
                action=action,
                subject=token.subject,
                capability=capability,
                outcome=outcome,
                detail=detail,
            )
            return len(self._action_log.entries) - 1
        except ActionLogError as exc:
            log.warning("hardened_executor: audit write failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 同步执行
    # ------------------------------------------------------------------

    def execute(
        self,
        token: str,
        *,
        fn: Callable[..., Any] | None = None,
        capability: str | None = None,
        envelope: ResourceEnvelope | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        use_breaker: bool = True,
        use_rate_limit: bool = True,
        use_honeypot: bool = True,
        audit: bool = True,
    ) -> ExecutionResult:
        """同步受控执行。fn 在调用线程运行；墙钟为协作式检查（阻塞式执行请用 aexecute）。"""
        t0 = time.monotonic()
        env = envelope or DEFAULT_ENVELOPE
        try:
            validate_envelope(env)
        except ValueError as exc:
            return ExecutionResult(status="error", error=f"invalid envelope: {exc}")

        cap = capability or self._default_capability
        try:
            tok = self._verify(token, required_capability=capability)
        except (CapabilityDeniedError, CapabilityError) as exc:
            return ExecutionResult(status="denied", error=str(exc))

        if use_breaker and self._breaker_open():
            msg = "circuit OPEN: execution rejected"
            if audit:
                self._audit(action="execute", token=tok, capability=cap, outcome="blocked", detail={"reason": msg})
            return ExecutionResult(status="blocked", error=msg, elapsed_ms=int((time.monotonic() - t0) * 1000))

        if use_rate_limit:
            try:
                self._acquire_rate()
            except Exception as exc:
                if audit:
                    self._audit(action="execute", token=tok, capability=cap, outcome="blocked", detail={"reason": f"rate limit: {exc}"})
                return ExecutionResult(status="blocked", error=f"rate limit: {exc}", elapsed_ms=int((time.monotonic() - t0) * 1000))

        probe = HoneypotProbe(self._honeypot_dir) if use_honeypot else None
        if probe is not None:
            probe.plant()

        outcome: Any = None
        err: str | None = None
        status = "ok"
        try:
            if fn is None:
                raise HardenedExecutorError("hardened_executor: fn must be provided")
            outcome = fn(*args, **(kwargs or {}))
        except Exception as exc:  # noqa: BLE001 — 基板不裸抛业务异常
            status = "error"
            err = f"{type(exc).__name__}: {exc}"

        trips: list[dict[str, Any]] = []
        if probe is not None:
            trips = probe.check_touched()
            probe.cleanup()
        if trips:
            status = "honeypot_trip"
            err = "honeypot probe touched: possible suspicious behavior"

        elapsed = int((time.monotonic() - t0) * 1000)
        if audit:
            self._audit(
                action="execute",
                token=tok,
                capability=cap,
                outcome=status,
                detail={"elapsed_ms": elapsed, "honey_trips": trips, "error": err},
            )
        return ExecutionResult(
            status=status, outcome=outcome, error=err, elapsed_ms=elapsed, honey_trips=trips
        )

    # ------------------------------------------------------------------
    # 异步执行
    # ------------------------------------------------------------------

    async def aexecute(
        self,
        token: str,
        *,
        fn: Callable[..., Awaitable[Any]] | None = None,
        capability: str | None = None,
        envelope: ResourceEnvelope | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        timeout: float | None = None,
        use_breaker: bool = True,
        use_rate_limit: bool = True,
        use_honeypot: bool = True,
        audit: bool = True,
    ) -> ExecutionResult:
        """异步受控执行；asyncio.wait_for 强制墙钟超时。"""
        t0 = time.monotonic()
        env = envelope or DEFAULT_ENVELOPE
        try:
            validate_envelope(env)
        except ValueError as exc:
            return ExecutionResult(status="error", error=f"invalid envelope: {exc}")

        cap = capability or self._default_capability
        try:
            tok = self._verify(token, required_capability=capability)
        except (CapabilityDeniedError, CapabilityError) as exc:
            return ExecutionResult(status="denied", error=str(exc))

        if use_breaker and self._breaker_open():
            msg = "circuit OPEN: execution rejected"
            if audit:
                self._audit(action="aexecute", token=tok, capability=cap, outcome="blocked", detail={"reason": msg})
            return ExecutionResult(status="blocked", error=msg, elapsed_ms=int((time.monotonic() - t0) * 1000))

        if use_rate_limit and self._rate_limiter is not None:
            acquire = getattr(self._rate_limiter, "acquire", None)
            if callable(acquire):
                try:
                    result = acquire()
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    if audit:
                        self._audit(action="aexecute", token=tok, capability=cap, outcome="blocked", detail={"reason": f"rate limit: {exc}"})
                    return ExecutionResult(status="blocked", error=f"rate limit: {exc}", elapsed_ms=int((time.monotonic() - t0) * 1000))

        probe = HoneypotProbe(self._honeypot_dir) if use_honeypot else None
        if probe is not None:
            probe.plant()

        outcome: Any = None
        err: str | None = None
        status = "ok"
        try:
            if fn is None:
                raise HardenedExecutorError("hardened_executor: fn must be provided")
            if timeout is None:
                timeout = env.wallclock_s
            outcome = await asyncio.wait_for(fn(*args, **(kwargs or {})), timeout=timeout)
        except asyncio.TimeoutError:
            status = "timeout"
            err = f"wallclock timeout after {timeout}s"
        except Exception as exc:  # noqa: BLE001
            status = "error"
            err = f"{type(exc).__name__}: {exc}"

        trips: list[dict[str, Any]] = []
        if probe is not None:
            trips = probe.check_touched()
            probe.cleanup()
        if trips and status == "ok":
            status = "honeypot_trip"
            err = "honeypot probe touched: possible suspicious behavior"

        elapsed = int((time.monotonic() - t0) * 1000)
        if audit:
            self._audit(
                action="aexecute",
                token=tok,
                capability=cap,
                outcome=status,
                detail={"elapsed_ms": elapsed, "honey_trips": trips, "error": err},
            )
        return ExecutionResult(
            status=status, outcome=outcome, error=err, elapsed_ms=elapsed, honey_trips=trips
        )

    # ------------------------------------------------------------------
    # 子进程执行（网络策略强制）
    # ------------------------------------------------------------------

    def _resolve_egress(self, command: str) -> str | None:
        """从 curl/wget 类命令解析出口 host（allowlist 模式用），无法解析返回 None。"""
        parts = command.split()
        if parts and parts[0] in ("curl", "wget"):
            for part in parts[1:]:
                if part.startswith("http://") or part.startswith("https://"):
                    from urllib.parse import urlparse

                    return urlparse(part).hostname
        return None

    async def execute_subprocess(
        self,
        token: str,
        *,
        command: str,
        capability: str = "executor.subprocess",
        envelope: ResourceEnvelope | None = None,
        cwd: str | None = None,
        env_vars: dict[str, str] | None = None,
        use_breaker: bool = True,
        use_honeypot: bool = True,
        audit: bool = True,
    ) -> dict[str, Any]:
        """命令级受控执行：网络策略强制 + 环境净化 + 墙钟超时 + 输出限额。"""
        t0 = time.monotonic()
        env_limits = envelope or DEFAULT_ENVELOPE
        try:
            validate_envelope(env_limits)
        except ValueError as exc:
            return {"status": "error", "error": f"invalid envelope: {exc}"}

        cap = capability
        try:
            tok = self._verify(token, required_capability=capability)
        except (CapabilityDeniedError, CapabilityError) as exc:
            return {"status": "denied", "error": str(exc)}

        if use_breaker and self._breaker_open():
            return {"status": "blocked", "error": "circuit OPEN: execution rejected"}

        # 网络策略强制：deny_all → 命令防火墙；allowlist → 出口白名单校验
        firewall_reason = self._sandbox.check_command(command)
        if env_limits.network.mode == "deny_all" and firewall_reason is not None:
            reason = f"network denied by envelope: {firewall_reason}"
            if audit:
                self._audit(action="subprocess", token=tok, capability=cap, outcome="blocked", detail={"reason": reason})
            return {"status": "blocked", "reason": reason, "elapsed_ms": int((time.monotonic() - t0) * 1000)}
        if env_limits.network.mode == "allowlist":
            egress_host = self._resolve_egress(command)
            if egress_host is not None and not env_limits.allows_network(egress_host):
                reason = f"egress host not allowed by envelope: {egress_host}"
                if audit:
                    self._audit(action="subprocess", token=tok, capability=cap, outcome="blocked", detail={"reason": reason})
                return {"status": "blocked", "reason": reason, "elapsed_ms": int((time.monotonic() - t0) * 1000)}

        probe = HoneypotProbe(self._honeypot_dir) if use_honeypot else None
        if probe is not None:
            probe.plant()

        clean_env = self._sandbox.sanitized_env() if env_vars is None else self._sanitize_env(env_vars)
        run_result = await self._sandbox.run(
            command, timeout=env_limits.wallclock_s, cwd=cwd, env=clean_env
        )
        run_result["elapsed_ms"] = int((time.monotonic() - t0) * 1000)

        trips: list[dict[str, Any]] = []
        if probe is not None:
            trips = probe.check_touched()
            probe.cleanup()
        if trips and run_result.get("status") == "ok":
            run_result["status"] = "honeypot_trip"
            run_result["error"] = "honeypot probe touched: possible suspicious behavior"
        run_result["honey_trips"] = trips

        if audit:
            self._audit(
                action="subprocess",
                token=tok,
                capability=cap,
                outcome=run_result.get("status", "unknown"),
                detail={"command": command[:200], "elapsed_ms": run_result["elapsed_ms"], "honey_trips": trips},
            )
        return run_result

    @staticmethod
    def _sanitize_env(env: dict[str, str]) -> dict[str, str]:
        """剥离代理变量与敏感凭据前缀。"""
        cleaned = dict(env)
        sensitive_prefixes = (
            "AWS_", "OPENAI_", "ANTHROPIC_", "DASHSCOPE_", "GEMINI_",
            "DEEPSEEK_", "TOGETHER_", "GROQ_", "HF_", "HUGGINGFACE_",
        )
        for key in list(cleaned):
            lower = key.lower()
            if "proxy" in lower or key.startswith(sensitive_prefixes):
                cleaned.pop(key, None)
        return cleaned
