"""O1/O2/O3 obase 层测试: wfg_deadlock_detector, local_sandbox_pool, snapshot_store."""

from __future__ import annotations

from pathlib import Path

from obase.local_sandbox_pool import LocalSandboxPool, SandboxExecutionResult
from obase.snapshot_store import SnapshotStore
from obase.wfg_deadlock_detector import WaitForGraph

# ============================================================================
# WaitForGraph
# ============================================================================

class TestWaitForGraph:
    def test_init_empty(self):
        wfg = WaitForGraph()
        assert wfg.detect_cycles() == []

    def test_add_wait(self):
        wfg = WaitForGraph()
        wfg.add_wait("A", "B")
        assert "B" in wfg.graph["A"]

    def test_self_loop_ignored(self):
        wfg = WaitForGraph()
        wfg.add_wait("A", "A")
        assert "A" not in wfg.graph.get("A", set())

    def test_simple_cycle(self):
        wfg = WaitForGraph()
        wfg.add_wait("A", "B")
        wfg.add_wait("B", "A")
        cycles = wfg.detect_cycles()
        assert len(cycles) >= 1

    def test_three_node_cycle(self):
        wfg = WaitForGraph()
        wfg.add_wait("A", "B")
        wfg.add_wait("B", "C")
        wfg.add_wait("C", "A")
        cycles = wfg.detect_cycles()
        assert len(cycles) >= 1

    def test_remove_agent_cleans_both(self):
        wfg = WaitForGraph()
        wfg.add_wait("A", "B")
        wfg.add_wait("B", "C")
        wfg.remove_agent("B")
        assert "B" not in wfg.graph
        assert "B" not in wfg.graph.get("A", set())

    def test_resolve_deadlocks_kills_lowest_priority(self):
        wfg = WaitForGraph()
        wfg.set_priority("A", 100)
        wfg.set_priority("B", 50)
        wfg.set_priority("C", 10)
        wfg.add_wait("A", "B")
        wfg.add_wait("B", "C")
        wfg.add_wait("C", "A")
        victims = wfg.resolve_deadlocks()
        assert "C" in victims
        assert wfg.detect_cycles() == []

    def test_no_cycles_returns_empty(self):
        wfg = WaitForGraph()
        wfg.add_wait("A", "B")
        wfg.add_wait("B", "C")
        assert wfg.detect_cycles() == []

    def test_diamond_no_cycle(self):
        wfg = WaitForGraph()
        wfg.add_wait("A", "B")
        wfg.add_wait("A", "C")
        wfg.add_wait("B", "D")
        wfg.add_wait("C", "D")
        assert wfg.detect_cycles() == []


# ============================================================================
# LocalSandboxPool
# ============================================================================

class TestLocalSandboxPool:
    """D0 迁移: 断言对象 = Veya-lineage 唯一实现 (run_python + SandboxExecutionResult)。"""

    def test_run_python_returns_structured_result(self):
        result = LocalSandboxPool().run_python("print('hello')")
        assert isinstance(result, SandboxExecutionResult)
        assert result.exit_code == 0
        assert "hello" in result.stdout
        assert result.hostile is False

    def test_honeypot_read_is_hostile(self):
        result = LocalSandboxPool().run_python(
            "import os; os.environ.get('FAKE_TOKEN')", honeypot_keys=["FAKE_TOKEN"]
        )
        assert result.honeypot_access == ["FAKE_TOKEN"]
        assert result.hostile is True

    def test_network_attempt_is_forensically_flagged(self):
        result = LocalSandboxPool().run_python(
            "import socket; socket.socket().connect(('127.0.0.1', 9))"
        )
        assert result.network_attempt is True
        assert result.hostile is True

    def test_instance_timeout_marks_timed_out(self):
        result = LocalSandboxPool(timeout_s=0.5).run_python("import time; time.sleep(5)")
        assert result.timed_out is True
        assert result.exit_code == 124

    def test_timeout_plus_network_keeps_forensics(self):
        result = LocalSandboxPool(timeout_s=0.5).run_python(
            "import socket, time; socket.socket().connect(('10.255.255.1', 9)); time.sleep(5)"
        )
        assert result.timed_out is True
        assert result.network_attempt is True
        assert result.hostile is True

    def test_to_dict_shape(self):
        payload = LocalSandboxPool().run_python("print('x')").to_dict()
        assert set(payload) == {
            "exit_code",
            "stdout",
            "stderr",
            "honeypot_access",
            "network_attempt",
            "hostile",
            "duration_ms",
            "timed_out",
        }


# ============================================================================
# SnapshotStore
# ============================================================================

class TestSnapshotStore:
    def test_save_and_load(self, tmp_path: Path):
        store = SnapshotStore(str(tmp_path / "snaps"))
        meta = store.save("entity-1", {"key": "value"})
        assert meta.version == 1
        state = store.load("entity-1")
        assert state == {"key": "value"}

    def test_version_increment(self, tmp_path: Path):
        store = SnapshotStore(str(tmp_path / "snaps"))
        store.save("e1", {"v": 1})
        meta = store.save("e1", {"v": 2})
        assert meta.version == 2

    def test_load_specific_version(self, tmp_path: Path):
        store = SnapshotStore(str(tmp_path / "snaps"))
        store.save("e1", {"v": 1})
        store.save("e1", {"v": 2})
        state = store.load("e1", version=1)
        assert state == {"v": 1}

    def test_load_nonexistent(self, tmp_path: Path):
        store = SnapshotStore(str(tmp_path / "snaps"))
        assert store.load("ghost") is None

    def test_diff(self, tmp_path: Path):
        store = SnapshotStore(str(tmp_path / "snaps"))
        store.save("e1", {"a": 1, "b": 2})
        store.save("e1", {"a": 1, "b": 3, "c": 4})
        diff = store.diff("e1", 1, 2)
        assert "b" in diff["changed"]
        assert "c" in diff["added"]

    def test_list_versions(self, tmp_path: Path):
        store = SnapshotStore(str(tmp_path / "snaps"))
        store.save("e1", {"x": 0})
        store.save("e1", {"x": 1})
        store.save("e1", {"x": 2})
        versions = store.list_versions("e1")
        assert versions == [1, 2, 3]
