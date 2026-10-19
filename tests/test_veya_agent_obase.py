"""Tests for Veya 顶级 Agent 增强元素 — obase 层 (3 个).

Covers: treesitter_indexer, hitl_signal_bus, mcp_server.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

# ---------------------------------------------------------------------------
# treesitter_indexer（无 tree-sitter 时走 AST 回退路径）
# ---------------------------------------------------------------------------


class TestTreesitterIndexer:
    async def test_index_file_python_symbols(self, tmp_path: pathlib.Path):
        from obase import TreesitterIndexer

        p = tmp_path / "app.py"
        p.write_text(
            "import os\nfrom pathlib import Path\n\n"
            "def main(a, b=1):\n    return a\n\n"
            "class Foo:\n    def bar(self): pass\n"
        )
        idx = TreesitterIndexer()
        syms = await idx.index_file(p)
        names = {s.name for s in syms}
        assert {"main", "Foo", "bar", "os", "Path"} <= names
        main = next(s for s in syms if s.name == "main")
        assert main.kind == "function" and main.line == 4
        foo = next(s for s in syms if s.name == "Foo")
        assert foo.kind == "class"

    async def test_index_file_non_python_empty(self, tmp_path: pathlib.Path):
        from obase import TreesitterIndexer

        p = tmp_path / "x.unknown_ext"
        p.write_text("whatever")
        idx = TreesitterIndexer()
        assert await idx.index_file(p) == []

    async def test_index_tree(self, tmp_path: pathlib.Path):
        from obase import TreesitterIndexer

        (tmp_path / "a.py").write_text("import b\ndef alpha(): pass\n")
        (tmp_path / "b.py").write_text("class Beta: pass\n")
        (tmp_path / "skip.js").write_text("function hi() {}\n")
        idx = TreesitterIndexer()
        ci = await idx.index_tree(tmp_path)
        assert ci.symbol_count == 3  # b(import) + alpha + Beta
        assert ci.languages["python"] == 2
        assert "javascript" in ci.languages
        assert ci.symbol_count == len(ci.symbols)

    async def test_index_tree_ignores_venv(self, tmp_path: pathlib.Path):
        from obase import TreesitterIndexer

        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("def hidden(): pass\n")
        (tmp_path / "real.py").write_text("def real(): pass\n")
        idx = TreesitterIndexer()
        ci = await idx.index_tree(tmp_path)
        assert all(".venv" not in f for f in ci.files)
        assert ci.symbol_count == 1

    async def test_index_tree_missing_root(self, tmp_path: pathlib.Path):
        from obase import TreesitterIndexer

        with pytest.raises(FileNotFoundError):
            await TreesitterIndexer().index_tree(tmp_path / "nope")

    async def test_index_file_syntax_error_empty(self, tmp_path: pathlib.Path):
        from obase import AstFallbackIndexer

        p = tmp_path / "bad.py"
        p.write_text("def broken(:\n")
        assert await AstFallbackIndexer().index_file(p) == []


# ---------------------------------------------------------------------------
# hitl_signal_bus
# ---------------------------------------------------------------------------


class TestHitlSignalBus:
    async def test_approve_flow(self):
        from obase import HitlSignalBus

        bus = HitlSignalBus()
        rid = bus.request_approval(scope="checkout", summary="order-1")
        assert bus.approve(rid, note="ok") is True
        decision = await bus.wait_for_decision(rid, timeout=1.0)
        assert decision["outcome"] == "approved"
        assert decision["note"] == "ok"
        assert bus.approve(rid) is False  # 幂等

    async def test_reject_and_cancel(self):
        from obase import HitlSignalBus

        bus = HitlSignalBus()
        rid1 = bus.request_approval(scope="a", summary="s")
        rid2 = bus.request_approval(scope="b", summary="s")
        assert bus.reject(rid1) is True
        assert bus.cancel(rid2) is True
        d1 = await bus.wait_for_decision(rid1, timeout=1.0)
        d2 = await bus.wait_for_decision(rid2, timeout=1.0)
        assert d1["outcome"] == "rejected" and d2["outcome"] == "cancelled"

    async def test_timeout(self):
        from obase import HitlSignalBus

        bus = HitlSignalBus()
        rid = bus.request_approval(scope="x", summary="y")
        decision = await bus.wait_for_decision(rid, timeout=0.05)
        assert decision["outcome"] == "timed_out"
        # 超时后仍可继续等
        assert bus.approve(rid) is True
        decision = await bus.wait_for_decision(rid, timeout=1.0)
        assert decision["outcome"] == "approved"

    async def test_unknown_request(self):
        from obase import HitlSignalBus

        bus = HitlSignalBus()
        decision = await bus.wait_for_decision("nope", timeout=0.05)
        assert decision["outcome"] == "unknown"

    async def test_interrupt_signal(self):
        from obase import HitlSignalBus

        bus = HitlSignalBus()
        assert bus.interrupted is False
        bus.signal_interrupt(reason="user stop")
        assert bus.interrupted is True
        assert bus.interrupt_reason == "user stop"
        bus.reset_interrupt()
        assert bus.interrupted is False and bus.interrupt_reason == ""

    async def test_contextvar_binding(self):
        from obase import bind_bus, get_bus, interrupted, request_approval, signal_interrupt
        from obase.hitl_signal_bus import HitlSignalBus

        bus = HitlSignalBus()
        bind_bus(bus)
        assert get_bus() is bus
        rid = request_approval(scope="ctx", summary="s")
        assert bus.approve(rid)
        signal_interrupt(reason="stop")
        assert interrupted() is True
        bind_bus(None)

    async def test_child_task_shares_bus(self):
        from obase import bind_bus
        from obase.hitl_signal_bus import HitlSignalBus

        bus = HitlSignalBus()
        bind_bus(bus)

        async def child():
            await asyncio.sleep(0.01)
            bus.approve("shared")

        rid = bus.request_approval(scope="c", summary="s")
        await asyncio.gather(bus.wait_for_decision(rid, timeout=1.0), child())
        bind_bus(None)

    def test_health_and_pending(self):
        from obase.hitl_signal_bus import HitlSignalBus

        bus = HitlSignalBus()
        bus.request_approval(scope="s", summary="x")
        assert len(bus.list_pending()) == 1
        assert bus.health()["pending_approvals"] == 1


# ---------------------------------------------------------------------------
# mcp_server（已有元素 + 新增 list_tools / has_tool）
# ---------------------------------------------------------------------------


class TestMcpServer:
    async def test_register_and_list(self):
        from obase.mcp_server import MCPServer, SkillDef

        async def handler(args: dict) -> dict:
            return {"msg": f"hi {args.get('name')}"}

        server = MCPServer(name="veya", version="1.0.0")
        server.register_skill(
            SkillDef(
                name="veya.greet",
                description="Greet",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                handler=handler,
            )
        )
        assert server.has_tool("veya.greet") is True
        assert server.has_tool("nope") is False
        assert server.tool_names() == ["veya.greet"]
        listing = server.list_tools()
        assert listing[0]["description"] == "Greet"
        assert listing[0]["input_schema"]["required"] == ["name"]

    async def test_duplicate_registration_raises(self):
        from obase.mcp_server import MCPServer, MCPServerError, SkillDef

        async def h(args):
            return {}

        server = MCPServer(name="d", version="1")
        skill = SkillDef(
            name="d.t", description="t",
            input_schema={"type": "object", "properties": {}}, handler=h,
        )
        server.register_skill(skill)
        with pytest.raises(MCPServerError):
            server.register_skill(skill)
