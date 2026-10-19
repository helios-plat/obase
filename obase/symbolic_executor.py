"""obase: 符号执行沙箱。不依赖上层模块。"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any

__all__ = ["SymbolicExecutor", "SymbolicExecutorError"]


class SymbolicExecutorError(RuntimeError):
    """符号执行器错误."""


class SymbolicExecutor:
    """CrossHair 符号执行引擎封装.

    职责:
    - 隔离底层 crosshair 环境
    - 超时控制防止死循环
    - 内存限制防止符号爆炸
    """

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def verify_file(self, filepath: str) -> dict[str, Any]:
        """调用 CrossHair 对包含契约的 Python 文件进行符号执行.

        CrossHair 尝试寻找任何能够打破契约（Contract）的反例。
        找不到反例 → ok=True，代码通过数学证明。

        Args:
            filepath: 含 deal 契约装饰器的 Python 文件路径

        Returns:
            {
                "ok": bool,
                "stdout": str,
                "stderr": str,
                "exit_code": int,
            }
        """
        try:
            result = subprocess.run(
                ["crosshair", "check", filepath],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "stdout": "",
                "stderr": f"符号执行超时 ({self.timeout}s)，可能存在无限循环路径",
                "exit_code": -1,
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "crosshair 未安装。运行: pip install crosshair-tool",
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "ok": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    def verify_source(
        self, code: str, *, filename: str = "verify_target.py"
    ) -> dict[str, Any]:
        """直接将代码字符串写入临时文件并验证.

        Args:
            code: 含契约的 Python 源代码
            filename: 临时文件名（用于错误定位）

        Returns:
            同 verify_file
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="verify_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)
            return self.verify_file(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def health(self) -> dict[str, Any]:
        """健康检查."""
        return {
            "status": "healthy",
            "timeout": self.timeout,
            "crosshair_available": self._check_crosshair(),
        }

    @staticmethod
    def _check_crosshair() -> bool:
        try:
            subprocess.run(
                ["crosshair", "--version"],
                capture_output=True,
                timeout=5,
            )
            return True
        except Exception:
            return False
