"""3O 范式内化 — 沙盒运行器 (obase 基础设施).

Docker 隔离 (CPU/内存限制 + 网络隔离) 与本地回退实现。
Docker SDK 惰性加载: 未安装时 DockerSandboxRunner 抛 ImportError。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxResult:
    """沙盒执行结果 (与 OpenRSI 轨迹契约一致)。"""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    execution_time_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class LocalSandboxRunner:
    """本地子进程沙盒 (隔离性弱, 仅供基础运行与测试)。"""

    def __init__(self, cwd: str | None = None):
        self.cwd = cwd

    async def execute(self, code_dir: str, command: str, timeout_sec: int = 30) -> SandboxResult:
        start = time.monotonic()
        process = None
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=code_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
            return SandboxResult(
                exit_code=process.returncode or 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                execution_time_ms=int((time.monotonic() - start) * 1000),
            )
        except TimeoutError:
            if process is not None:
                process.kill()
            return SandboxResult(
                exit_code=-1,
                timed_out=True,
                stderr=f"Timeout after {timeout_sec}s (SIGKILL)",
                execution_time_ms=int((time.monotonic() - start) * 1000),
            )


class DockerSandboxRunner:
    """Docker 隔离沙盒: 限制 CPU 核数、内存上限, 并禁用网络。

    依赖 docker SDK (惰性加载); 未安装时构造抛 ImportError。
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        cpu_count: int = 1,
        mem_limit_mb: int = 4096,
        network_disabled: bool = True,
    ):
        try:
            import docker  # noqa: F401
        except ImportError as e:  # pragma: no cover - 环境依赖
            raise ImportError(
                "DockerSandboxRunner requires the 'docker' SDK (pip install docker)"
            ) from e
        self.image = image
        self.cpu_count = cpu_count
        self.mem_limit_mb = mem_limit_mb
        self.network_disabled = network_disabled

    async def execute(self, code_dir: str, command: str, timeout_sec: int = 30) -> SandboxResult:
        import docker

        client = docker.from_env()
        start = time.monotonic()
        try:
            container = client.containers.run(
                self.image,
                command=["/bin/sh", "-c", command],
                working_dir="/workspace",
                volumes={code_dir: {"bind": "/workspace", "mode": "rw"}},
                nano_cpus=int(self.cpu_count * 1e9),
                mem_limit=f"{self.mem_limit_mb}m",
                network_disabled=self.network_disabled,
                detach=True,
            )
            try:
                exit_code = container.wait(timeout=timeout_sec).get("StatusCode", -1)
            except Exception:
                container.kill()
                return SandboxResult(
                    exit_code=-1,
                    timed_out=True,
                    stderr=f"Timeout after {timeout_sec}s (SIGKILL)",
                    execution_time_ms=int((time.monotonic() - start) * 1000),
                )
            stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                execution_time_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            try:
                container.remove(force=True)  # type: ignore[possibly-undefined]
            except Exception:
                pass
