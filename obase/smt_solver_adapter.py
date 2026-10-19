"""obase.smt_solver_adapter — Z3 / SMT 求解器适配器基础设施.

职责:
- 为 oprim._z3_check_feasible 提供 Z3 求解器生命周期管理
- 惰性 import z3（未安装时给出明确错误）
- 封装求解器实例化与资源释放

零反向依赖: 不 import oprim/oskill/omodul.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["SMTSolverAdapter", "SMTSolverError", "SMTUnavailableError"]


class SMTSolverError(RuntimeError):
    """SMT 求解器错误."""


class SMTUnavailableError(SMTSolverError):
    """SMT 求解器不可用错误（z3 未安装）."""
    pass


class SMTSolverAdapter:
    """Z3 / SMT 求解器适配器.

    惰性加载 z3，未安装时不阻塞模块导入。
    """

    def __init__(self, *, timeout_ms: int = 5000) -> None:
        if timeout_ms <= 0:
            raise ValueError(f"timeout_ms must be > 0, got {timeout_ms!r}")
        self.timeout_ms = timeout_ms
        self._solver: Any = None
        self._z3_available: bool | None = None

    @property
    def z3_available(self) -> bool:
        """检查 z3 是否可用."""
        if self._z3_available is None:
            try:
                import z3  # noqa: F401
                self._z3_available = True
            except ImportError:
                self._z3_available = False
        return self._z3_available

    @property
    def available(self) -> bool:
        """Whether the z3 backend can actually be used."""
        return self.z3_available

    def create_solver(self) -> Any:
        """创建 Z3 Solver 实例.

        Returns:
            z3.Solver 实例

        Raises:
            SMTSolverError: z3 未安装
        """
        if not self.z3_available:
            raise SMTSolverError(
                "z3-solver is not installed. Run: pip install z3-solver"
            )
        import z3
        solver = z3.Solver()
        solver.set("timeout", self.timeout_ms)
        self._solver = solver
        return solver

    def check(self, *constraints: Any) -> str:
        """执行 SMT 可满足性检查.

        Args:
            constraints: z3 约束表达式

        Returns:
            "sat" | "unsat" | "unknown"
        """
        if not self.z3_available:
            return "unknown"
        import z3
        try:
            solver = self.create_solver()
            for c in constraints:
                solver.add(c)
            result = solver.check()
            if result == z3.sat:
                return "sat"
            elif result == z3.unsat:
                return "unsat"
            else:
                return "unknown"
        except Exception:
            return "unknown"

    def check_satisfiability(
        self, declarations: list[dict[str, Any]], assertions: list[str]
    ) -> dict[str, Any]:
        """Declarative SMT entry point.

        ``declarations`` describe symbols (``{"name": "p", "type": "Bool"}``);
        ``assertions`` are expression strings.  Returns a uniform
        ``{"status", "satisfiable", "model"}`` payload without ever raising
        for a missing backend.
        """
        if not self.z3_available:
            return {"status": "unavailable", "satisfiable": None, "model": None}
        import z3  # noqa: PLC0415

        try:
            solver = z3.Solver()
            solver.set("timeout", self.timeout_ms)
            declared: dict[str, Any] = {}
            for decl in declarations:
                name, type_ = decl.get("name"), decl.get("type")
                if type_ == "Bool":
                    declared[name] = z3.Bool(name)
                elif type_ == "Int":
                    declared[name] = z3.Int(name)
                elif type_ == "Real":
                    declared[name] = z3.Real(name)
                else:
                    raise ValueError(f"unsupported declaration type: {type_!r}")
            for expr in assertions:
                for token in sorted(declared, key=len, reverse=True):
                    expr = re.sub(rf"\b{token}\b", f"declared[{token!r}]", expr)
                # build via eval over the declared symbol namespace only
                solver.add(eval(expr, {"__builtins__": {}}, dict(declared)))  # noqa: S307
            result = solver.check()
        except (ValueError, TypeError, SyntaxError, NameError, z3.z3types.Z3Exception):
            return {"status": "error", "satisfiable": None, "model": None}
        if result == z3.sat:
            model = solver.model()
            return {
                "status": "sat",
                "satisfiable": True,
                "model": {d.name(): model.eval(d).as_long() for d in model.decls()},
            }
        if result == z3.unsat:
            return {"status": "unsat", "satisfiable": False, "model": None}
        return {"status": "unknown", "satisfiable": None, "model": None}

    def health(self) -> dict[str, Any]:
        """健康检查."""
        return {
            "status": "healthy" if self.z3_available else "degraded",
            "z3_available": self.z3_available,
            "timeout_ms": self.timeout_ms,
        }
