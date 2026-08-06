"""obase.causal_graph_store — runtime component-dependency DAG (causal structure).

3O layer: obase (I/O and resources).
Maintains the directed acyclic graph (DAG) of microservices / task steps that
Phase 2 cognitive diagnosis operates on. Provides serialization, topological
ordering and graph-mutilation support for counterfactual inference.

Node attributes:
- ``p_fail``: unconditional failure probability (root node, no parents).
- ``cond_fail``: dict {tuple(parent states): fail_prob} — conditional failure
  probability given every combination of parent states (binary 0/1 states).

The store is deliberately dependency-light (networkx only) and never calls an
LLM — the causal structure is the system's ground truth, not a model's guess.
"""

from __future__ import annotations

import json
from typing import Any

import networkx as nx


class CausalGraphError(ValueError):
    """Raised on cyclic / structurally invalid causal graphs."""


class CausalGraphStore:
    """Directed acyclic causal graph with serialization + topology utilities.

    version: 结构版本号 —— add_node/add_edge 时自增, 供审计记录
    "当时用的是哪版因果图"。
    """

    def __init__(self) -> None:
        self._g: nx.DiGraph = nx.DiGraph()
        self.version: int = 1

    # ── 构建 ─────────────────────────────────────────────────────────
    def add_node(self, node: str, *, p_fail: float | None = None, cond_fail: dict | None = None, **attrs: Any) -> None:
        """Add a component node. Root nodes carry ``p_fail``; children carry
        ``cond_fail`` keyed by parent-state tuples (dict 或 JSON 序列化形态
        [[states, prob], ...] 均可)。"""
        if p_fail is not None:
            attrs["p_fail"] = float(p_fail)
        if cond_fail is not None:
            attrs["cond_fail"] = cond_fail
        cf = attrs.get("cond_fail")
        if cf is not None:
            if isinstance(cf, list):
                # JSON 序列化形态: [[父状态组合, 概率], ...]
                attrs["cond_fail"] = {tuple(k): float(v) for k, v in cf}
            else:
                attrs["cond_fail"] = {
                    tuple(k) if isinstance(k, list) else k: float(v) for k, v in cf.items()
                }
        self._g.add_node(node, **attrs)
        self.version += 1

    def add_edge(self, parent: str, child: str, **attrs: Any) -> None:
        """Direction: parent → child (parent causally precedes child)."""
        self._g.add_edge(parent, child, **attrs)
        if not nx.is_directed_acyclic_graph(self._g):
            self._g.remove_edge(parent, child)
            raise CausalGraphError(
                f"加入边 {parent}→{child} 会形成环 — 因果图必须是有向无环图 (DAG)"
            )
        self.version += 1

    # ── 查询 ─────────────────────────────────────────────────────────
    @property
    def graph(self) -> nx.DiGraph:
        return self._g

    def get_graph(self) -> nx.DiGraph:
        """Return the underlying networkx DiGraph (alias for ``graph``)."""
        return self._g

    def nodes(self) -> list[str]:
        return list(self._g.nodes)

    def edges(self) -> list[tuple[str, str]]:
        return list(self._g.edges)

    def parents(self, node: str) -> list[str]:
        return list(self._g.predecessors(node))

    def children(self, node: str) -> list[str]:
        return list(self._g.successors(node))

    def ancestors(self, node: str) -> set[str]:
        return set(nx.ancestors(self._g, node))

    def descendants(self, node: str) -> set[str]:
        return set(nx.descendants(self._g, node))

    def topological_sort(self) -> list[str]:
        """Deterministic topological order (causal execution order)."""
        return list(nx.topological_sort(self._g))

    def node_attr(self, node: str) -> dict[str, Any]:
        return dict(self._g.nodes[node])

    # ── 序列化 ───────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for k, v in attrs.items():
                if k == "cond_fail":
                    out[k] = [[list(kk), vv] for kk, vv in v.items()]  # [[父状态组合, 概率], ...] JSON 安全
                elif isinstance(v, tuple):
                    out[k] = list(v)
                else:
                    out[k] = v
            return out

        return {
            "nodes": {n: _clean(attrs) for n, attrs in self._g.nodes(data=True)},
            "edges": [[u, v] for u, v in self._g.edges],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def serialize(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict (alias of ``to_dict``)."""
        return self.to_dict()

    def deserialize(self, data: dict[str, Any] | str) -> "CausalGraphStore":
        """Load from a dict (or JSON string) produced by ``serialize``/``to_dict``."""
        if isinstance(data, str):
            data = json.loads(data)
        loaded = CausalGraphStore.from_dict(data)
        self._g = loaded._g
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CausalGraphStore":
        store = cls()
        for node, attrs in (data.get("nodes") or {}).items():
            store.add_node(node, **attrs)
        for u, v in data.get("edges") or []:
            store.add_edge(u, v)
        return store

    # ── 反事实支持: 图割裂 (Graph Mutilation) ───────────────────────
    def mutilated_copy(self, target_node: str) -> "CausalGraphStore":
        """Return a copy with ALL of ``target_node``'s incoming edges removed —
        the classic do-calculus Graph Mutilation. The target's own distribution
        is then forced by the intervention value (see oprim._do_calculus_intervention)."""
        if target_node not in self._g:
            raise KeyError(f"节点不存在: {target_node}")
        copy = CausalGraphStore()
        for node, attrs in self._g.nodes(data=True):
            copy.add_node(node, **attrs)
        for u, v, attrs in self._g.edges(data=True):
            if v == target_node:
                continue  # 割裂: 切断目标节点的所有入边
            copy.add_edge(u, v, **attrs)
        return copy

    def structural_paths(self, source: str, target: str, max_paths: int = 5) -> list[list[str]]:
        """All simple directed paths from source to target (causal paths)."""
        try:
            return [list(p) for p in nx.all_simple_paths(self._g, source, target)][:max_paths]
        except nx.NetworkXNoPath:
            return []


# ── 运行时单例: 供 O1 诊断事务兜底 ──────────────────────────────────
_RUNTIME_STORE: CausalGraphStore | None = None


def get_runtime_causal_store() -> CausalGraphStore:
    """Module-level runtime causal store (diagnosis fallback target).

    Components register their dependency topology into this store at
    startup; O1 diagnosis consumes it when no explicit store is passed.
    """
    global _RUNTIME_STORE
    if _RUNTIME_STORE is None:
        _RUNTIME_STORE = CausalGraphStore()
    return _RUNTIME_STORE
