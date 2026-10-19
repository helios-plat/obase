"""3O 范式内化 — obase 基建测试 (Graft/OpenRSI/ReasoningBank)."""

from __future__ import annotations

from obase import (
    GraphNode,
    GraphRelation,
    LocalSandboxRunner,
    MarkdownGraphStore,
    MemoryBank,
    MemoryItem,
    TrajectoryEntry,
    append_trajectory,
    load_trajectories,
)
from obase.graph_storage import MarkdownGraphStore as _MGS
from obase.sandbox_runner import SandboxResult

# ---------------------------------------------------------------------------
# Graft: graph_storage
# ---------------------------------------------------------------------------


def test_graph_node_roundtrip(tmp_path):
    store = MarkdownGraphStore(tmp_path / ".veya" / "graph")
    node = GraphNode(
        node_id="auth_service_core",
        file_path="src/services/auth.ts",
        content_hash="sha256:abc",
        summary="JWT 鉴权核心逻辑",
        crux="if (isExpired(token)) { return refreshToken(token); }",
        relations=[
            GraphRelation("db_connection_pool"),
            GraphRelation("user_controller", "part_of"),
        ],
    )
    path = store.save_node(node)
    md = path.read_text(encoding="utf-8")
    assert "[[db_connection_pool]]" in md
    assert "[[user_controller]]" in md

    loaded = store.load_node("auth_service_core")
    assert loaded is not None
    assert loaded.summary == "JWT 鉴权核心逻辑"
    assert loaded.crux == "if (isExpired(token)) { return refreshToken(token); }"
    assert loaded.relations[0].target == "db_connection_pool"
    assert loaded.relations[1].type == "part_of"


def test_graph_hash_cache_zero_cost_skip(tmp_path):
    store = MarkdownGraphStore(tmp_path / ".veya" / "graph")
    h1 = _MGS.hash_content(b"code v1")
    assert store.check_hash("node_a", h1) is False  # 首次必变
    node = GraphNode(node_id="node_a", file_path="a.py", content_hash=h1)
    store.save_node(node)
    assert store.check_hash("node_a", h1) is True  # 未变 → 0 成本跳过
    assert store.check_hash("node_a", _MGS.hash_content(b"code v2")) is False


# ---------------------------------------------------------------------------
# OpenRSI: sandbox_runner / trajectory_logger
# ---------------------------------------------------------------------------


async def test_local_sandbox_runner_success(tmp_path):
    runner = LocalSandboxRunner()
    result = await runner.execute(str(tmp_path), "echo sandbox-ok")
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert "sandbox-ok" in result.stdout
    assert result.timed_out is False


async def test_local_sandbox_runner_timeout(tmp_path):
    runner = LocalSandboxRunner()
    result = await runner.execute(str(tmp_path), "sleep 5", timeout_sec=1)
    assert result.timed_out is True
    assert result.exit_code == -1


def test_trajectory_logger_roundtrip(tmp_path):
    entry = TrajectoryEntry(
        task_id="TASK-8921",
        branch_id="branch_2",
        operator_used="Evo_Debug",
        input_code="def f(): pass",
        error_trace="AssertionError at auth.test.ts:42",
        output_code="def f(): return 1",
        sandbox_result={
            "exit_code": 0,
            "tests_passed": 12,
            "tests_failed": 0,
            "execution_time_ms": 1420,
        },
    )
    path = append_trajectory(entry, path=tmp_path / "trajectories.jsonl")
    assert path.exists()
    loaded = load_trajectories(path)
    assert len(loaded) == 1
    assert loaded[0]["operator_used"] == "Evo_Debug"
    assert loaded[0]["sandbox_result"]["tests_passed"] == 12


# ---------------------------------------------------------------------------
# ReasoningBank: memory_bank
# ---------------------------------------------------------------------------


async def test_memory_bank_add_and_keyword_search(tmp_path):
    bank = MemoryBank(str(tmp_path / "memory.db"))
    await bank.add(
        MemoryItem(
            memory_id="MEM-2026-004",
            context_description="MySQL 连接池死锁修复 (高并发)",
            failed_attempt={
                "action": "事务内直接调用 external_http_call()",
                "reason": "HTTP 阻塞占用连接, 锁等待超时",
            },
            successful_strategy={
                "action": "先异步 HTTP 再开事务",
                "reason": "缩短持锁时长",
            },
            context_vector=[0.5, 0.25],
        )
    )
    hits = await bank.search_experience("mysql connection pool deadlock", top_k=3)
    assert len(hits) == 1
    assert hits[0].memory_id == "MEM-2026-004"
    assert hits[0].successful_strategy["action"] == "先异步 HTTP 再开事务"
    assert await bank.count() == 1
    assert await bank.delete("MEM-2026-004") is True
    assert await bank.count() == 0


async def test_memory_bank_vector_search(tmp_path):
    bank = MemoryBank(str(tmp_path / "memory2.db"))
    await bank.add(
        MemoryItem(
            memory_id="m1",
            context_description="a",
            failed_attempt={"action": "x", "reason": "y"},
            successful_strategy={"action": "z", "reason": "w"},
            context_vector=[1.0, 0.0],
        )
    )
    hits = await bank.search_experience("unrelated", top_k=3, query_vector=[0.9, 0.1])
    assert len(hits) == 1  # 向量相似弥补关键词缺失
