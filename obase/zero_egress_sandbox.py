"""obase.zero_egress_sandbox — 零外联沙箱执行环境.

无网络出口的命令执行沙箱：
- 命令防火墙：拒绝网络类命令（curl/wget/nc/ssh/git fetch 等）
- 环境净化：剥离代理变量与敏感凭据
- 可选网络命名空间隔离（unshare -n，Linux 内核可用时）
- 超时熔断 + 输出限额

Example:
    >>> sb = ZeroEgressSandbox()
    >>> r = await sb.run("python -c 'print(1+1)'")
    >>> r["exit_code"]
    0
    >>> await sb.run("curl http://x")   # 被命令防火墙拒绝
    {'status': 'blocked', 'reason': 'network command denied: curl'}
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from typing import Any

__all__ = ["ZeroEgressSandbox", "SandboxError", "SandboxResult", "NETWORK_COMMANDS"]

NETWORK_COMMANDS = (
    "curl", "wget", "nc", "ncat", "telnet", "ssh", "scp", "sftp", "ftp",
    "git fetch", "git pull", "git push", "pip install", "pip download",
    "npm install", "apt-get", "apt ", "yum", "dnf", "docker pull",
    "dig", "nslookup", "ping", "traceroute", "hostname -I", "ifconfig", "ip addr",
)


@dataclass
class SandboxResult:
    """沙箱执行结果。"""

    status: str  # ok | blocked | timeout | error
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    reason: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "reason": self.reason,
            "elapsed_ms": self.elapsed_ms,
        }


class SandboxError(RuntimeError):
    """沙箱基础设施错误。"""


class ZeroEgressSandbox:
    """零外联沙箱：命令防火墙 + 环境净化 + 可选 netns 隔离。"""

    def __init__(
        self,
        *,
        deny_network: bool = True,
        use_network_namespace: bool = True,
        max_output_chars: int = 20_000,
        strip_proxy_env: bool = True,
    ) -> None:
        self.deny_network = deny_network
        self.use_network_namespace = use_network_namespace
        self.max_output_chars = max_output_chars
        self.strip_proxy_env = strip_proxy_env
        self._netns_available: bool | None = None

    @property
    def netns_available(self) -> bool:
        """unshare -n 是否可用（Linux）。"""
        if self._netns_available is None:
            self._netns_available = (
                os.name == "posix" and shutil.which("unshare") is not None
            )
        return self._netns_available

    # ------------------------------------------------------------------
    # 检查
    # ------------------------------------------------------------------

    def check_command(self, command: str) -> str | None:
        """命令防火墙：命中网络命令返回拒绝原因，否则 None。"""
        if not self.deny_network:
            return None
        lowered = command.strip().lower()
        for banned in NETWORK_COMMANDS:
            if lowered == banned or lowered.startswith(banned):
                return f"network command denied: {banned.strip()}"
        return None

    def sanitized_env(self) -> dict[str, str]:
        """净化后的环境（剥离代理与凭据）。"""
        env = dict(os.environ)
        if self.strip_proxy_env:
            for key in list(env):
                if "proxy" in key.lower() or key in (
                    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DASHSCOPE_API_KEY",
                ):
                    env.pop(key, None)
        return env

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(
        self,
        command: str,
        *,
        timeout: float = 60.0,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """执行单条命令（零外联语义）。"""
        import time

        if not command.strip():
            raise SandboxError("zero_egress_sandbox: command must not be empty")

        reason = self.check_command(command)
        if reason is not None:
            return SandboxResult(status="blocked", reason=reason).to_dict()

        t0 = time.monotonic()
        try:
            if self.use_network_namespace and self.netns_available:
                argv = ["unshare", "-n", "sh", "-c", command]
            else:
                argv = ["sh", "-c", command]
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=env or self.sanitized_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    status="timeout",
                    reason=f"timed out after {timeout}s",
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                ).to_dict()
        except FileNotFoundError as exc:
            raise SandboxError(f"zero_egress_sandbox: shell unavailable: {exc}") from exc
        except OSError as exc:
            return SandboxResult(
                status="error", reason=f"cannot execute: {exc}",
            ).to_dict()

        return SandboxResult(
            status="ok" if proc.returncode == 0 else "error",
            exit_code=proc.returncode,
            stdout=stdout.decode("utf-8", errors="replace")[: self.max_output_chars],
            stderr=stderr.decode("utf-8", errors="replace")[: self.max_output_chars],
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        ).to_dict()
