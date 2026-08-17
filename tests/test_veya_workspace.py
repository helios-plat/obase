"""SpecKitPaths routing."""

from __future__ import annotations

from obase.veya_workspace import SpecKitPaths, TaskNode


def test_paths(tmp_path) -> None:
    paths = SpecKitPaths(tmp_path)
    assert paths.speckit_dir == tmp_path.resolve() / ".speckit"
    assert paths.taskgraph_path("g1").name == "taskgraph.json"


def test_task_node_defaults() -> None:
    node = TaskNode(id="T1", title="A", instruction="do A")
    assert node.status == "pending"
    assert node.depends_on == []


def test_intent_brief_defaults() -> None:
    from obase.intent_brief import IntentBrief

    brief = IntentBrief(interpretation="add foo")
    assert brief.action == "ask"
    assert brief.questions == []
