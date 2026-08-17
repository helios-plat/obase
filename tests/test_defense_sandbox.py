"""PathJail + ProcessJail + loop_breaker + token_counter."""

from __future__ import annotations

import sys
from contextvars import copy_context

import pytest

from obase.loop_breaker import BreakerState, get_breaker, init_breaker, reset_breaker
from obase.sandbox import PathJail, ProcessJail
from obase.token_counter import token_counter


def test_path_jail_allows_inside(tmp_path) -> None:
    jail = PathJail(tmp_path)
    target = tmp_path / "a" / "b.txt"
    target.parent.mkdir()
    target.write_text("ok", encoding="utf-8")
    assert jail.resolve_and_verify("a/b.txt") == target.resolve()


def test_path_jail_blocks_dotdot(tmp_path) -> None:
    jail = PathJail(tmp_path)
    with pytest.raises(PermissionError, match="escape"):
        jail.resolve_and_verify("../secret")


def test_path_jail_blocks_absolute_escape(tmp_path) -> None:
    jail = PathJail(tmp_path)
    with pytest.raises(PermissionError, match="escape"):
        jail.resolve_and_verify("/etc/passwd")


def test_path_jail_does_not_prefix_match(tmp_path) -> None:
    jail = PathJail(tmp_path / "work")
    (tmp_path / "work").mkdir()
    (tmp_path / "workevil").mkdir()
    with pytest.raises(PermissionError):
        jail.resolve_and_verify(str(tmp_path / "workevil" / "x"))


def test_process_jail_runs_argv(tmp_path) -> None:
    jail = ProcessJail(tmp_path, timeout_s=10)
    code, out, err = jail.run([sys.executable, "-c", "print('jail-ok')"])
    assert code == 0
    assert "jail-ok" in out
    assert err == ""


def test_process_jail_timeout(tmp_path) -> None:
    jail = ProcessJail(tmp_path, timeout_s=1)
    code, out, err = jail.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert code == 124
    assert "timed out" in err


def test_process_jail_rejects_cwd_escape(tmp_path) -> None:
    jail = ProcessJail(tmp_path)
    with pytest.raises(PermissionError):
        jail.run([sys.executable, "-c", "print(1)"], cwd="..")


def test_loop_breaker_context_is_isolated() -> None:
    assert get_breaker() is None
    token = init_breaker()
    try:
        state = get_breaker()
        assert isinstance(state, BreakerState)
        state.total_steps = 7

        def other() -> int:
            inner = init_breaker()
            try:
                other_state = get_breaker()
                assert other_state is not None
                assert other_state.total_steps == 0
                return other_state.total_steps
            finally:
                reset_breaker(inner)

        ctx = copy_context()
        assert ctx.run(other) == 0
        assert get_breaker() is not None
        assert get_breaker().total_steps == 7
    finally:
        reset_breaker(token)
    assert get_breaker() is None


def test_token_counter_empty_is_zero() -> None:
    assert token_counter("") == 0
    assert token_counter("abcd") == 1
