from __future__ import annotations

from obase.hierarchical_context import HierarchicalContextStore
from obase.orchestrator import (
    Check,
    CheckType,
    Edge,
    FileRunStateBackend,
    Node,
    Runbook,
    project_run_trajectory,
    runbook_goto,
    start_runbook,
)


def _passing_check_runner(check: Check, ctx: dict) -> dict:
    return {"passed": True}


def _failing_check_runner(check: Check, ctx: dict) -> dict:
    return {"passed": False, "message": "not ready"}


def _make_runbook(max_attempts: int = 1) -> Runbook:
    return Runbook(
        name="trajectory-test",
        initial="start",
        nodes={
            "start": Node(
                id="start",
                prompt="begin",
                before_transfer=[Check(type=CheckType.PREDICATE, payload={"expr": "True"})],
            ),
            "done": Node(id="done", prompt="finished"),
        },
        edges=[Edge(from_node="start", to_node="done", max_attempts=max_attempts)],
    )


class TestProjectRunTrajectory:
    def test_writes_l2_body_and_l0_abstract(self, tmp_path):
        rb = _make_runbook()
        start_runbook(rb, run_id="traj-1")
        runbook_goto(rb, "traj-1", "done", check_runner=_passing_check_runner)
        state = FileRunStateBackend().load("traj-1")

        store = HierarchicalContextStore(root=tmp_path)
        uri = project_run_trajectory(state, store)
        assert uri == "3o://user/veya/memories/trajectories/traj-1"
        assert store.exists(uri, "L2")
        assert store.exists(uri, "L0")
        body = store.read(uri, "L2")
        assert "traj-1" in body
        assert "done" in body
        abstract = store.read(uri, "L0")
        assert "completed" in abstract

    def test_custom_user_id_changes_uri(self, tmp_path):
        rb = _make_runbook()
        start_runbook(rb, run_id="traj-2")
        state = FileRunStateBackend().load("traj-2")
        store = HierarchicalContextStore(root=tmp_path)
        uri = project_run_trajectory(state, store, user_id="alice")
        assert uri == "3o://user/alice/memories/trajectories/traj-2"


class TestAutoProjectionOnTerminalState:
    def test_completed_run_triggers_projection_when_context_store_given(self, tmp_path):
        rb = _make_runbook()
        store = HierarchicalContextStore(root=tmp_path)
        start_runbook(rb, run_id="traj-3")
        result = runbook_goto(
            rb, "traj-3", "done", check_runner=_passing_check_runner, context_store=store
        )
        assert result["ok"] is True
        uri = "3o://user/veya/memories/trajectories/traj-3"
        assert store.exists(uri, "L2")

    def test_blocked_run_triggers_projection(self, tmp_path):
        rb = _make_runbook(max_attempts=1)
        store = HierarchicalContextStore(root=tmp_path)
        start_runbook(rb, run_id="traj-4")
        runbook_goto(rb, "traj-4", "done", check_runner=_failing_check_runner, context_store=store)
        result = runbook_goto(
            rb, "traj-4", "done", check_runner=_failing_check_runner, context_store=store
        )
        assert result.get("blocked") is True
        uri = "3o://user/veya/memories/trajectories/traj-4"
        assert store.exists(uri, "L2")
        assert "blocked" in store.read(uri, "L0")

    def test_non_terminal_transition_does_not_project(self, tmp_path):
        rb = Runbook(
            name="multi-hop",
            initial="a",
            nodes={
                "a": Node(id="a", prompt="a"),
                "b": Node(id="b", prompt="b"),
                "c": Node(id="c", prompt="c"),
            },
            edges=[Edge(from_node="a", to_node="b"), Edge(from_node="b", to_node="c")],
        )
        store = HierarchicalContextStore(root=tmp_path)
        start_runbook(rb, run_id="traj-5")
        result = runbook_goto(
            rb, "traj-5", "b", check_runner=_passing_check_runner, context_store=store
        )
        assert result["ok"] is True
        uri = "3o://user/veya/memories/trajectories/traj-5"
        assert store.exists(uri, "L2") is False

    def test_no_context_store_means_no_projection_attempt(self, tmp_path):
        """Default behavior (no context_store) doesn't touch hierarchical_context at all."""
        rb = _make_runbook()
        start_runbook(rb, run_id="traj-6")
        result = runbook_goto(rb, "traj-6", "done", check_runner=_passing_check_runner)
        assert result["ok"] is True

    def test_projection_failure_does_not_break_goto(self, tmp_path):
        rb = _make_runbook()
        start_runbook(rb, run_id="traj-7")

        class _BrokenStore:
            def write(self, *a, **kw):
                raise RuntimeError("disk full")

        result = runbook_goto(
            rb, "traj-7", "done", check_runner=_passing_check_runner, context_store=_BrokenStore()
        )
        assert result["ok"] is True
