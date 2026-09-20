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
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from obase.provider_routing import ProtocolFamily

__all__ = [
    "HarnessRunResult",
    "HarnessCapabilities",
    "HarnessAdapter",
    "BaseCLIHarnessAdapter",
    "CodexHarnessAdapter",
    "ClaudeCodeHarnessAdapter",
    "OpenCodeHarnessAdapter",
    "HARNESS_CATEGORY",
    "register_harness_adapters",
    "discover_harness_capabilities",
]

HARNESS_CATEGORY = "harness"


# ---------------------------------------------------------------------------
# 统一结果 / capabilities
# ---------------------------------------------------------------------------


@dataclass
class HarnessRunResult:
    """统一 harness 运行结果。"""

    run_id: str
    status: str  # "ok" | "error" | "cancelled" | "running"
    output: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    native_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarnessCapabilities:
    """统一 capability 描述。"""

    streaming: bool = False
    resume: bool = False
    cancel: bool = False
    tool_calls: bool = False
    workspace: bool = False
    diff: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            "streaming": self.streaming,
            "resume": self.resume,
            "cancel": self.cancel,
            "tool_calls": self.tool_calls,
            "workspace": self.workspace,
            "diff": self.diff,
        }


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
            tracked.status = "error"
            return HarnessRunResult(
                run_id=run_id,
                status="error",
                error=str(exc),
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
            tracked.status = "cancelled"
            return HarnessRunResult(
                run_id=run_id,
                status="cancelled",
                error="timeout",
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
                native_metadata={"binary": self.binary, "returncode": rc},
            )
        output, usage, error = self.parse_output(stdout, stderr, rc)
        tracked.status = "ok" if error is None else "error"
        session = self.extract_session(stdout, stderr)
        if session:
            tracked.harness_session = session
        return HarnessRunResult(
            run_id=run_id,
            status=tracked.status,
            output=output,
            usage=usage,
            error=error,
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
        tracked = self._runs.get(run_id)
        session = kwargs.get("session") or (tracked.harness_session if tracked else None)
        if not session:
            return HarnessRunResult(
                run_id=run_id,
                status="error",
                error="no harness session recorded for resume",
                native_metadata={"binary": self.binary},
            )
        return await self._spawn(self.build_resume_argv(session, prompt, **kwargs), **kwargs)

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
