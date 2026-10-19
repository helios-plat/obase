"""obase 基础设施层：基于内存的有向图死锁检测器。不依赖任何 3O 上层模块。"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set


class WaitForGraph:
    """内存有向等待图 —— 死锁检测基础设施.

    纯数据结构封装，零反向依赖。
    - 节点: agent_id (str)
    - 有向边: waiter → holder
    - 环检测: DFS 回溯法
    - 优先级: 数值越大优先级越高
    """

    def __init__(self) -> None:
        self.graph: Dict[str, Set[str]] = defaultdict(set)
        self.priorities: Dict[str, int] = {}

    def set_priority(self, agent_id: str, priority: int) -> None:
        """设置 agent 优先级."""
        self.priorities[agent_id] = priority

    def add_wait(self, waiter: str, holder: str) -> None:
        """添加等待边 waiter → holder."""
        if waiter != holder:
            self.graph[waiter].add(holder)

    def remove_agent(self, agent_id: str) -> None:
        """从图中完全移除 agent（出边 + 所有入边）."""
        self.graph.pop(agent_id, None)
        for w, holders in list(self.graph.items()):
            if agent_id in holders:
                holders.remove(agent_id)
                if not holders:
                    del self.graph[w]

    def detect_cycles(self) -> List[List[str]]:
        """DFS 回溯检测所有简单环."""
        visited: Set[str] = set()
        path: List[str] = []
        cycles: List[List[str]] = []

        def dfs(node: str) -> None:
            if node in path:
                cycles.append(path[path.index(node):])
                return
            if node in visited:
                return
            visited.add(node)
            path.append(node)
            for neighbor in self.graph.get(node, []):
                dfs(neighbor)
            path.pop()

        for n in list(self.graph.keys()):
            if n not in visited:
                dfs(n)
        return cycles

    def resolve_deadlocks(self) -> List[str]:
        """检测所有死锁环，按最低优先级斩杀 Victim 拆解."""
        cycles = self.detect_cycles()
        victims: Set[str] = set()

        for cycle in sorted(cycles, key=len):
            active_nodes = [n for n in cycle if n not in victims]
            if not active_nodes:
                continue
            victim = min(active_nodes, key=lambda n: self.priorities.get(n, 0))
            victims.add(victim)

        for v in victims:
            self.remove_agent(v)
        return list(victims)
