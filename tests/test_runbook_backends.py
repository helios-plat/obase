"""RunStateBackend parity: the same Runbook scenarios must behave identically
on FileRunStateBackend and SqliteRunStateBackend — this is the "File / SQLite
两种 store 都能 round-trip" checklist item.
"""

from __future__ import annotations

import pytest

from obase.orchestrator import (
    Check,
    CheckType,
    Edge,
    FileRunStateBackend,
    Node,
    Runbook,
    SqliteRunStateBackend,
    StageContractViolation,
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
        name="backend-parity",
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


@pytest.fixture(params=["file", "sqlite"])
def backend_factory(request, tmp_path):
    """Returns a zero-arg factory producing a *fresh instance* pointed at the
    same underlying storage — this is what proves cross-process-style
    recovery (new object, same disk state), not just "works within one
    Python object's lifetime".
    """
    if request.param == "file":
        from obase.fs import FS

        FS.set_default_working_dir(tmp_path / "obase_work")
        yield FileRunStateBackend
        FS.reset_working_dir()
    else:
        db_path = tmp_path / "runs.db"
        yield lambda: SqliteRunStateBackend(db_path)


class TestBackendParity:
    def test_start_goto_roundtrip(self, backend_factory):
        rb = _make_runbook()
        backend = backend_factory()
        state = start_runbook(rb, run_id="r1", backend=backend)
        assert state.current_node == "start"

        result = runbook_goto(rb, "r1", "plan", check_runner=_passing_check_runner, backend=backend)
        assert result["ok"] is True

        cur = runbook_current(rb, "r1", backend=backend)
        assert cur["node"] == "plan"

    def test_failing_check_stays_and_records_evidence(self, backend_factory):
        rb = _make_runbook()
        backend = backend_factory()
        start_runbook(rb, run_id="r2", backend=backend)
        result = runbook_goto(rb, "r2", "plan", check_runner=_failing_check_runner, backend=backend)
        assert result["ok"] is False
        assert result["evidence"]
        cur = runbook_current(rb, "r2", backend=backend)
        assert cur["node"] == "start"

    def test_fresh_backend_instance_restores_exact_state(self, backend_factory):
        """New backend object (same storage) = the process-restart scenario."""
        rb = _make_runbook()
        backend1 = backend_factory()
        start_runbook(rb, run_id="r3", backend=backend1)
        runbook_goto(rb, "r3", "plan", check_runner=_passing_check_runner, backend=backend1)

        backend2 = backend_factory()
        cur = runbook_current(rb, "r3", backend=backend2)
        assert cur["node"] == "plan"
        history = runbook_history("r3", backend=backend2)
        assert len(history) == 1
        assert history[0]["to"] == "plan"

    def test_hash_mismatch_refuses_resume(self, backend_factory):
        rb = _make_runbook()
        backend = backend_factory()
        start_runbook(rb, run_id="r4", backend=backend)
        changed = _make_runbook(max_attempts=99)
        with pytest.raises(StageContractViolation):
            start_runbook(changed, run_id="r4", resume=True, backend=backend)

    def test_max_attempts_exceeded_blocks(self, backend_factory):
        rb = _make_runbook(max_attempts=2)
        backend = backend_factory()
        start_runbook(rb, run_id="r5", backend=backend)
        runbook_goto(rb, "r5", "plan", check_runner=_failing_check_runner, backend=backend)
        runbook_goto(rb, "r5", "plan", check_runner=_failing_check_runner, backend=backend)
        result = runbook_goto(rb, "r5", "plan", check_runner=_failing_check_runner, backend=backend)
        assert result["ok"] is False
        assert result["blocked"] is True
        cur = runbook_current(rb, "r5", backend=backend)
        assert cur["state"] == "blocked"

    def test_missing_run_raises_file_not_found(self, backend_factory):
        rb = _make_runbook()
        backend = backend_factory()
        with pytest.raises(FileNotFoundError):
            runbook_current(rb, "ghost-run", backend=backend)


class TestSqliteBackendSpecific:
    def test_exists_reflects_saved_runs(self, tmp_path):
        backend = SqliteRunStateBackend(tmp_path / "runs.db")
        assert backend.exists("x") is False
        rb = _make_runbook()
        start_runbook(rb, run_id="x", backend=backend)
        assert backend.exists("x") is True

    def test_two_instances_same_db_file_see_each_others_writes(self, tmp_path):
        db_path = tmp_path / "runs.db"
        b1 = SqliteRunStateBackend(db_path)
        rb = _make_runbook()
        start_runbook(rb, run_id="y", backend=b1)

        b2 = SqliteRunStateBackend(db_path)
        state = b2.load("y")
        assert state is not None
        assert state.current_node == "start"

    def test_default_db_path_uses_three_o_run_state_dir_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("THREE_O_RUN_STATE_DIR", str(tmp_path / "custom"))
        backend = SqliteRunStateBackend()
        assert backend.db_path == tmp_path / "custom" / "runs.db"
