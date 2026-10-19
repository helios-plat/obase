"""Tests for Veya 前沿探索元素 — obase 层 (2 个).

Covers: smt_solver_adapter, lean_formal_prover.
"""

from __future__ import annotations

import importlib.util

import pytest


class TestSMTSolverAdapter:
    def test_z3_missing_graceful(self):
        if importlib.util.find_spec("z3") is not None:
            pytest.skip("z3 installed")
        from obase import SMTSolverAdapter

        a = SMTSolverAdapter()
        assert a.available is False
        r = a.check_satisfiability([{"name": "p", "type": "Bool"}], ["p"])
        assert r["status"] == "unavailable" and r["satisfiable"] is None
        assert a.health()["status"] == "degraded"

    def test_validation(self):
        from obase import SMTSolverAdapter

        with pytest.raises(ValueError):
            SMTSolverAdapter(timeout_ms=0)

    @pytest.mark.skipif(
        importlib.util.find_spec("z3") is None, reason="z3 not installed"
    )
    def test_sat_unsat(self):
        from obase import SMTSolverAdapter

        a = SMTSolverAdapter()
        r = a.check_satisfiability([{"name": "p", "type": "Bool"}], ["p"])
        assert r["status"] == "sat" and r["satisfiable"] is True
        assert r["model"] is not None
        r = a.check_satisfiability([{"name": "p", "type": "Bool"}], ["p", "Not(p)"])
        assert r["status"] == "unsat" and r["satisfiable"] is False

    @pytest.mark.skipif(
        importlib.util.find_spec("z3") is None, reason="z3 not installed"
    )
    def test_int_real_declarations(self):
        from obase import SMTSolverAdapter

        a = SMTSolverAdapter()
        r = a.check_satisfiability(
            [{"name": "x", "type": "Int"}],
            ["x > 3", "x < 5"],
        )
        assert r["status"] == "sat"

    @pytest.mark.skipif(
        importlib.util.find_spec("z3") is None, reason="z3 not installed"
    )
    def test_bad_constraint_error(self):
        from obase import SMTSolverAdapter

        a = SMTSolverAdapter()
        r = a.check_satisfiability([{"name": "p", "type": "Bool"}], ["p +"])
        assert r["status"] == "error"


class TestLeanFormalProver:
    def test_missing_binary_graceful(self):
        import shutil

        if shutil.which("lean") is not None:
            pytest.skip("lean installed")
        from obase import LeanFormalProver

        p = LeanFormalProver()
        r = p.verify_lean_code("theorem t : True := by trivial")
        assert r["valid"] is False and r["returncode"] == -1
        assert "Lean executable not found" in r["stderr"]

    def test_empty_code_rejected(self):
        from obase import LeanFormalProver, LeanProverError

        with pytest.raises(LeanProverError):
            LeanFormalProver().verify_lean_code("")

    def test_empty_executable_rejected(self):
        from obase import LeanFormalProver

        with pytest.raises(ValueError):
            LeanFormalProver(lean_executable="")
