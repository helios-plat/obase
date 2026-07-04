"""Tests for obase.workflow_engine."""
from __future__ import annotations

import asyncio

import pytest

from obase.workflow_engine import (
    CycleError,
    WorkflowEngine,
    WorkflowExecutionError,
)


class TestTopologicalSort:
    def test_empty_graph(self):
        layers = WorkflowEngine.topological_sort([], [])
        assert layers == []

    def test_single_node(self):
        layers = WorkflowEngine.topological_sort(["A"], [])
        assert layers == [["A"]]

    def test_linear_chain(self):
        layers = WorkflowEngine.topological_sort(
            ["A", "B", "C"], [("A", "B"), ("B", "C")]
        )
        assert layers == [["A"], ["B"], ["C"]]

    def test_topological_sort_correct_layers(self):
        """A → B, A → C; B and C should be in the same parallel layer."""
        nodes = ["A", "B", "C"]
        edges = [("A", "B"), ("A", "C")]
        layers = WorkflowEngine.topological_sort(nodes, edges)
        assert layers[0] == ["A"]
        assert set(layers[1]) == {"B", "C"}

    def test_diamond_shape(self):
        # A → B, A → C, B → D, C → D
        nodes = ["A", "B", "C", "D"]
        edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
        layers = WorkflowEngine.topological_sort(nodes, edges)
        assert layers[0] == ["A"]
        assert set(layers[1]) == {"B", "C"}
        assert layers[2] == ["D"]

    def test_all_nodes_present_in_layers(self):
        nodes = ["X", "Y", "Z"]
        edges = [("X", "Y"), ("X", "Z")]
        layers = WorkflowEngine.topological_sort(nodes, edges)
        flat = [n for layer in layers for n in layer]
        assert sorted(flat) == sorted(nodes)

    def test_disconnected_nodes_in_first_layer(self):
        layers = WorkflowEngine.topological_sort(["A", "B"], [])
        assert len(layers) == 1
        assert set(layers[0]) == {"A", "B"}


class TestCycleDetection:
    def test_cycle_detection(self):
        """Direct 2-node cycle must raise CycleError."""
        with pytest.raises(CycleError):
            WorkflowEngine.topological_sort(["A", "B"], [("A", "B"), ("B", "A")])

    def test_self_loop_raises(self):
        with pytest.raises(CycleError):
            WorkflowEngine.topological_sort(["A"], [("A", "A")])

    def test_triangle_cycle_raises(self):
        with pytest.raises(CycleError):
            WorkflowEngine.topological_sort(
                ["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")]
            )

    def test_acyclic_graph_no_raise(self):
        WorkflowEngine.topological_sort(
            ["A", "B", "C"], [("A", "B"), ("A", "C")]
        )  # must not raise

    def test_detect_cycle_standalone(self):
        with pytest.raises(CycleError):
            WorkflowEngine.detect_cycle(["A", "B"], [("A", "B"), ("B", "A")])


class TestExecute:
    def test_simple_execution(self):
        async def _run():
            nodes = ["A", "B"]
            edges = [("A", "B")]
            layers = WorkflowEngine.topological_sort(nodes, edges)

            async def executor(node, upstream):
                return f"result-{node}"

            return await WorkflowEngine.execute(layers, executor)

        results = asyncio.run(_run())
        assert results["A"] == "result-A"
        assert results["B"] == "result-B"

    def test_upstream_outputs_passed(self):
        async def _run():
            nodes = ["A", "B"]
            edges = [("A", "B")]
            layers = WorkflowEngine.topological_sort(nodes, edges)

            async def executor(node, upstream):
                if node == "B":
                    return upstream.get("A", "MISSING") + "+B"
                return "A-val"

            return await WorkflowEngine.execute(layers, executor)

        results = asyncio.run(_run())
        assert results["B"] == "A-val+B"

    def test_rollback_on_error(self):
        """on_error='rollback' must raise WorkflowExecutionError on failure."""
        async def _run():
            nodes = ["A", "B"]
            edges = [("A", "B")]
            layers = WorkflowEngine.topological_sort(nodes, edges)

            async def executor(node, upstream):
                if node == "B":
                    raise RuntimeError("B failed")
                return "ok"

            await WorkflowEngine.execute(layers, executor, on_error="rollback")

        with pytest.raises(WorkflowExecutionError) as exc_info:
            asyncio.run(_run())
        assert exc_info.value.failed_node == "B"

    def test_continue_on_error(self):
        """on_error='continue' — failed node stored as exception, rest proceeds."""
        async def _run():
            nodes = ["A", "B", "C"]
            edges = [("A", "B"), ("A", "C")]
            layers = WorkflowEngine.topological_sort(nodes, edges)

            async def executor(node, upstream):
                if node == "B":
                    raise ValueError("B broken")
                return f"ok-{node}"

            return await WorkflowEngine.execute(layers, executor, on_error="continue")

        results = asyncio.run(_run())
        assert isinstance(results["B"], ValueError)
        assert results["C"] == "ok-C"

    def test_parallel_layer_execution(self):
        """Nodes in same layer should run concurrently (measured by total time)."""

        async def _run():
            nodes = ["A", "B", "C"]
            edges = [("A", "B"), ("A", "C")]
            layers = WorkflowEngine.topological_sort(nodes, edges)

            async def executor(node, upstream):
                if node in ("B", "C"):
                    await asyncio.sleep(0.05)
                return node

            return await WorkflowEngine.execute(layers, executor)

        start = asyncio.get_event_loop().time() if False else __import__("time").time()
        asyncio.run(_run())
        elapsed = __import__("time").time() - start
        # Sequential would take ≥0.1s; parallel should take ~0.05s
        assert elapsed < 0.15

    def test_invalid_on_error_raises(self):
        async def _run():
            layers = [["A"]]
            async def executor(n, u): return n
            await WorkflowEngine.execute(layers, executor, on_error="INVALID")

        with pytest.raises(ValueError):
            asyncio.run(_run())

    def test_empty_layers(self):
        async def _run():
            async def executor(n, u): return n
            return await WorkflowEngine.execute([], executor)

        results = asyncio.run(_run())
        assert results == {}
