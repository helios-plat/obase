from __future__ import annotations

import pytest

from obase.graph_storage import GraphNode, GraphRelation, MarkdownGraphStore


def test_markdown_graph_store_round_trip_upserts_and_orders_nodes(tmp_path):
    store = MarkdownGraphStore(tmp_path / "graph")
    store.save_node(
        GraphNode(
            node_id="zeta",
            file_path="src/zeta.py",
            content_hash="hash-z",
            summary="Zeta summaries stay readable",
            crux="cache --> safety with unusual text",
            relations=[GraphRelation("alpha"), GraphRelation("unit-test", "part_of")],
        )
    )
    store.save_node(GraphNode(node_id="alpha", summary="Alpha node", relations=[]))
    # The hash includes the full ID, so path-like IDs remain distinct.
    store.save_node(GraphNode(node_id="path/alpha", summary="Distinct path-like ID"))

    nodes = store.load_all()
    assert [node.node_id for node in nodes] == ["alpha", "path/alpha", "zeta"]
    restored = store.get_node("zeta")
    assert restored is not None
    assert restored.to_dict() == nodes[-1].to_dict()
    assert restored.crux == "cache --> safety with unusual text"
    assert [edge.to_dict() for edge in restored.relations] == [
        {"target": "alpha", "type": "depends_on"},
        {"target": "unit-test", "type": "part_of"},
    ]

    store.save_node(GraphNode(node_id="alpha", summary="updated"))
    assert len(store.load_all()) == 3
    assert store.get_node("alpha").summary == "updated"
    assert store.delete_node("alpha") is True
    assert store.delete_node("alpha") is False


def test_markdown_graph_store_ignores_plain_markdown_and_rejects_bad_metadata(tmp_path):
    root = tmp_path / "graph"
    root.mkdir()
    (root / "notes.md").write_text("# Unrelated note\n", encoding="utf-8")
    store = MarkdownGraphStore(root)
    assert store.load_all() == []
    (root / "bad.md").write_text(
        "<!-- obase-graph-node:v1:not-valid-base64 -->\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="invalid graph metadata"):
        store.load_all()
