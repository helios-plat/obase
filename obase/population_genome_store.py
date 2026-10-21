"""obase.population_genome_store — 种群基因库：管理多个并行的 Agent 工作流变体.

职责:
- 用 networkx DAG 序列化表示每个工作流变体
- 记录每个变体的历史执行次数与 O3 稠密奖励得分
- 提供种群快照、持久化存储、末位淘汰
- 为演化自适应提供基因池基础设施

零反向依赖: 不 import oprim/oskill/omodul.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

__all__ = ["PopulationGenomeStore", "GenomeRecord", "PopulationSnapshot"]


@dataclass
class GenomeRecord:
    """单个工作流变体的基因记录.

    Attributes:
        genome_id: 唯一标识
        dag_json: networkx DAG 的 JSON 序列化
        parent_ids: 父代 genome_id 列表（用于追踪演化谱系）
        birth_generation: 诞生代数
        total_executions: 累计执行次数
        reward_history: [(timestamp, score), ...] 历史奖励记录
        last_score: 最近一次评分
        is_active: 是否活跃（被淘汰的标记为 False）
        metadata: 额外元数据
    """

    genome_id: str
    dag_json: str
    parent_ids: list[str] = field(default_factory=list)
    birth_generation: int = 0
    total_executions: int = 0
    reward_history: list[tuple[float, float]] = field(default_factory=list)
    last_score: float = 0.0
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_reward(self, score: float) -> None:
        """记录一次执行奖励."""
        self.reward_history.append((time.time(), score))
        self.total_executions += 1
        self.last_score = score

    def to_dict(self) -> dict[str, Any]:
        return {
            "genome_id": self.genome_id,
            "dag_json": self.dag_json,
            "parent_ids": self.parent_ids,
            "birth_generation": self.birth_generation,
            "total_executions": self.total_executions,
            "reward_history": self.reward_history,
            "last_score": self.last_score,
            "is_active": self.is_active,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GenomeRecord:
        return cls(
            genome_id=d["genome_id"],
            dag_json=d["dag_json"],
            parent_ids=d.get("parent_ids", []),
            birth_generation=d.get("birth_generation", 0),
            total_executions=d.get("total_executions", 0),
            reward_history=d.get("reward_history", []),
            last_score=d.get("last_score", 0.0),
            is_active=d.get("is_active", True),
            metadata=d.get("metadata", {}),
        )


@dataclass
class PopulationSnapshot:
    """种群快照."""
    generation: int
    timestamp: float
    active_count: int
    total_count: int
    genomes: list[GenomeRecord]
    top_performer: GenomeRecord | None
    stats: dict[str, float] = field(default_factory=dict)


class PopulationGenomeStore:
    """种群基因库.

    管理多个并行的 Agent 工作流变体，每个变体表示为一个 networkx DAG。
    支持种群快照、持久化、谱系追踪。
    """

    def __init__(self, max_population: int = 20) -> None:
        self.max_population = max_population
        self._genomes: dict[str, GenomeRecord] = {}
        self._generation: int = 0

    # ------------------------------------------------------------------
    # 基因组 CRUD
    # ------------------------------------------------------------------

    def add_genome(
        self,
        dag: nx.DiGraph,
        *,
        parent_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GenomeRecord:
        """向种群添加一个新的工作流变体.

        Args:
            dag: 工作流 DAG
            parent_ids: 父代 ID 列表
            metadata: 元数据

        Returns:
            GenomeRecord
        """
        genome_id = uuid.uuid4().hex[:12]
        record = GenomeRecord(
            genome_id=genome_id,
            dag_json=json.dumps(nx.node_link_data(dag), ensure_ascii=False),
            parent_ids=parent_ids or [],
            birth_generation=self._generation,
            metadata=metadata or {},
        )
        self._genomes[genome_id] = record
        self._enforce_population_limit()
        return record

    def get_genome(self, genome_id: str) -> GenomeRecord | None:
        """获取基因组."""
        return self._genomes.get(genome_id)

    def get_dag(self, genome_id: str) -> nx.DiGraph | None:
        """反序列化基因组为 networkx DAG."""
        record = self._genomes.get(genome_id)
        if record is None:
            return None
        try:
            data = json.loads(record.dag_json)
            return nx.node_link_graph(data)
        except Exception:
            return None

    def record_reward(self, genome_id: str, score: float) -> bool:
        """记录一次执行奖励."""
        record = self._genomes.get(genome_id)
        if record is None:
            return False
        record.record_reward(score)
        return True

    def deactivate(self, genome_id: str) -> bool:
        """淘汰（停用）一个基因组."""
        record = self._genomes.get(genome_id)
        if record is None:
            return False
        record.is_active = False
        return True

    def remove(self, genome_id: str) -> bool:
        """物理删除一个基因组."""
        if genome_id in self._genomes:
            del self._genomes[genome_id]
            return True
        return False

    # ------------------------------------------------------------------
    # 种群查询
    # ------------------------------------------------------------------

    def list_active(self) -> list[GenomeRecord]:
        """列出所有活跃基因组."""
        return [g for g in self._genomes.values() if g.is_active]

    def list_all(self) -> list[GenomeRecord]:
        """列出所有基因组."""
        return list(self._genomes.values())

    def top_performers(self, n: int = 3) -> list[GenomeRecord]:
        """按最近评分排序的 Top N."""
        active = self.list_active()
        active.sort(key=lambda g: g.last_score, reverse=True)
        return active[:n]

    def bottom_performers(self, n: int = 3) -> list[GenomeRecord]:
        """按最近评分排序的 Bottom N."""
        active = self.list_active()
        active.sort(key=lambda g: g.last_score)
        return active[:n]

    def snapshot(self) -> PopulationSnapshot:
        """生成种群快照."""
        active = self.list_active()
        all_genomes = self.list_all()
        top = active[0] if active else None
        scores = [g.last_score for g in active]
        return PopulationSnapshot(
            generation=self._generation,
            timestamp=time.time(),
            active_count=len(active),
            total_count=len(all_genomes),
            genomes=all_genomes,
            top_performer=top,
            stats={
                "mean_score": sum(scores) / len(scores) if scores else 0.0,
                "max_score": max(scores) if scores else 0.0,
                "min_score": min(scores) if scores else 0.0,
            },
        )

    # ------------------------------------------------------------------
    # 世代管理
    # ------------------------------------------------------------------

    def advance_generation(self) -> int:
        """推进一个世代."""
        self._generation += 1
        return self._generation

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def population_size(self) -> int:
        return len(self._genomes)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self._generation,
            "max_population": self.max_population,
            "genomes": [g.to_dict() for g in self._genomes.values()],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PopulationGenomeStore:
        store = cls(max_population=data.get("max_population", 20))
        store._generation = data.get("generation", 0)
        for gd in data.get("genomes", []):
            record = GenomeRecord.from_dict(gd)
            store._genomes[record.genome_id] = record
        return store

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _enforce_population_limit(self) -> None:
        """超限时淘汰最低分 inactive 基因组."""
        if len(self._genomes) <= self.max_population:
            return
        inactive = [g for g in self._genomes.values() if not g.is_active]
        for g in inactive[: len(self._genomes) - self.max_population]:
            del self._genomes[g.genome_id]
        # 如果还不够，淘汰最低分 active
        while len(self._genomes) > self.max_population:
            active = self.list_active()
            if not active:
                break
            worst = min(active, key=lambda g: g.last_score)
            worst.is_active = False
            del self._genomes[worst.genome_id]

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "generation": self._generation,
            "population_size": self.population_size,
            "active_count": len(self.list_active()),
            "max_population": self.max_population,
        }
