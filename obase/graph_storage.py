"""Markdown-backed graph nodes with machine-readable, versioned metadata."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_MARKER = "<!-- obase-graph-node:v1:"
_MARKER_END = " -->"


@dataclass(slots=True, frozen=True)
class GraphRelation:
    """Directed relation from its owning node to its target."""

    target: str
    type: str = "depends_on"

    def __post_init__(self) -> None:
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("relation target must be a non-empty string")
        if not isinstance(self.type, str) or not self.type.strip():
            raise ValueError("relation type must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {"target": self.target, "type": self.type}


@dataclass(slots=True)
class GraphNode:
    """A repository/code-graph node and the provenance attached to it."""

    node_id: str
    file_path: str = ""
    content_hash: str = ""
    summary: str = ""
    crux: str = ""
    relations: list[GraphRelation] = field(default_factory=list)
    custom_notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        for name in ("file_path", "content_hash", "summary", "crux"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        self.relations = [
            relation if isinstance(relation, GraphRelation) else GraphRelation(**relation)
            for relation in self.relations
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "file_path": self.file_path,
            "content_hash": self.content_hash,
            "summary": self.summary,
            "crux": self.crux,
            "relations": [relation.to_dict() for relation in self.relations],
            "custom_notes": self.custom_notes,
        }


class MarkdownGraphStore:
    """Persist graph nodes as readable Markdown pages with an encoded JSON header.

    The metadata header is versioned and stored in the first line as a base64
    payload so arbitrary Markdown text and comment terminators in content
    cannot corrupt parsing. Writes use an atomic rename.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _filename(node_id: str) -> str:
        # Preserve the human-readable legacy path for simple IDs while keeping
        # all unusual/path-like IDs slugged and hash-disambiguated.
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", node_id):
            return f"{node_id}.md"
        readable = re.sub(r"[^A-Za-z0-9._-]+", "_", node_id).strip("._-")[:64]
        if not readable:
            readable = "node"
        suffix = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:12]
        return f"{readable}-{suffix}.md"

    @staticmethod
    def _encode(node: GraphNode) -> str:
        raw = json.dumps(
            node.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(first_line: str, path: Path) -> GraphNode | None:
        if not first_line.startswith(_MARKER) or not first_line.endswith(_MARKER_END):
            return None
        encoded = first_line[len(_MARKER) : -len(_MARKER_END)]
        try:
            payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            value = json.loads(payload.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("metadata must be a JSON object")
            relations = value.get("relations", [])
            if not isinstance(relations, list):
                raise ValueError("relations must be a JSON list")
            return GraphNode(
                node_id=value["node_id"],
                file_path=value.get("file_path", ""),
                content_hash=value.get("content_hash", ""),
                summary=value.get("summary", ""),
                crux=value.get("crux", ""),
                relations=[GraphRelation(**relation) for relation in relations],
                custom_notes=value.get("custom_notes", ""),
            )
        except (binascii.Error, KeyError, TypeError, UnicodeError, ValueError) as exc:
            raise ValueError(f"invalid graph metadata in {path}") from exc

    def save_node(self, node: GraphNode) -> Path:
        """Validate and atomically persist one node; existing IDs are upserted."""
        if not isinstance(node, GraphNode):
            raise TypeError("node must be a GraphNode")
        path = self.root / self._filename(node.node_id)
        header = f"{_MARKER}{self._encode(node)}{_MARKER_END}"
        body = (
            f"{header}\n\n# {node.node_id}\n\n"
            f"{node.summary}\n\n## Crux\n\n{node.crux}\n\n"
            f"- File: {node.file_path}\n"
            f"- Content hash: {node.content_hash}\n\n"
            "## Relations\n\n"
            + "".join(
                f"- [[{relation.target}]] ({relation.type})\n"
                for relation in node.relations
            )
        )
        fd, temp_name = tempfile.mkstemp(prefix=".graph-node-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return path

    def load_all(self) -> list[GraphNode]:
        """Load nodes deterministically and collapse legacy duplicate filenames."""
        nodes_by_id: dict[str, GraphNode] = {}
        for path in sorted(self.root.glob("*.md"), key=lambda item: item.name):
            with path.open("r", encoding="utf-8") as stream:
                first_line = stream.readline().rstrip("\r\n")
            node = self._decode(first_line, path)
            if node is not None:
                # For a migration overlap, the canonical simple-ID name sorts
                # after its old slug-hash filename, so the current node wins.
                nodes_by_id[node.node_id] = node
        return sorted(nodes_by_id.values(), key=lambda node: node.node_id)

    def get_node(self, node_id: str) -> GraphNode | None:
        """Fetch one node by ID, including nodes written with the older hashed name."""
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        readable = re.sub(r"[^A-Za-z0-9._-]+", "_", node_id).strip("._-")[:64]
        if not readable:
            readable = "node"
        suffix = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:12]
        canonical = self.root / self._filename(node_id)
        legacy = self.root / f"{readable}-{suffix}.md"
        candidates = [canonical] if canonical == legacy else [canonical, legacy]
        for path in candidates:
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8") as stream:
                first_line = stream.readline().rstrip("\r\n")
            node = self._decode(first_line, path)
            if node is None:
                if path == canonical:
                    raise ValueError(f"missing graph metadata in {path}")
                continue
            if node.node_id == node_id:
                return node
            if path == canonical:
                raise ValueError(f"node ID mismatch in {path}")
        return None

    def delete_node(self, node_id: str) -> bool:
        """Delete a stored node by ID, including any legacy duplicate filename."""
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        readable = re.sub(r"[^A-Za-z0-9._-]+", "_", node_id).strip("._-")[:64]
        if not readable:
            readable = "node"
        suffix = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:12]
        canonical = self.root / self._filename(node_id)
        legacy = self.root / f"{readable}-{suffix}.md"
        removed = False
        for path in (canonical,) if canonical == legacy else (canonical, legacy):
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8") as stream:
                first_line = stream.readline().rstrip("\r\n")
            node = self._decode(first_line, path)
            if node is not None and node.node_id == node_id:
                path.unlink()
                removed = True
        return removed

    # Compatibility methods retained from the Gloom graph store interface.
    @staticmethod
    def hash_content(content: bytes | str) -> str:
        raw = content.encode("utf-8") if isinstance(content, str) else content
        return hashlib.sha256(raw).hexdigest()

    def node_path(self, node_id: str) -> Path:
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        return self.root / self._filename(node_id)

    def get_hash(self, node_id: str) -> str | None:
        node = self.get_node(node_id)
        return None if node is None else node.content_hash

    def check_hash(self, node_id: str, content_hash: str) -> bool:
        return self.get_hash(node_id) == content_hash

    def load_node(self, node_id: str) -> GraphNode | None:
        """Read one node by its stable node ID, returning None when absent."""
        return self.get_node(node_id)

    @staticmethod
    def _parse_markdown(node_id: str, md: str) -> GraphNode:
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        lines = md.splitlines()
        summary = next((line[2:].strip() for line in lines if line.startswith("# ")), "")
        crux = ""
        for i, line in enumerate(lines):
            if line.strip().lower() in {"## crux", "## 核心", "## crux:"}:
                crux = next((item.strip() for item in lines[i + 1:] if item.strip()), "")
                break
        return GraphNode(node_id=node_id, summary=summary, crux=crux)
