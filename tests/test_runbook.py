from __future__ import annotations

import pytest

from obase.orchestrator import (
    Check,
    CheckType,
    Edge,
    Node,
    Runbook,
    StageContractViolation,
    register_dynamic_check,
    runbook_current,
    runbook_goto,
    runbook_history,
    start_runbook,
)


def _passing_check_runner(check: Check, ctx: dict) -> dict:
    return {"passed": True}


def _failing_check_runner(check: Check, ctx: dict) -> dict:
    return {"passed": False, "message": "not ready"}


def _make_runbook(max_attempts: int = 3) -> Runbook:
    return Runbook(
        name="test-loop",
        initial="start",
        nodes={
            "start": Node(
                id="start",
                prompt="begin",
                before_transfer=[Check(type=CheckType.PREDICATE, payload={"expr": "True"})],
            ),
            "plan": Node(id="plan", prompt="plan it"),
            "done": Node(id="done", prompt="finished"),
        },
        edges=[
            Edge(from_node="start", to_node="plan", max_attempts=max_attempts),
            Edge(from_node="plan", to_node="done", max_attempts=max_attempts),
        ],
    )


class TestRunbookLifecycle:
    def test_start_creates_running_state_at_initial_node(self):
        rb = _make_runbook()
        state = start_runbook(rb, run_id="r1")
        assert state.state == "running"
        assert state.current_node == "start"
        cur = runbook_current(rb, "r1")
        assert cur["prompt"] == "begin"
        assert cur["allowed_next"] == ["plan"]

    def test_goto_rejects_edge_not_in_runbook(self):
        rb = _make_runbook()
        start_runbook(rb, run_id="r2")
        result = runbook_goto(rb, "r2", "done", check_runner=_passing_check_runner)
        assert result["ok"] is False
        assert "no edge" in result["reason"]

    def test_goto_succeeds_and_reaches_terminal_completion(self):
        rb = _make_runbook()
        start_runbook(rb, run_id="r3")
        r1 = runbook_goto(rb, "r3", "plan", check_runner=_passing_check_runner)
        assert r1["ok"] is True
        assert r1["to"] == "plan"
        r2 = runbook_goto(rb, "r3", "done", check_runner=_passing_check_runner)
        assert r2["ok"] is True
        cur = runbook_current(rb, "r3")
        assert cur["node"] == "done"
        assert cur["state"] == "completed"
        history = runbook_history("r3")
        assert [h["to"] for h in history] == ["plan", "done"]

    def test_failing_blocking_check_keeps_run_at_current_node(self):
        rb = _make_runbook()
        start_runbook(rb, run_id="r4")
        result = runbook_goto(rb, "r4", "plan", check_runner=_failing_check_runner)
        assert result["ok"] is False
        assert result["stay_in"] == "start"
        cur = runbook_current(rb, "r4")
        assert cur["node"] == "start"

    def test_max_attempts_exceeded_blocks_run(self):
        rb = _make_runbook(max_attempts=2)
        start_runbook(rb, run_id="r5")
        runbook_goto(rb, "r5", "plan", check_runner=_failing_check_runner)
        runbook_goto(rb, "r5", "plan", check_runner=_failing_check_runner)
        result = runbook_goto(rb, "r5", "plan", check_runner=_failing_check_runner)
        assert result["ok"] is False
        assert result["blocked"] is True
        cur = runbook_current(rb, "r5")
        assert cur["state"] == "blocked"

    def test_resume_returns_same_state_when_runbook_unchanged(self):
        rb = _make_runbook()
        s1 = start_runbook(rb, run_id="r6")
        runbook_goto(rb, "r6", "plan", check_runner=_passing_check_runner)
        s2 = start_runbook(rb, run_id="r6", resume=True)
        assert s2.current_node == "plan"
        assert s2.run_id == s1.run_id

    def test_resume_refuses_on_runbook_hash_mismatch(self):
        rb = _make_runbook()
        start_runbook(rb, run_id="r7")
        changed = _make_runbook(max_attempts=99)
        with pytest.raises(StageContractViolation):
            start_runbook(changed, run_id="r7", resume=True)

    def test_dynamic_check_is_evaluated_on_next_goto(self):
        rb = _make_runbook()
        start_runbook(rb, run_id="r8")
        register_dynamic_check("r8", Check(type=CheckType.MANUAL, payload={}, blocking=True))
        result = runbook_goto(rb, "r8", "plan", check_runner=_failing_check_runner)
        assert result["ok"] is False
        assert len(result["evidence"]) >= 1
