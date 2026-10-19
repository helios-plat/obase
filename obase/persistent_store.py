"""obase.persistent_store — 版本化资产存储：CausalGraph / ThreatProfile / StrategyState / CPD.

资产类型归 obase（SPEC §7.4：数据/状态类型归 obase，算法归 oprim/oskill）：
- CausalGraphDoc — 因果图（节点/边/权重/元数据），可版本化
- ThreatProfile  — 威胁签名（故障特征集合 + 严重度 + 缓解提示）
- StrategyState  — 策略状态（名称/先验权重/适用图/历史效果）
- CPD            — 条件概率分布表（node → {parents 组合 → P}）

存储语义（每类资产按 (kind, key) 管理）：
- 事件日志（JSONL append-only）→ 完整历史回放（history）
- 当前状态文件（root/current/<kind>/<key>.json）→ load_latest
- 目录级快照版本（复用 obase.versionstore.VersionStore）→ 按版本恢复
- rollback = 把目标版本的 doc 作为新版本写入（历史不可变，指针前移）

零反向依赖（obase 铁律）：不 import oprim/oskill/omodul。

例:
    >>> store = PersistentStore("/tmp/ps_demo")
    >>> rev = store.save("causal_graph", "core", CausalGraphDoc(nodes=["a","b"], edges=[("a","b")]).to_dict(),
    ...                   author="system", reason="init")
    >>> store.load_latest("causal_graph", "core")["nodes"]
    ['a', 'b']
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obase.versionstore import VersionStore, VersionStoreError

__all__ = [
    "CausalGraphDoc",
    "ThreatProfile",
    "StrategyState",
    "CPD",
    "PersistentStore",
    "PersistentStoreError",
    "validate_doc",
]

KINDS = ("causal_graph", "threat_profile", "strategy_state", "cpd")


class PersistentStoreError(RuntimeError):
    """版本化资产存储错误。"""


# ----------------------------------------------------------------------
# 资产类型（§7.4：类型归 obase）
# ----------------------------------------------------------------------


@dataclass
class CausalGraphDoc:
    """因果图资产。edges 为 (cause, effect) 列表；weights 键为 "u->v"。"""

    name: str
    nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodes": self.nodes,
            "edges": [[u, v] for u, v in self.edges],
            "weights": self.weights,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CausalGraphDoc":
        return cls(
            name=data["name"],
            nodes=list(data.get("nodes", [])),
            edges=[tuple(e) for e in data.get("edges", [])],
            weights=dict(data.get("weights", {})),
            meta=dict(data.get("meta", {})),
        )


@dataclass
class ThreatProfile:
    """威胁/故障签名资产。signature 为故障特征指纹集合（如 error_tag / 指标异常名）。"""

    profile_id: str
    signature: list[str] = field(default_factory=list)
    severity: str = "medium"  # low | medium | high | critical
    mitigations: list[str] = field(default_factory=list)
    observed_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "signature": self.signature,
            "severity": self.severity,
            "mitigations": self.mitigations,
            "observed_at": self.observed_at,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThreatProfile":
        return cls(
            profile_id=data["profile_id"],
            signature=list(data.get("signature", [])),
            severity=data.get("severity", "medium"),
            mitigations=list(data.get("mitigations", [])),
            observed_at=float(data.get("observed_at", time.time())),
            meta=dict(data.get("meta", {})),
        )


@dataclass
class StrategyState:
    """策略状态资产。priors 为能力 → 先验权重（如 {"rollback": 0.7}）。"""

    strategy_id: str
    name: str = ""
    priors: dict[str, float] = field(default_factory=dict)
    graph_ref: str | None = None
    effects: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "priors": self.priors,
            "graph_ref": self.graph_ref,
            "effects": self.effects,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyState":
        return cls(
            strategy_id=data["strategy_id"],
            name=data.get("name", ""),
            priors=dict(data.get("priors", {})),
            graph_ref=data.get("graph_ref"),
            effects=list(data.get("effects", [])),
            meta=dict(data.get("meta", {})),
        )


@dataclass
class CPD:
    """条件概率分布表资产。table 键为 parents 组合（如 "a=1,b=0"）→ P(node=1 | combo)。"""

    node: str
    parents: list[str] = field(default_factory=list)
    table: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "parents": self.parents,
            "table": self.table,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CPD":
        return cls(
            node=data["node"],
            parents=list(data.get("parents", [])),
            table={str(k): float(v) for k, v in data.get("table", {}).items()},
            meta=dict(data.get("meta", {})),
        )


def validate_doc(kind: str, doc: dict[str, Any]) -> None:
    """按资产类型做 schema 校验；非法抛 PersistentStoreError。"""
    if kind not in KINDS:
        raise PersistentStoreError(f"unknown asset kind: {kind!r} (valid: {KINDS})")
    if not isinstance(doc, dict):
        raise PersistentStoreError(f"{kind}: doc must be a dict")
    if kind == "causal_graph":
        if "name" not in doc:
            raise PersistentStoreError("causal_graph: missing 'name'")
    elif kind == "threat_profile":
        if "profile_id" not in doc:
            raise PersistentStoreError("threat_profile: missing 'profile_id'")
        if doc.get("severity", "medium") not in ("low", "medium", "high", "critical"):
            raise PersistentStoreError(f"threat_profile: bad severity {doc.get('severity')!r}")
    elif kind == "strategy_state":
        if "strategy_id" not in doc:
            raise PersistentStoreError("strategy_state: missing 'strategy_id'")
    elif kind == "cpd":
        if "node" not in doc:
            raise PersistentStoreError("cpd: missing 'node'")


# ----------------------------------------------------------------------
# 存储
# ----------------------------------------------------------------------


class PersistentStore:
    """版本化资产存储：事件日志 + 当前状态 + 快照版本，支持按版本回滚。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._current = self.root / "current"
        self._events = self.root / "events"
        self._vsn = VersionStore(self.root / "vsn")
        self._lock = threading.Lock()
        self._current.mkdir(parents=True, exist_ok=True)
        self._events.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def save(
        self,
        kind: str,
        key: str,
        doc: dict[str, Any],
        *,
        author: str = "system",
        reason: str = "",
    ) -> str:
        """保存资产为当前状态 + 新快照版本，返回 rev。"""
        validate_doc(kind, doc)
        with self._lock:
            current_file = self._current / kind / f"{key}.json"
            current_file.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(current_file, doc)

            event_file = self._events / kind / f"{key}.jsonl"
            event_file.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": time.time(),
                "author": author,
                "reason": reason,
                "doc": doc,
            }
            with event_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

            rev = self._vsn.snapshot(
                [current_file], message=f"{kind}:{key}:{reason or 'update'}"
            )
            return rev

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def load_latest(self, kind: str, key: str) -> dict[str, Any] | None:
        """读取当前最新版（None = 不存在）。"""
        current_file = self._current / kind / f"{key}.json"
        if not current_file.exists():
            return None
        with current_file.open(encoding="utf-8") as f:
            return json.load(f)

    def load_version(self, kind: str, key: str, rev: str) -> dict[str, Any] | None:
        """读取指定快照版本（None = rev 不存在或与资产无关）。"""
        meta = self._vsn.get(rev)
        if meta is None:
            return None
        marker = f"{kind}/{key}.json"
        if not any(marker in p for p in meta.get("paths", [])):
            return None
        with tempfile.TemporaryDirectory(prefix="ps_restore_") as tmp:
            self._vsn.restore(rev, target_root=tmp)
            for item in Path(tmp).iterdir():
                if item.is_file() and item.name.endswith(f"-{key}.json"):
                    with item.open(encoding="utf-8") as f:
                        return json.load(f)
        return None

    def list_versions(self, kind: str, key: str) -> list[dict[str, Any]]:
        """该资产的全部版本元数据（时间倒序）。"""
        marker = f"{kind}/{key}.json"
        return [
            v for v in self._vsn.list_versions()
            if any(marker in p for p in v.get("paths", []))
        ]

    def history(self, kind: str, key: str) -> list[dict[str, Any]]:
        """事件日志回放（时间正序，含作者/原因/完整 doc）。"""
        event_file = self._events / kind / f"{key}.jsonl"
        if not event_file.exists():
            return []
        out: list[dict[str, Any]] = []
        with event_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:  # pragma: no cover - 防御
                    continue
        return out

    # ------------------------------------------------------------------
    # 回滚
    # ------------------------------------------------------------------

    def rollback(
        self,
        kind: str,
        key: str,
        to_rev: str,
        *,
        author: str = "system",
        reason: str = "rollback",
    ) -> str:
        """回滚到指定版本：把该版本的 doc 作为新版本写入（历史不可变）。

        Returns:
            新版本的 rev。
        """
        doc = self.load_version(kind, key, to_rev)
        if doc is None:
            raise PersistentStoreError(
                f"rollback: version {to_rev!r} not found for {kind}:{key}"
            )
        return self.save(kind, key, doc, author=author, reason=reason)

    @staticmethod
    def _atomic_write(path: Path, doc: dict[str, Any]) -> None:
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, default=str)
        tmp.replace(path)
