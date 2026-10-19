"""本地虚拟文件系统与隔离执行环境 (3O 范式 Phase 1 默认实现).

零向上依赖: 仅依赖 obase.contracts, 不 import 任何上层业务包。
使用 asyncio.create_subprocess_shell 确保非阻塞执行。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from obase.contracts import IVFS_Sandbox


class VFSPathTraversalError(ValueError):
    """路径穿越安全校验失败"""


class LocalVFS(IVFS_Sandbox):
    """本地虚拟文件系统实现 (隔离性较弱，仅供基础运行与测试)"""

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()

    def _resolve(self, path: str) -> Path:
        """路径穿越安全校验 (Path Traversal Protection)。

        拒绝任何解析后逃逸出 workspace_root 的路径访问。
        """
        target = (self.workspace_root / path).resolve()
        if target != self.workspace_root and self.workspace_root not in target.parents:
            raise VFSPathTraversalError(f"path escapes workspace root: {path}")
        return target

    async def execute_isolated(self, cmd: str, timeout: int = 30) -> dict[str, Any]:
        process = None
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                cwd=self.workspace_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return {
                "exit_code": process.returncode,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
            }
        except TimeoutError:
            if process is not None:
                process.kill()
            return {"exit_code": -1, "stdout": "", "stderr": f"Timeout after {timeout}s"}

    async def read_file(self, path: str) -> bytes:
        target = self._resolve(path)
        return await asyncio.to_thread(target.read_bytes)

    async def write_file(self, path: str, content: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, content)
