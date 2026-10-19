"""Tests for the Veya/3O 42-element inventory — obase layer (10 elements).

Covers: docker_pool, git_worktree, cognitive_store, mcp_client, cost_tracker,
decision_logger, browser_runner, pseudo_anonymizer, version_store, plugin_loader.
"""

from __future__ import annotations

import asyncio
import pathlib
import tempfile

import pytest


# ---------------------------------------------------------------------------
# decision_logger — ContextVar 全局决策轨迹
# ---------------------------------------------------------------------------


class TestDecisionLogger:
    async def test_begin_record_end(self):
        from obase import begin_trail, end_trail, get_trail, record_decision

        trail = begin_trail(run_id="r1")
        assert get_trail() is trail
        record_decision(event="llm_call", model="m", cost_usd=0.01)
        assert len(trail.steps) == 1
        assert trail.steps[0]["event"] == "llm_call"
        assert end_trail() is trail
        assert get_trail() is None

    async def test_child_task_shares_same_trail_object(self):
        from obase import begin_trail, end_trail, record_decision

        trail = begin_trail(run_id="r2")
        await asyncio.gather(*(_record_in_task() for _ in range(5)))
        assert len(trail.steps) == 5  # ContextVar 继承：子 Task 共享同一对象
        end_trail()

    async def test_unbound_record_is_noop(self):
        from obase import record_decision

        record_decision(event="x")  # 不应抛


async def _record_in_task() -> None:
    from obase import record_decision

    record_decision(event="parallel")


# ---------------------------------------------------------------------------
# pseudo_anonymizer — SPEC §5.5.1
# ---------------------------------------------------------------------------


class TestPseudoAnonymizer:
    def test_deterministic_24hex(self):
        from obase import PseudoAnonymizer

        p = PseudoAnonymizer(salt="s")
        a, b = p.user("u_1"), p.user("u_1")
        assert a == b and len(a) == 24 and a != "u_1"

    def test_salt_changes_pseudonym(self):
        from obase import pseudo_anonymize

        assert pseudo_anonymize("x", salt="s1") != pseudo_anonymize("x", salt="s2")

    def test_empty_value_rejected(self):
        from obase import pseudo_anonymize

        with pytest.raises(ValueError):
            pseudo_anonymize("", salt="s")

    def test_payload_anonymization(self):
        from obase import PseudoAnonymizer

        p = PseudoAnonymizer(salt="s")
        out = p.anonymize_payload({"user_id": "u9", "keep": 1}, fields=["user_id"])
        assert out["user_id"] != "u9" and out["keep"] == 1


# ---------------------------------------------------------------------------
# plugin_loader — Python 沙箱插件
# ---------------------------------------------------------------------------


class TestPluginLoader:
    def test_load_and_call(self, tmp_path: pathlib.Path):
        from obase import PluginSandboxError, load_python_plugin

        p = tmp_path / "greet.py"
        p.write_text("# @name: greet\n# @version: 1.2.0\n\ndef main(name):\n    return f'hi {name}'\n")
        spec = load_python_plugin(p)
        assert spec.entry_points["main"]("x") == "hi x"
        assert spec.version == "1.2.0"
        assert spec.call("main", "y") == "hi y"

    def test_sandbox_blocks_os(self, tmp_path: pathlib.Path):
        from obase import PluginSandboxError, load_python_plugin

        p = tmp_path / "evil.py"
        p.write_text("import os\ndef main():\n    return os.getcwd()\n")
        with pytest.raises(PluginSandboxError, match="denied"):
            load_python_plugin(p)

    def test_sandbox_blocks_already_imported_module(self, tmp_path: pathlib.Path):
        # os 已在 sys.modules —— 校验 builtins.__import__ 拦截生效
        from obase import PluginSandboxError, load_python_plugin

        p = tmp_path / "evil2.py"
        p.write_text("import json, sys\ndef main():\n    return sys.version\n")
        with pytest.raises(PluginSandboxError, match="denied"):
            load_python_plugin(p)

    def test_allowed_modules_whitelist(self, tmp_path: pathlib.Path):
        from obase import load_python_plugin

        p = tmp_path / "ok.py"
        p.write_text("import json\ndef main():\n    return json.dumps([1])\n")
        spec = load_python_plugin(p)
        assert spec.entry_points["main"]() == "[1]"


# ---------------------------------------------------------------------------
# cognitive_store — MemoryChunk / SQLite 后端（PgVector 需 PG，跳过）
# ---------------------------------------------------------------------------


class TestCognitiveStoreSqlite:
    async def test_upsert_search_delete(self, tmp_path: pathlib.Path):
        from obase import MemoryChunk, SqliteMemoryStore

        store = SqliteMemoryStore(tmp_path / "mem.db", dim=4)
        await store.upsert(MemoryChunk(chunk_id="c1", content="hello", embedding=[1.0, 0, 0, 0]))
        await store.upsert(MemoryChunk(chunk_id="c2", content="bye", embedding=[0.0, 1.0, 0, 0]))
        hits = await store.search([1.0, 0, 0, 0], top_k=5)
        assert hits[0][0].chunk_id == "c1"
        assert hits[0][1] < 0.001
        assert await store.count() == 2
        got = await store.get("c2")
        assert got is not None and got.content == "bye"
        assert await store.delete("c2") is True
        assert await store.count() == 1

    async def test_dim_mismatch_rejected(self, tmp_path: pathlib.Path):
        from obase import MemoryChunk, SqliteMemoryStore

        store = SqliteMemoryStore(tmp_path / "mem2.db", dim=4)
        with pytest.raises(ValueError):
            await store.upsert(MemoryChunk(chunk_id="x", content="x", embedding=[1.0]))

    async def test_factory(self, tmp_path: pathlib.Path):
        from obase import make_memory_store

        store = await make_memory_store("sqlite", db_path=tmp_path / "m.db", dim=2)
        assert await store.count() == 0


# ---------------------------------------------------------------------------
# version_store — 快照 / 还原
# ---------------------------------------------------------------------------


class TestVersionStore:
    def test_snapshot_restore_list(self, tmp_path: pathlib.Path):
        from obase import VersionStore

        src = tmp_path / "src"
        src.mkdir()
        f = src / "a.txt"
        f.write_text("v1")
        vs = VersionStore(tmp_path / "vs")
        rev = vs.snapshot([f], message="m1")
        assert vs.latest()["rev"] == rev
        f.write_text("v2")
        target = tmp_path / "restore"
        vs.restore(rev, target_root=target)
        restored = [p for p in target.iterdir() if p.name.endswith("a.txt")]
        assert len(restored) == 1 and restored[0].read_text() == "v1"

    def test_snapshot_empty_rejected(self, tmp_path: pathlib.Path):
        from obase import VersionStore, VersionStoreError

        vs = VersionStore(tmp_path / "vs2")
        with pytest.raises(VersionStoreError):
            vs.snapshot([])

    def test_restore_unknown_rev(self, tmp_path: pathlib.Path):
        from obase import VersionStore, VersionStoreError

        vs = VersionStore(tmp_path / "vs3")
        with pytest.raises(VersionStoreError):
            vs.restore("rev-nope", target_root=tmp_path / "t")


# ---------------------------------------------------------------------------
# cost_tracker — ContextVar 全局计数器 (SPEC §5.6 C1)
# ---------------------------------------------------------------------------


class TestCostTrackerContextVar:
    async def test_bind_record(self):
        from obase import CostTracker, bind_cost_tracker, get_cost_tracker, record_cost

        assert get_cost_tracker() is None
        tracker = CostTracker(strict_pricing=False)
        bind_cost_tracker(tracker)
        assert get_cost_tracker() is tracker
        assert record_cost("llm", "p", "m", "in", 1000) == 0.0  # 无单价 + 非严格 → 0
        bind_cost_tracker(None)

    async def test_record_tokens_fallback_pricing(self):
        from obase import CostTracker, bind_cost_tracker, record_tokens

        tracker = CostTracker()
        bind_cost_tracker(tracker)
        cost = record_tokens("dashscope", "qwen-max", in_tokens=1000, out_tokens=1000)
        assert cost > 0 and abs(cost - tracker.total_usd) < 1e-9
        bind_cost_tracker(None)

    async def test_unbound_record_tokens_is_noop(self):
        from obase import record_tokens

        assert record_tokens("p", "m", in_tokens=1, out_tokens=1) == 0.0


# ---------------------------------------------------------------------------
# browser_runner — 无 playwright 时的明确错误（playwright 非 CI 必备）
# ---------------------------------------------------------------------------


class TestBrowserRunner:
    async def test_health_idle(self):
        from obase import BrowserRunner

        runner = BrowserRunner()
        assert runner.is_running is False
        assert runner.health()["status"] == "idle"


# ---------------------------------------------------------------------------
# docker_pool — 无 docker SDK 时的惰性错误（SDK 非基础依赖）
# ---------------------------------------------------------------------------


class TestDockerPool:
    async def test_lazy_docker_error_path(self):
        import importlib.util

        if importlib.util.find_spec("docker") is not None:
            pytest.skip("docker SDK installed — 该路径在无 SDK 环境验证")
        from obase import DockerPool, DockerPoolError

        pool = DockerPool(image="python:3.12-slim")
        with pytest.raises(DockerPoolError, match="docker SDK"):
            await pool.acquire()

    def test_max_size_validation(self):
        from obase import DockerPool

        with pytest.raises(ValueError):
            DockerPool(image="x", max_size=0)


# ---------------------------------------------------------------------------
# mcp_client — 已有元素复验
# ---------------------------------------------------------------------------


class TestMcpClient:
    def test_registry_roundtrip(self):
        from obase import McpClientRegistry

        class FakeHandle:
            async def list_tools(self):
                return []

            async def call_tool(self, name, args):
                return {}

        McpClientRegistry.register("t1", FakeHandle())
        assert McpClientRegistry.get("t1") is not None
        with pytest.raises(KeyError):
            McpClientRegistry.get("nope")


# ---------------------------------------------------------------------------
# git_worktree — 真实 git 仓库集成
# ---------------------------------------------------------------------------


class TestGitWorktree:
    async def test_add_list_remove(self, tmp_path: pathlib.Path):
        from obase import add_worktree, list_worktrees, remove_worktree
        from obase.git import run_git

        repo = tmp_path / "repo"
        repo.mkdir()
        result = await run_git(["init", "-b", "main"], cwd=repo)
        assert result.ok, result.stderr
        (repo / "f.txt").write_text("x")
        result = await run_git(["add", "."], cwd=repo)
        assert result.ok
        result = await run_git(["commit", "-m", "init", "--no-verify"], cwd=repo)
        assert result.ok, result.stderr

        wt = await add_worktree(repo=repo, branch="feat/parallel")
        assert wt.exists() and (wt / ".git").is_file()
        entries = await list_worktrees(repo=repo)
        assert any(e["path"] == str(wt) for e in entries)
        await remove_worktree(repo=repo, path=wt)
        assert not wt.exists()
