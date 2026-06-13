"""Tests for obase.sympy_runtime — sandboxed SymPy execution."""

from __future__ import annotations

import time

import pytest

from obase.sympy_runtime import (
    EvalResult,
    RuntimeConfig,
    SymPyEvalError,
    SymPyMemoryError,
    SymPyRestrictedError,
    SymPyRuntime,
    SymPyRuntimeError,
    SymPyTimeoutError,
    diff,
    evaluate,
    get_runtime,
    integrate,
    latex,
    solve,
    simplify,
)


class TestRuntimeConfig:
    """Test RuntimeConfig defaults and frozen behavior."""

    def test_default_config(self) -> None:
        cfg = RuntimeConfig()
        assert cfg.timeout_seconds == 5.0
        assert cfg.max_memory_bytes == 64 * 1024 * 1024
        assert cfg.max_expression_depth == 50
        assert "sympy" in cfg.allowed_modules

    def test_custom_config(self) -> None:
        cfg = RuntimeConfig(timeout_seconds=2.0, max_expression_depth=10)
        assert cfg.timeout_seconds == 2.0
        assert cfg.max_expression_depth == 10

    def test_config_is_frozen(self) -> None:
        cfg = RuntimeConfig()
        with pytest.raises(Exception):
            cfg.timeout_seconds = 1.0  # type: ignore[misc]


class TestSymPyRuntime:
    """Core runtime tests."""

    def test_evaluate_basic(self) -> None:
        rt = SymPyRuntime()
        result = rt.evaluate("1 + 2")
        assert result.success is True
        assert result.value == 3

    def test_evaluate_symbolic(self) -> None:
        rt = SymPyRuntime()
        result = rt.evaluate("x**2", {"x": 3})
        assert result.success is True
        assert result.value == 9

    def test_evaluate_with_symbol(self) -> None:
        rt = SymPyRuntime()
        result = rt.evaluate("x + y", {"x": 2, "y": 3})
        assert result.success is True
        assert result.value == 5

    def test_evaluate_simplify(self) -> None:
        rt = SymPyRuntime()
        result = rt.evaluate("(x + 1)**2 - (x**2 + 2*x + 1)", {"x": 5})
        assert result.success is True
        assert result.value == 0

    def test_evaluate_simplify_disabled(self) -> None:
        rt = SymPyRuntime()
        result = rt.evaluate("1 + 2", simplify_result=False)
        assert result.success is True
        assert result.value == 3

    def test_evaluate_syntax_error(self) -> None:
        rt = SymPyRuntime()
        result = rt.evaluate("1 + * 2")
        assert result.success is False
        assert result.error is not None

    def test_evaluate_wall_time(self) -> None:
        rt = SymPyRuntime()
        result = rt.evaluate("1 + 1")
        assert result.wall_time_ms >= 0


class TestSandboxSecurity:
    """Security-focused tests for sandbox restrictions."""

    def test_forbid_import(self) -> None:
        rt = SymPyRuntime()
        with pytest.raises(SymPyRestrictedError, match="Import"):
            rt.evaluate("import os")

    def test_forbid_from_import(self) -> None:
        rt = SymPyRuntime()
        with pytest.raises(SymPyRestrictedError, match="Import from"):
            rt.evaluate("from os import path")

    def test_forbid_exec(self) -> None:
        rt = SymPyRuntime()
        with pytest.raises(SymPyRestrictedError, match="not allowed"):
            rt.evaluate("exec('print(1)')")

    def test_forbid_eval(self) -> None:
        rt = SymPyRuntime()
        with pytest.raises(SymPyRestrictedError, match="not allowed"):
            rt.evaluate("__import__('os')")

    def test_forbid_function_def(self) -> None:
        rt = SymPyRuntime()
        with pytest.raises(SymPyRestrictedError, match="not allowed"):
            rt.evaluate("def foo(): pass")

    def test_forbid_class_def(self) -> None:
        rt = SymPyRuntime()
        with pytest.raises(SymPyRestrictedError, match="not allowed"):
            rt.evaluate("class Foo: pass")

    def test_forbid_loop(self) -> None:
        rt = SymPyRuntime()
        with pytest.raises(SymPyRestrictedError, match="not allowed"):
            rt.evaluate("for i in range(10): pass")

    def test_forbid_private_attribute(self) -> None:
        rt = SymPyRuntime()
        with pytest.raises(SymPyRestrictedError, match="Private attribute"):
            rt.evaluate("x.__class__")

    def test_depth_limit(self) -> None:
        cfg = RuntimeConfig(max_expression_depth=5)
        rt = SymPyRuntime(cfg)
        # Nested binops create deep AST: ((((...1+1)...)+1)+1)
        expr = "+".join(["1"] * 20)
        with pytest.raises(SymPyRestrictedError, match="depth"):
            rt.evaluate(expr)

    def test_string_length_limit(self) -> None:
        cfg = RuntimeConfig(max_string_length=10)
        rt = SymPyRuntime(cfg)
        with pytest.raises(SymPyRestrictedError, match="length"):
            rt.evaluate("a" * 100)


class TestSolveEquation:
    """Tests for equation solving."""

    def test_solve_linear(self) -> None:
        rt = SymPyRuntime()
        result = rt.solve_equation("2*x - 4", "x")
        assert result.success is True
        assert result.value == [2]

    def test_solve_quadratic(self) -> None:
        rt = SymPyRuntime()
        result = rt.solve_equation("x**2 - 4", "x")
        assert result.success is True
        assert set(result.value) == {-2, 2}

    def test_solve_complex(self) -> None:
        rt = SymPyRuntime()
        result = rt.solve_equation("x**3 - 8", "x")
        assert result.success is True
        assert len(result.value) == 3


class TestDifferentiate:
    """Tests for differentiation."""

    def test_diff_power(self) -> None:
        rt = SymPyRuntime()
        result = rt.differentiate("x**3", "x")
        assert result.success is True
        from sympy import Symbol
        x = Symbol("x")
        assert result.value == 3 * x**2

    def test_diff_trig(self) -> None:
        rt = SymPyRuntime()
        result = rt.differentiate("sin(x)", "x")
        assert result.success is True
        from sympy import Symbol, cos
        x = Symbol("x")
        assert result.value == cos(x)

    def test_diff_second_order(self) -> None:
        rt = SymPyRuntime()
        result = rt.differentiate("x**4", "x", order=2)
        assert result.success is True
        from sympy import Symbol
        x = Symbol("x")
        assert result.value == 12 * x**2

    def test_diff_constant(self) -> None:
        rt = SymPyRuntime()
        result = rt.differentiate("5", "x")
        assert result.success is True
        assert result.value == 0


class TestIntegrate:
    """Tests for integration."""

    def test_integrate_power(self) -> None:
        rt = SymPyRuntime()
        result = rt.integrate_expr("x**2", "x")
        assert result.success is True
        from sympy import Symbol
        x = Symbol("x")
        assert result.value == x**3 / 3

    def test_integrate_definite(self) -> None:
        rt = SymPyRuntime()
        result = rt.integrate_expr("x**2", "x", 0, 1)
        assert result.success is True
        from sympy import Rational
        assert result.value == Rational(1, 3)

    def test_integrate_trig(self) -> None:
        rt = SymPyRuntime()
        result = rt.integrate_expr("sin(x)", "x")
        assert result.success is True
        from sympy import Symbol, cos
        x = Symbol("x")
        assert result.value == -cos(x)


class TestSimplify:
    """Tests for simplification."""

    def test_simplify_basic(self) -> None:
        rt = SymPyRuntime()
        result = rt.simplify_expr("(x + 1)**2 - (x**2 + 2*x + 1)")
        assert result.success is True
        assert result.value == 0

    def test_simplify_trig(self) -> None:
        rt = SymPyRuntime()
        result = rt.simplify_expr("sin(x)**2 + cos(x)**2")
        assert result.success is True
        assert result.value == 1


class TestToLatex:
    """Tests for LaTeX conversion."""

    def test_latex_basic(self) -> None:
        rt = SymPyRuntime()
        result = rt.to_latex("x**2")
        assert result.success is True
        assert "x^{2}" in result.result_str

    def test_latex_fraction(self) -> None:
        rt = SymPyRuntime()
        result = rt.to_latex("Rational(1, 2)")
        assert result.success is True
        assert "\\frac" in result.result_str


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_evaluate_function(self) -> None:
        result = evaluate("2 + 3")
        assert result.success is True
        assert result.value == 5

    def test_solve_function(self) -> None:
        result = solve("x - 5", "x")
        assert result.success is True
        assert result.value == [5]

    def test_diff_function(self) -> None:
        result = diff("x**2", "x")
        assert result.success is True
        from sympy import Symbol
        x = Symbol("x")
        assert result.value == 2 * x

    def test_integrate_function(self) -> None:
        result = integrate("x", "x")
        assert result.success is True
        from sympy import Symbol
        x = Symbol("x")
        assert result.value == x**2 / 2

    def test_simplify_function(self) -> None:
        result = simplify("(x + 1)**2 - x**2 - 2*x - 1")
        assert result.success is True
        assert result.value == 0

    def test_latex_function(self) -> None:
        result = latex("x**2 + y**2")
        assert result.success is True
        assert "x^{2}" in result.result_str


class TestGetRuntime:
    """Tests for get_runtime singleton."""

    def test_get_runtime_singleton(self) -> None:
        rt1 = get_runtime()
        rt2 = get_runtime()
        assert rt1 is rt2

    def test_get_runtime_custom_config(self) -> None:
        cfg = RuntimeConfig(timeout_seconds=10.0)
        rt = get_runtime(cfg)
        assert rt._config.timeout_seconds == 10.0


class TestTimeout:
    """Tests for timeout handling."""

    def test_timeout_config(self) -> None:
        cfg = RuntimeConfig(timeout_seconds=0.01)
        rt = SymPyRuntime(cfg)
        result = rt.evaluate("1 + 1")
        assert result.success is True


class TestEvalResult:
    """Tests for EvalResult model."""

    def test_eval_result_success(self) -> None:
        result = EvalResult(value=42, expr_str="40+2", result_str="42")
        assert result.success is True
        assert result.value == 42

    def test_eval_result_failure(self) -> None:
        result = EvalResult(
            value=None, expr_str="bad", result_str="", success=False, error="fail"
        )
        assert result.success is False
        assert result.error == "fail"

    def test_eval_result_wall_time(self) -> None:
        result = EvalResult(value=1, expr_str="1", result_str="1", wall_time_ms=5.5)
        assert result.wall_time_ms == 5.5
