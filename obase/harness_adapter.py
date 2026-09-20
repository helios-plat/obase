"""obase.harness_adapter — Unified agent-CLI harness adapters.

WAVE A owner: obase. 唯一注册入口为 ProviderRegistry(category="harness")。

本模块只做 transport/process 级适配:
- run / resume / cancel / status (+ 可选 stream / workspace / diff)
- 统一 HarnessRunResult + capability discovery

明确不做:
- semantic task routing, model selection authority, approval authority
- 项目目标/会话/工作区的所有权状态,项目会话持久化

已实现真实 adapter (均为真实 CLI 子进程,无 placeholder):
- CodexHarnessAdapter      (binary: codex)
- ClaudeCodeHarnessAdapter (binary: claude)
- OpenCodeHarnessAdapter   (binary: opencode)
"""

from __future__ import annotations

import asyncio
import json
import shutil
import signal
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from obase.provider_routing import ProtocolFamily

__all__ = [
    "HarnessRunResult",
    "HarnessRunRequest",
    "HarnessActivity",
    "ActivityKind",
    "HarnessErrorKind",
    "HarnessCapabilities",
    "HarnessAdapter",
    "BaseCLIHarnessAdapter",
    "CodexHarnessAdapter",
    "ClaudeCodeHarnessAdapter",
    "OpenCodeHarnessAdapter",
    "HARNESS_CATEGORY",
    "RESULT_STATUSES",
    "TERMINAL_STATUSES",
    "normalize_status",
    "apply_cleanup_outcome",
    "register_harness_adapters",
    "discover_harness_capabilities",
]

HARNESS_CATEGORY = "harness"


# ---------------------------------------------------------------------------
# 统一结果 / capabilities
# ---------------------------------------------------------------------------


#: Canonical harness execution statuses (D2, single authority).
#: ``partial`` = execution ended with incomplete but usable output.
RESULT_STATUSES = ("completed", "failed", "cancelled", "timeout", "partial")

#: Every canonical result status is a terminal observation of the harness
#: execution itself. ("进程退出" only means harness-terminal — it never
#: implies goal acceptance; there is no goal-acceptance field by design.)
TERMINAL_STATUSES = ("completed", "failed", "cancelled", "timeout", "partial")

_STATUS_ALIASES = {
    "ok": "completed",
    "success": "completed",
    "succeeded": "completed",
    "done": "completed",
    "completed": "completed",
    "error": "failed",
    "failed": "failed",
    "failure": "failed",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "timeout": "timeout",
    "timed_out": "timeout",
    "partial": "partial",
    "incomplete": "partial",
}


def normalize_status(value: Any, *, default: str = "failed") -> str:
    """Normalize an upstream status string to the canonical set, fail-closed.

    Unknown values never default to ``completed`` — they map to ``default``
    (``"failed"`` unless the caller explicitly passes another canonical
    status such as ``"partial"`` for incomplete-but-usable output).
    """
    if isinstance(value, str):
        hit = _STATUS_ALIASES.get(value.strip().lower())
        if hit is not None:
            return hit
    if default in RESULT_STATUSES:
        return default
    return "failed"


class HarnessErrorKind(StrEnum):
    """Minimal unified harness error taxonomy (D2, single authority).

    Carries no retry/disposition semantics — transient/permanent judgement
    and resume disposition belong to the project runtime (D3), never here.
    The native error text is always preserved alongside.
    """

    CONFIGURATION = "configuration"
    UNAVAILABLE = "unavailable"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    PROTOCOL = "protocol"
    PROCESS = "process"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RESUME_REJECTED = "resume_rejected"
    EXECUTION = "execution"

    @classmethod
    def coerce(cls, value: HarnessErrorKind | str | None) -> HarnessErrorKind | None:
        """Coerce a stored string to a member; ``None`` stays ``None``."""
        if value is None or isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value.strip().lower())
            except ValueError:
                pass
        valid = sorted(member.value for member in cls)
        raise ValueError(f"unknown harness error kind {value!r}; expected one of {valid}")


_AUTH_PATTERNS = ("oauth", "unauthorized", "unauthenticated", "401", "authentication")
_RATE_LIMIT_PATTERNS = ("rate limit", "rate_limit", "429", "too many requests", "usage limit")


def classify_process_error(stderr: str, returncode: int) -> HarnessErrorKind:
    """Classify a finished-process failure from direct evidence only.

    Auth/rate-limit kinds require explicit marker text in stderr; anything
    else with a nonzero exit is ``PROCESS``. The raw text is never consumed
    — it stays on the result ``error`` field verbatim.
    """
    text = (stderr or "").lower()
    if any(marker in text for marker in _AUTH_PATTERNS):
        return HarnessErrorKind.AUTHENTICATION
    if any(marker in text for marker in _RATE_LIMIT_PATTERNS):
        return HarnessErrorKind.RATE_LIMITED
    return HarnessErrorKind.PROCESS


class ActivityKind(StrEnum):
    """Structured harness activity kinds (D2, single authority)."""

    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TERMINAL = "terminal"
    STATUS = "status"

    @classmethod
    def coerce(cls, value: ActivityKind | str) -> ActivityKind:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value.strip().lower())
            except ValueError:
                pass
        valid = sorted(member.value for member in cls)
        raise ValueError(f"unknown activity kind {value!r}; expected one of {valid}")


@dataclass(frozen=True)
class HarnessActivity:
    """One structured harness execution activity (static observation).

    Tool activities carry ``tool_name`` + ``tool_arguments`` (reference, not
    secrets) + ``tool_status``/``tool_result_ref`` — never a bare bool or
    free text alone. No activity is ever fabricated: providers that cannot
    observe an activity declare it unsupported via capabilities.
    """

    kind: ActivityKind
    sequence: int
    run_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    turn_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    tool_arguments: Mapping[str, Any] = field(default_factory=dict)
    tool_status: str | None = None
    tool_result_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ActivityKind.coerce(self.kind))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("HarnessActivity.sequence must be an int")
        if self.sequence < 0:
            raise ValueError("HarnessActivity.sequence must be >= 0")
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "tool_arguments", dict(self.tool_arguments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "payload": dict(self.payload),
            "metadata": dict(self.metadata),
            "tool_name": self.tool_name,
            "tool_arguments": dict(self.tool_arguments),
            "tool_status": self.tool_status,
            "tool_result_ref": self.tool_result_ref,
        }


@dataclass(frozen=True)
class HarnessRunRequest:
    """Static execution request envelope (no project business objects).

    Never carries project goal/session business objects or any mutable run
    state — only the inputs one harness execution needs.
    """

    prompt: str
    cwd: str | None = None
    session_id: str | None = None
    timeout_s: float | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prompt:
            raise ValueError("HarnessRunRequest.prompt must not be empty")
        object.__setattr__(self, "env", dict(self.env))
        object.__setattr__(self, "options", dict(self.options))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_kwargs(self) -> dict[str, Any]:
        """Project the request onto adapter ``run()`` keyword arguments."""
        kwargs: dict[str, Any] = dict(self.options)
        if self.cwd is not None:
            kwargs["cwd"] = self.cwd
        if self.timeout_s is not None:
            kwargs["timeout_s"] = self.timeout_s
        if self.session_id is not None:
            kwargs["session"] = self.session_id
        return kwargs

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "cwd": self.cwd,
            "session_id": self.session_id,
            "timeout_s": self.timeout_s,
            "env": dict(self.env),
            "options": dict(self.options),
            "metadata": dict(self.metadata),
        }


@dataclass
class HarnessRunResult:
    """统一 harness 运行结果 (D2 canonical execution ABI)。

    Identity: ``run_id`` (this execution) vs ``session_id`` (resumable
    upstream agent session) vs ``turn_id`` (one turn in a session) vs
    ``parent_run_id`` (the run this execution resumes/continues) — four
    distinct ids, never conflated.

    ``terminal_observed=True`` means the upstream already produced an
    authoritative terminal result; later cleanup outcomes must never
    re-judge it (see :func:`apply_cleanup_outcome`).
    """

    run_id: str
    status: str  # canonical: one of RESULT_STATUSES
    output: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    native_metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    turn_id: str | None = None
    parent_run_id: str | None = None
    terminal_observed: bool = False
    error_kind: HarnessErrorKind | str | None = None
    activities: tuple[HarnessActivity, ...] = ()

    def __post_init__(self) -> None:
        self.error_kind = HarnessErrorKind.coerce(self.error_kind)
        if isinstance(self.activities, (list, tuple)):
            for item in self.activities:
                if not isinstance(item, HarnessActivity):
                    raise TypeError("HarnessRunResult.activities must hold HarnessActivity")
            self.activities = tuple(self.activities)
        else:
            raise TypeError("HarnessRunResult.activities must be a list/tuple")
        self.terminal_observed = bool(self.terminal_observed)

    @property
    def is_terminal(self) -> bool:
        """Whether the recorded status is a terminal observation."""
        return self.status in TERMINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "parent_run_id": self.parent_run_id,
            "status": self.status,
            "output": self.output,
            "usage": dict(self.usage),
            "error": self.error,
            "error_kind": self.error_kind.value if self.error_kind else None,
            "terminal_observed": self.terminal_observed,
            "activities": [item.to_dict() for item in self.activities],
            "native_metadata": dict(self.native_metadata),
        }


def apply_cleanup_outcome(result: HarnessRunResult, cleanup_error: str | None) -> HarnessRunResult:
    """Fold a post-terminal cleanup outcome into a result without re-judging.

    Once ``terminal_observed`` is set, pipe/subprocess/stream teardown
    timeouts are recorded into ``native_metadata`` only — the terminal
    status/output/error never change. Non-terminal results with a cleanup
    error fail closed to ``failed``.
    """
    if result.terminal_observed:
        if cleanup_error:
            merged = dict(result.native_metadata)
            merged["cleanup_error_ignored"] = cleanup_error
            return replace(result, native_metadata=merged)
        return result
    if cleanup_error:
        return replace(
            result,
            status="failed",
            error=result.error or cleanup_error,
            error_kind=result.error_kind or HarnessErrorKind.EXECUTION,
        )
    return result


@dataclass
class HarnessCapabilities:
    """统一 capability 描述。

    D2: this stays a harness-specific typed view. The generic runtime
    capability authority remains ``D1 ProviderSpec.capabilities`` +
    ``lifecycle`` — see :meth:`lifecycle_matrix` for the projection.
    ``as_dict`` keeps the original six transport keys (pinned contract).
    """

    streaming: bool = False
    resume: bool = False
    cancel: bool = False
    tool_calls: bool = False
    workspace: bool = False
    diff: bool = False
    tool_activity: bool = False
    session: bool = False
    turn_identity: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            "streaming": self.streaming,
            "resume": self.resume,
            "cancel": self.cancel,
            "tool_calls": self.tool_calls,
            "workspace": self.workspace,
            "diff": self.diff,
        }

    def lifecycle_matrix(self) -> dict[str, bool]:
        """Project onto the D1 lifecycle/support matrix (no second authority)."""
        return {
            "run": True,
            "stream": self.streaming,
            "status": True,
            "cancel": self.cancel,
            "resume": self.resume,
        }

    def supports_activity(self, kind: ActivityKind | str) -> bool:
        """Whether this harness can honestly observe one activity kind."""
        resolved = ActivityKind.coerce(kind)
        if resolved in (
            ActivityKind.MESSAGE,
            ActivityKind.TERMINAL,
            ActivityKind.STATUS,
        ):
            return True
        return self.tool_activity


@runtime_checkable
class HarnessAdapter(Protocol):
    """HarnessAdapter 最小 contract (稳定后抽象)。"""

    @property
    def name(self) -> str: ...
    @property
    def capabilities(self) -> HarnessCapabilities: ...
    async def run(self, prompt: str, **kwargs: Any) -> HarnessRunResult: ...
    async def resume(self, run_id: str, prompt: str = "", **kwargs: Any) -> HarnessRunResult: ...
    async def cancel(self, run_id: str) -> bool: ...
    async def status(self, run_id: str) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# CLI 进程基类 (transport only)
# ---------------------------------------------------------------------------


class HarnessAdapterError(RuntimeError):
    """harness adapter 错误。"""


@dataclass
class _TrackedRun:
    run_id: str
    proc: asyncio.subprocess.Process | None = None
    harness_session: str | None = None  # harness 原生 session/thread id
    status: str = "running"
    started_at: float = field(default_factory=time.time)


class BaseCLIHarnessAdapter:
    """真实 CLI 子进程适配基类。只管理进程生命周期,不持有项目状态。"""

    binary: str = ""
    adapter_name: str = "base"
    protocol_family: ProtocolFamily = ProtocolFamily.HARNESS
    _capabilities: HarnessCapabilities = HarnessCapabilities()

    def __init__(self, *, binary: str | None = None, timeout_s: float = 120.0) -> None:
        if binary:
            self.binary = binary
        self.timeout_s = timeout_s
        self._runs: dict[str, _TrackedRun] = {}

    # -- identity / capabilities -------------------------------------------
    @property
    def name(self) -> str:
        return self.adapter_name

    @property
    def capabilities(self) -> HarnessCapabilities:
        return self._capabilities

    def binary_path(self) -> str | None:
        """真实 binary 解析 (PATH 查找,找不到返回 None)。"""
        return shutil.which(self.binary) if self.binary else None

    def is_available(self) -> bool:
        return self.binary_path() is not None

    async def version(self) -> str | None:
        """真实 --version 探测,失败返回 None (不抛异常)。"""
        if not self.is_available():
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                self.binary,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode == 0:
                return out.decode(errors="ignore").strip()
            return None
        except Exception:
            return None

    # -- contract (子类提供 argv 构造 + 输出解析) ----------------------------
    def build_run_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        raise NotImplementedError

    def build_resume_argv(self, session: str, prompt: str, **kwargs: Any) -> list[str]:
        raise NotImplementedError

    def parse_output(
        self, stdout: str, stderr: str, returncode: int
    ) -> tuple[str, dict[str, Any], str | None]:
        """解析原生输出 -> (output, usage, error)。默认实现诚实透传。"""
        if returncode == 0:
            return stdout.strip(), {}, None
        return "", {}, (stderr.strip() or f"exit={returncode}")

    # -- run / resume / cancel / status -------------------------------------
    async def _spawn(self, argv: list[str], **kwargs: Any) -> HarnessRunResult:
        run_id = f"hrn_{uuid.uuid4().hex[:12]}"
        timeout = float(kwargs.get("timeout_s", self.timeout_s))
        tracked = _TrackedRun(run_id=run_id)
        self._runs[run_id] = tracked
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=kwargs.get("cwd"),
            )
        except FileNotFoundError as exc:
            tracked.status = "failed"
            return HarnessRunResult(
                run_id=run_id,
                status="failed",
                error=str(exc),
                error_kind=HarnessErrorKind.UNAVAILABLE,
                terminal_observed=True,
                native_metadata={"binary": self.binary, "argv": argv},
            )
        tracked.proc = proc
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            tracked.status = "timeout"
            return HarnessRunResult(
                run_id=run_id,
                status="timeout",
                error="timeout",
                error_kind=HarnessErrorKind.TIMEOUT,
                terminal_observed=True,
                native_metadata={"binary": self.binary, "timeout_s": timeout},
            )
        stdout = out_b.decode(errors="ignore")
        stderr = err_b.decode(errors="ignore")
        rc = proc.returncode or 0
        if tracked.status == "cancelled":
            # cancel() 已标记:保留取消语义,不被退出码覆盖
            return HarnessRunResult(
                run_id=run_id,
                status="cancelled",
                error="cancelled",
                error_kind=HarnessErrorKind.CANCELLED,
                terminal_observed=True,
                session_id=tracked.harness_session,
                native_metadata={"binary": self.binary, "returncode": rc},
            )
        output, usage, error = self.parse_output(stdout, stderr, rc)
        tracked.status = "completed" if error is None else "failed"
        session = self.extract_session(stdout, stderr)
        if session:
            tracked.harness_session = session
        error_kind = None if error is None else classify_process_error(stderr, rc)
        terminal = HarnessActivity(
            kind=ActivityKind.TERMINAL,
            sequence=0,
            run_id=run_id,
            session_id=tracked.harness_session,
            payload={"status": tracked.status, "returncode": rc},
        )
        return HarnessRunResult(
            run_id=run_id,
            status=tracked.status,
            output=output,
            usage=usage,
            error=error,
            error_kind=error_kind,
            terminal_observed=True,
            session_id=tracked.harness_session,
            activities=(terminal,),
            native_metadata={
                "binary": self.binary,
                "argv": argv,
                "returncode": rc,
                "stderr_tail": stderr[-2000:],
                "harness_session": tracked.harness_session,
            },
        )

    def extract_session(self, stdout: str, stderr: str) -> str | None:
        """从原生输出提取 harness session id (默认无)。"""
        return None

    async def run(self, prompt: str, **kwargs: Any) -> HarnessRunResult:
        if not prompt:
            raise ValueError(f"{self.adapter_name}: prompt must not be empty")
        return await self._spawn(self.build_run_argv(prompt, **kwargs), **kwargs)

    async def resume(self, run_id: str, prompt: str = "", **kwargs: Any) -> HarnessRunResult:
        """Resume a recorded harness session (D2 ABI).

        Rejection (no resumable session) is itself an authoritative,
        terminal outcome: status ``failed`` + ``RESUME_REJECTED``. No
        D3 disposition is decided here — callers own retry/fresh policy.
        """
        tracked = self._runs.get(run_id)
        session = kwargs.get("session") or (tracked.harness_session if tracked else None)
        if not session:
            return HarnessRunResult(
                run_id=run_id,
                status="failed",
                error="no harness session recorded for resume",
                error_kind=HarnessErrorKind.RESUME_REJECTED,
                terminal_observed=True,
                parent_run_id=run_id,
                native_metadata={"binary": self.binary},
            )
        result = await self._spawn(self.build_resume_argv(session, prompt, **kwargs), **kwargs)
        return replace(result, parent_run_id=run_id, session_id=session)

    async def cancel(self, run_id: str) -> bool:
        tracked = self._runs.get(run_id)
        if tracked is None or tracked.proc is None:
            return False
        proc = tracked.proc
        if proc.returncode is not None:
            return False  # 已结束,无可取消
        try:
            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except TimeoutError:
                proc.kill()
            tracked.status = "cancelled"
            return True
        except (ProcessLookupError, OSError):
            return False

    async def status(self, run_id: str) -> dict[str, Any]:
        """run 状态 + 真实 binary 版本探测。"""
        tracked = self._runs.get(run_id)
        info: dict[str, Any] = {
            "adapter": self.adapter_name,
            "binary": self.binary,
            "binary_available": self.is_available(),
            "binary_version": await self.version(),
        }
        if tracked is None:
            info.update({"run_id": run_id, "run_status": "unknown"})
            return info
        proc = tracked.proc
        info.update(
            {
                "run_id": run_id,
                "run_status": tracked.status,
                "harness_session": tracked.harness_session,
                "elapsed_s": round(time.time() - tracked.started_at, 2),
                "exit_code": proc.returncode if proc else None,
            }
        )
        return info

    # -- 可选 contract (默认不支持,子类按需覆盖) ------------------------------
    async def stream(self, prompt: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        """可选:流式输出 (默认不支持,逐块 yield 文本)。"""
        result = await self.run(prompt, **kwargs)
        if result.output:
            yield result.output

    async def stream_activities(self, prompt: str, **kwargs: Any) -> AsyncIterator[HarnessActivity]:
        """Activity-typed view over one execution (D2, extends text stream).

        The CLI transports below have no live event channel, so activities
        are projected from the authoritative terminal observation: message
        (real output text) + status + terminal, strictly ordered. Tool
        activities appear only when honestly observed — none of the current
        adapters observe them (``tool_activity`` capability is ``False``),
        so none are ever fabricated here.
        """
        result = await self.run(prompt, **kwargs)
        sequence = 0
        if result.output:
            yield HarnessActivity(
                kind=ActivityKind.MESSAGE,
                sequence=sequence,
                run_id=result.run_id,
                session_id=result.session_id,
                payload={"text": result.output},
            )
            sequence += 1
        yield HarnessActivity(
            kind=ActivityKind.STATUS,
            sequence=sequence,
            run_id=result.run_id,
            session_id=result.session_id,
            payload={"status": result.status, "error": result.error},
        )
        sequence += 1
        yield HarnessActivity(
            kind=ActivityKind.TERMINAL,
            sequence=sequence,
            run_id=result.run_id,
            session_id=result.session_id,
            payload={"status": result.status, "terminal_observed": True},
        )

    async def workspace(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "workspace": None, "supported": False}

    async def diff(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "diff": None, "supported": False}


# ---------------------------------------------------------------------------
# 真实 adapters
# ---------------------------------------------------------------------------


class CodexHarnessAdapter(BaseCLIHarnessAdapter):
    """Codex CLI adapter (codex exec / codex exec resume)。"""

    binary = "codex"
    adapter_name = "codex"
    _capabilities = HarnessCapabilities(
        streaming=False,
        resume=True,
        cancel=True,
        tool_calls=True,
        workspace=True,
        diff=False,
        tool_activity=False,
        session=True,
        turn_identity=False,
    )

    def build_run_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        argv = [self.binary, "exec", "--skip-git-repo-check"]
        if kwargs.get("cwd"):
            argv += ["-C", str(kwargs["cwd"])]
        argv.append(prompt)
        return argv

    def build_resume_argv(self, session: str, prompt: str, **kwargs: Any) -> list[str]:
        argv = [self.binary, "exec", "resume", session]
        argv.append(prompt or "")
        return argv


class ClaudeCodeHarnessAdapter(BaseCLIHarnessAdapter):
    """Claude Code CLI adapter (claude -p / claude --resume)。"""

    binary = "claude"
    adapter_name = "claude-code"
    _capabilities = HarnessCapabilities(
        streaming=False,
        resume=True,
        cancel=True,
        tool_calls=True,
        workspace=True,
        diff=False,
        tool_activity=False,
        session=True,
        turn_identity=False,
    )

    def build_run_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        argv = [self.binary, "-p", prompt, "--output-format", "json"]
        if kwargs.get("max_turns") is not None:
            argv += ["--max-turns", str(kwargs["max_turns"])]
        return argv

    def build_resume_argv(self, session: str, prompt: str, **kwargs: Any) -> list[str]:
        return [self.binary, "--resume", session, "-p", prompt or "", "--output-format", "json"]

    def parse_output(
        self, stdout: str, stderr: str, returncode: int
    ) -> tuple[str, dict[str, Any], str | None]:
        if returncode != 0:
            return "", {}, (stderr.strip() or f"exit={returncode}")
        try:
            data = json.loads(stdout)
            if isinstance(data, dict) and data.get("type") == "result":
                return (
                    str(data.get("result", "")),
                    dict(data.get("usage") or {}),
                    data.get("error"),
                )
        except (json.JSONDecodeError, AttributeError):
            pass
        return stdout.strip(), {}, None


class OpenCodeHarnessAdapter(BaseCLIHarnessAdapter):
    """OpenCode CLI adapter (opencode run / opencode run -s)。"""

    binary = "opencode"
    adapter_name = "opencode"
    _capabilities = HarnessCapabilities(
        streaming=True,
        resume=True,
        cancel=True,
        tool_calls=True,
        workspace=True,
        diff=False,
        tool_activity=False,
        session=True,
        turn_identity=False,
    )

    def build_run_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        argv = [self.binary, "run", prompt, "--format", "json"]
        if kwargs.get("model"):
            argv += ["-m", str(kwargs["model"])]
        if kwargs.get("cwd"):
            argv += ["--dir", str(kwargs["cwd"])]
        return argv

    def build_resume_argv(self, session: str, prompt: str, **kwargs: Any) -> list[str]:
        return [self.binary, "run", "-s", session, prompt or "", "--format", "json"]

    def extract_session(self, stdout: str, stderr: str) -> str | None:
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = evt.get("sessionID")
            if isinstance(sid, str) and sid:
                return sid
        return None

    def parse_output(
        self, stdout: str, stderr: str, returncode: int
    ) -> tuple[str, dict[str, Any], str | None]:
        if returncode != 0:
            return "", {}, (stderr.strip() or f"exit={returncode}")
        texts: list[str] = []
        usage: dict[str, Any] = {}
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "text":
                part = evt.get("part", {})
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part["text"]))
            elif evt.get("type") == "step_finish":
                part = evt.get("part", {})
                if isinstance(part, dict):
                    tokens = part.get("tokens") or {}
                    usage = {"tokens": tokens, "cost": part.get("cost")}
        if texts or usage:
            return "\n".join(texts).strip(), usage, None
        return stdout.strip(), {}, None


# ---------------------------------------------------------------------------
# 注册 / capability discovery (唯一入口: ProviderRegistry)
# ---------------------------------------------------------------------------


def register_harness_adapters(registry: Any | None = None) -> list[str]:
    """将真实 harness adapters 注册到 ProviderRegistry(category="harness")。"""
    from obase.provider_registry import ProviderRegistry

    reg = registry or ProviderRegistry.get()
    adapters = [
        CodexHarnessAdapter(),
        ClaudeCodeHarnessAdapter(),
        OpenCodeHarnessAdapter(),
    ]
    names: list[str] = []
    for adapter in adapters:
        reg.register(HARNESS_CATEGORY, adapter.name, adapter, replace=True)
        names.append(adapter.name)
    return names


def discover_harness_capabilities(registry: Any | None = None) -> dict[str, dict[str, bool]]:
    """capability discovery:列出已注册 harness 的 capabilities。"""
    from obase.provider_registry import ProviderRegistry

    reg = registry or ProviderRegistry.get()
    out: dict[str, dict[str, bool]] = {}
    for category, name in ProviderRegistry.list_providers(HARNESS_CATEGORY):
        if category != HARNESS_CATEGORY:
            continue
        try:
            adapter = reg.generic(HARNESS_CATEGORY, name)
        except Exception:
            continue
        caps = getattr(adapter, "capabilities", None)
        if caps is not None:
            out[name] = caps.as_dict() if hasattr(caps, "as_dict") else dict(caps)
    return out
