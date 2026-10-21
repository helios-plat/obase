"""3O 范式内化 — Graft 图谱存储 (obase 基础设施).

本地 Markdown 图谱节点 + SHA256 哈希缓存 (.veya/graph/ 目录)。
无业务逻辑, 无 LLM。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GraphRelation:
    target: str
    type: str = "depends_on"


@dataclass
class GraphNode:
    """Graft 图谱节点 (与规范数据契约一致)。"""

    node_id: str
    file_path: str
    content_hash: str
    summary: str = ""
    crux: str = ""
    relations: list[GraphRelation] = field(default_factory=list)
    custom_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "file_path": self.file_path,
            "content_hash": self.content_hash,
            "summary": self.summary,
            "crux": self.crux,
            "relations": [{"target": r.target, "type": r.type} for r in self.relations],
            "custom_notes": self.custom_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphNode:
        return cls(
            node_id=data["node_id"],
            file_path=data.get("file_path", ""),
            content_hash=data.get("content_hash", ""),
            summary=data.get("summary", ""),
            crux=data.get("crux", ""),
            relations=[
                GraphRelation(target=r["target"], type=r.get("type", "depends_on"))
                for r in data.get("relations", [])
            ],
            custom_notes=data.get("custom_notes", ""),
        )


class MarkdownGraphStore:
    """本地 Markdown 图谱存储: 节点为 .md 文件, 关系为 [[wikilink]]。"""

    def __init__(self, graph_dir: str | Path):
        self.graph_dir = Path(graph_dir)
        self.cache_path = self.graph_dir / "cache.json"

    # -- 哈希 ------------------------------------------------------------
    @staticmethod
    def hash_content(content: bytes | str) -> str:
        raw = content.encode("utf-8") if isinstance(content, str) else content
        return f"sha256:{hashlib.sha256(raw).hexdigest()}"

    def _load_cache(self) -> dict[str, str]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self, cache: dict[str, str]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8"
        )

    def check_hash(self, node_id: str, content_hash: str) -> bool:
        """Hash 未变化返回 True (0 成本跳过依据)。"""
        return self._load_cache().get(node_id) == content_hash

    def get_hash(self, node_id: str) -> str | None:
        return self._load_cache().get(node_id)

    # -- 节点读写 --------------------------------------------------------
    def node_path(self, node_id: str) -> Path:
        return self.graph_dir / f"{node_id}.md"

    def save_node(self, node: GraphNode) -> Path:
        """节点落盘为 Markdown (含 [[wikilink]] 关联) + 更新哈希缓存。"""
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        links = "\n".join(
            f"- [[{r.target}]] ({r.type})" for r in node.relations
        )
        md = (
            f"# {node.node_id}\n\n"
            f"- file: `{node.file_path}`\n"
            f"- hash: `{node.content_hash}`\n\n"
            f"## Summary\n\n{node.summary}\n\n"
            f"## Crux\n\n```\n{node.crux}\n```\n\n"
            f"## Relations\n\n{links or '_none_'}\n\n"
            f"## Notes\n\n{node.custom_notes or '_none_'}\n"
        )
        path = self.node_path(node.node_id)
        path.write_text(md, encoding="utf-8")
        cache = self._load_cache()
        cache[node.node_id] = node.content_hash
        self._save_cache(cache)
        return path

    def load_node(self, node_id: str) -> GraphNode | None:
        path = self.node_path(node_id)
        if not path.exists():
            return None
        md = path.read_text(encoding="utf-8")
        return self._parse_markdown(node_id, md)

    def load_all(self) -> list[GraphNode]:
        if not self.graph_dir.exists():
            return []
        nodes = []
        for md_path in sorted(self.graph_dir.glob("*.md")):
            nodes.append(self._parse_markdown(md_path.stem, md_path.read_text(encoding="utf-8")))
        return nodes

    @staticmethod
    def _parse_markdown(node_id: str, md: str) -> GraphNode:
        file_path = ""
        summary = ""
        crux = ""
        relations: list[GraphRelation] = []
        section = ""
        for line in md.splitlines():
            if line.startswith("## "):
                section = line[3:].strip().lower()
                continue
            if line.startswith("- file: `"):
                file_path = line[len("- file: `"):].rstrip("`")
            elif section == "summary":
                summary = line if line.strip() else summary
            elif section == "crux" and not crux:
                if line.strip() and not line.strip().startswith("```"):
                    crux = line.strip()
            elif section == "relations" and line.startswith("- [["):
                target = line[4:].split("]]")[0]
                rel_type = "depends_on"
                if "(" in line:
                    rel_type = line.split("(", 1)[1].rstrip(")")
                relations.append(GraphRelation(target=target, type=rel_type))
        return GraphNode(
            node_id=node_id,
            file_path=file_path,
            content_hash="",
            summary=summary,
            crux=crux,
            relations=relations,
        )
