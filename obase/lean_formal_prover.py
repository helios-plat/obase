"""obase.lean_formal_prover — Lean 4 形式化定理证明器接口.

Lean 4 CLI 适配器：把 Lean 代码写入临时文件并调用 lean 编译器校验
语义证明。lean 可执行文件缺失 / 超时均优雅降级为 dict（不抛）。

Example:
    >>> p = LeanFormalProver()
    >>> r = p.verify_lean_code("theorem t : True := by trivial")
    >>> r["valid"] in (True, False)
    True
"""

from __future__ import annotations

import subprocess
import tempfile
from typing import Any

__all__ = ["LeanFormalProver", "LeanProverError"]


class LeanProverError(RuntimeError):
    """Lean 调用基础设施错误。"""


class LeanFormalProver:
    """Lean 4 代码与契约定理证明器 CLI 适配器。"""

    def __init__(self, lean_executable: str = "lean") -> None:
        if not lean_executable:
            raise ValueError("lean_formal_prover: lean_executable must not be empty")
        self.lean_executable = lean_executable

    def verify_lean_code(
        self, code_snippet: str, *, timeout_sec: float = 10.0
    ) -> dict[str, Any]:
        """将 Lean 4 代码写入临时文件并调用 lean 编译器校验语义证明。

        Args:
            code_snippet: Lean 4 定理/证明代码。
            timeout_sec: 编译超时秒数。

        Returns:
            {"valid": bool, "returncode": int, "stdout": str, "stderr": str}
            （lean 缺失 / 超时同样返回 dict，valid=False，绝不 raise）

        Raises:
            LeanProverError: 临时文件写入失败。
        """
        if not code_snippet or not code_snippet.strip():
            raise LeanProverError("lean_formal_prover: code_snippet must not be empty")
        if timeout_sec <= 0:
            raise LeanProverError("lean_formal_prover: timeout_sec must be > 0")

        try:
            with tempfile.NamedTemporaryFile(suffix=".lean", mode="w", delete=True) as tmp:
                tmp.write(code_snippet)
                tmp.flush()

                try:
                    proc = subprocess.run(
                        [self.lean_executable, tmp.name],
                        capture_output=True,
                        text=True,
                        timeout=timeout_sec,
                    )
                except FileNotFoundError:
                    return {
                        "valid": False,
                        "returncode": -1,
                        "stdout": "",
                        "stderr": "Lean executable not found in PATH. Graceful degradation.",
                    }
                except subprocess.TimeoutExpired:
                    return {
                        "valid": False,
                        "returncode": -1,
                        "stdout": "",
                        "stderr": "Execution timed out.",
                    }
        except OSError as exc:
            raise LeanProverError(f"lean_formal_prover: cannot write temp file: {exc}") from exc

        is_valid = proc.returncode == 0 and "error:" not in proc.stderr
        return {
            "valid": is_valid,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
