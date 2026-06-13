"""obase.workflow_engine — DAG-based workflow execution engine.

Provides topological sort (layered, same-layer nodes run in parallel),
cycle detection, and execute with rollback/continue error strategies.

The engine is semantics-agnostic: node executors are injected as Callables.

Example:
    nodes = ["A", "B", "C"]
    edges = [("A", "B"), ("A", "C")]   # A → B, A → C
    layers = WorkflowEngine.topological_sort(nodes, edges)
    # layers == [["A"], ["B", "C"]]

    async def my_executor(node, upstream):
        return f"result-{node}"

    results = await WorkflowEngine.execute(
        layers=layers,
        node_executor=my_executor,
        on_error="rollback",
    )
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any, Callable


class CycleError(Exception):
    """Raised when the node graph contains a cycle."""


class WorkflowExecutionError(Exception):
    """Raised when a node fails and on_error='rollback'."""

    def __init__(self, failed_node: str, cause: Exception) -> None:
        super().__init__(f"Node {failed_node!r} failed: {cause}")
        self.failed_node = failed_node
        self.cause = cause


class WorkflowEngine:
    """DAG workflow execution engine."""

    @staticmethod
    def detect_cycle(nodes: list[str], edges: list[tuple[str, str]]) -> None:
        """Raise CycleError if the graph contains a directed cycle.

        Uses DFS with three-color marking (white/gray/black).
        """
        adj: dict[str, list[str]] = defaultdict(list)
        for src, dst in edges:
            adj[src].append(dst)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in nodes}

        def dfs(node: str) -> None:
            color[node] = GRAY
            for nxt in adj[node]:
                if color.get(nxt, WHITE) == GRAY:
                    raise CycleError(f"Cycle detected involving node {nxt!r}")
                if color.get(nxt, WHITE) == WHITE:
                    dfs(nxt)
            color[node] = BLACK

        for n in nodes:
            if color[n] == WHITE:
                dfs(n)

    @staticmethod
    def topological_sort(
        nodes: list[str], edges: list[tuple[str, str]]
    ) -> list[list[str]]:
        """Return nodes grouped into layers for parallel execution.

        Each layer contains nodes whose dependencies are all in earlier layers.
        Nodes within the same layer can execute concurrently.

        Raises:
            CycleError: if the graph contains a cycle.
        """
        WorkflowEngine.detect_cycle(nodes, edges)

        in_degree: dict[str, int] = {n: 0 for n in nodes}
        adj: dict[str, list[str]] = defaultdict(list)
        for src, dst in edges:
            adj[src].append(dst)
            in_degree[dst] = in_degree.get(dst, 0) + 1

        queue: deque[str] = deque(n for n in nodes if in_degree[n] == 0)
        layers: list[list[str]] = []

        while queue:
            layer = list(queue)
            layers.append(layer)
            queue.clear()
            for node in layer:
                for nxt in adj[node]:
                    in_degree[nxt] -= 1
                    if in_degree[nxt] == 0:
                        queue.append(nxt)

        if sum(len(l) for l in layers) != len(nodes):
            raise CycleError("Graph has a cycle — not all nodes were processed")

        return layers

    @staticmethod
    async def execute(
        layers: list[list[str]],
        node_executor: Callable[[str, dict[str, Any]], Any],
        *,
        on_error: str = "rollback",
        completed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute layers in order; nodes within a layer run concurrently.

        Parameters
        ----------
        layers:
            Output of topological_sort().
        node_executor:
            Async callable ``(node_id, upstream_outputs) -> result``.
            ``upstream_outputs`` is a dict of {node_id: result} for all
            previously completed nodes.
        on_error:
            ``"rollback"`` — raise WorkflowExecutionError on first failure.
            ``"continue"`` — skip failed nodes and continue.
        completed:
            Pre-seeded output dict (mutated in place and returned).

        Returns
        -------
        dict mapping node_id → result (or exception if on_error='continue').
        """
        if on_error not in ("rollback", "continue"):
            raise ValueError(f"on_error must be 'rollback' or 'continue', got {on_error!r}")

        outputs: dict[str, Any] = completed if completed is not None else {}

        async def _run_node(node: str) -> tuple[str, Any]:
            result = await node_executor(node, dict(outputs))
            return node, result

        for layer in layers:
            tasks = [asyncio.create_task(_run_node(n)) for n in layer]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for node, outcome in zip(layer, results):
                if isinstance(outcome, Exception):
                    if on_error == "rollback":
                        # Cancel remaining tasks
                        for t in tasks:
                            t.cancel()
                        raise WorkflowExecutionError(node, outcome)
                    else:
                        outputs[node] = outcome
                else:
                    node_id, result = outcome
                    outputs[node_id] = result

        return outputs
