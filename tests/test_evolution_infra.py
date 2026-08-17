"""ASTParser + GraphDBPool MVCC."""

from __future__ import annotations

import pytest

from obase.cocoindex.parser import ASTParser
from obase.graph_store.models import GraphDBPool, new_fact


def test_parser_functions_and_constants(tmp_path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("MAX = 3\n\ndef add(a, b):\n    return a + b\n", encoding="utf-8")
    rec = ASTParser().parse_source(path.read_text(encoding="utf-8"))
    assert rec["ok"] is True
    kinds = {n["kind"] for n in rec["nodes"]}
    assert "function" in kinds
    assert "constant" in kinds


@pytest.mark.asyncio
async def test_parse_file(tmp_path) -> None:
    path = tmp_path / "a.py"
    path.write_text("def f():\n    return 1\n", encoding="utf-8")
    rec = await ASTParser().parse_file(path)
    assert rec["ok"] is True
    assert rec["path"].endswith("a.py")


@pytest.mark.asyncio
async def test_graph_pool_archives_old() -> None:
    pool = GraphDBPool()
    first = new_fact("User", predicate="role", object_value="anon")
    await pool.upsert_and_archive(first, None)
    second = new_fact("User", predicate="role", object_value="admin")
    await pool.upsert_and_archive(second, first.node_id)
    assert pool.facts[first.node_id].status == "ARCHIVED"
    assert pool.facts[second.node_id].status == "ACTIVE"
    assert pool.find_active("User", predicate="role").object_value == "admin"
