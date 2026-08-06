"""obase.knowledge_store — Cindy-style cross-harness knowledge base.

Markdown files with structured YAML frontmatter: id, type, covers, depends_on,
auto_update, stale tracking.  Atomic writes (tmp → rename).  "Correct once,
remembers forever" across all agent sessions.

3O element: ``obase.knowledge_store`` (``KnowledgeStore`` class).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


class KnowledgeStore:
    """Cindy-style cross-harness knowledge base.

    Usage::

        store = KnowledgeStore()
        store.write("auth", "module", "# Auth\n## 是什么\nhandles login.\n", covers=["login", "oauth"])
        doc = store.read("auth")
        store.mark_stale("auth", "API changed")
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir else Path.home() / ".veya" / "knowledge"
        self._base.mkdir(parents=True, exist_ok=True)

    # -- write / read --------------------------------------------------------
    def write(self, id_: str, type_: str, body: str, **frontmatter: Any) -> Path:
        """Atomic write of a knowledge file with frontmatter."""
        path = self._path(id_)
        fm = {
            "id": id_, "type": type_,
            "covers": frontmatter.pop("covers", []),
            "depends_on": frontmatter.pop("depends_on", []),
            "last_synced_commit": frontmatter.pop("last_synced_commit", ""),
            "last_synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stale": frontmatter.pop("stale", False),
            "stale_reason": frontmatter.pop("stale_reason", None),
            "auto_update": frontmatter.pop("auto_update", True),
            "schema_version": frontmatter.pop("schema_version", 1),
            **frontmatter,
        }
        content = _serialize_frontmatter(fm, body)
        return _atomic_write(path, content)

    def read(self, id_: str) -> dict[str, Any] | None:
        """Read a knowledge file, returning {frontmatter: {...}, body: "..."}."""
        path = self._path(id_)
        if not path.exists():
            return None
        return _parse_frontmatter(path.read_text(encoding="utf-8"))

    def delete(self, id_: str) -> bool:
        path = self._path(id_)
        if path.exists():
            path.unlink()
            return True
        return False

    # -- staleness -----------------------------------------------------------
    def mark_stale(self, id_: str, reason: str = "") -> bool:
        doc = self.read(id_)
        if doc is None:
            return False
        doc["frontmatter"]["stale"] = True
        doc["frontmatter"]["stale_reason"] = reason or None
        return self.write(id_, doc["frontmatter"]["type"], doc["body"], **doc["frontmatter"]) is not None

    def mark_fresh(self, id_: str) -> bool:
        doc = self.read(id_)
        if doc is None:
            return False
        doc["frontmatter"]["stale"] = False
        doc["frontmatter"]["stale_reason"] = None
        doc["frontmatter"]["last_synced_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        return self.write(id_, doc["frontmatter"]["type"], doc["body"], **doc["frontmatter"]) is not None

    def list_stale(self) -> list[dict[str, Any]]:
        return [d for d in self.list_all() if d["frontmatter"].get("stale")]

    # -- listing -------------------------------------------------------------
    def list_all(self, type_: str | None = None) -> list[dict[str, Any]]:
        docs = []
        for p in sorted(self._base.glob("*.md")):
            doc = _parse_frontmatter(p.read_text(encoding="utf-8"))
            if doc and (type_ is None or doc["frontmatter"].get("type") == type_):
                docs.append(doc)
        return docs

    def list_ids(self) -> list[str]:
        return [p.stem for p in sorted(self._base.glob("*.md"))]

    # -- template ------------------------------------------------------------
    @staticmethod
    def skeleton(id_: str, type_: str) -> str:
        """Generate a skeleton template for a new knowledge entry."""
        if type_ == "module":
            return f"# {id_}\n\n## 是什么\n\n_TODO: 一段话讲清这个模块在系统里的位置。_\n\n## 关键抽象\n\n_TODO: 列出关键 class / 函数 / 文件。_\n\n## 模块边界\n\n_TODO: 不依赖什么、被谁依赖、对外接口。_\n\n## 不要做的事\n\n_TODO: 反模式 / 常见误用。_\n"
        if type_ == "pattern":
            return f"# {id_}\n\n## 场景\n\n_TODO: 什么场景下用这个模式。_\n\n## 做法\n\n_TODO: 步骤。_\n\n## 示例\n\n_TODO: 代码示例。_\n"
        return f"# {id_}\n\n_TODO: describe {type_} {id_}._\n"

    def _path(self, id_: str) -> Path:
        safe = id_.replace("/", "_").replace(":", "_").replace("\\", "_")
        return self._base / f"{safe}.md"


# ---------------------------------------------------------------------------
# YAML frontmatter helpers (no external deps — hand-rolled for portability)
# ---------------------------------------------------------------------------


def _serialize_frontmatter(fm: dict[str, Any], body: str) -> str:
    lines = ["---"]
    lines.append(f"id: {fm.get('id', '')}")
    lines.append(f"type: {fm.get('type', '')}")
    if fm.get("covers"):
        lines.append(f"covers: [{', '.join(fm['covers'])}]")
    if fm.get("depends_on"):
        lines.append(f"depends_on: [{', '.join(fm['depends_on'])}]")
    lines.append(f"auto_update: {str(fm.get('auto_update', True)).lower()}")
    lines.append(f"stale: {str(fm.get('stale', False)).lower()}")
    if fm.get("stale_reason"):
        lines.append(f"stale_reason: {fm['stale_reason']}")
    lines.append(f"last_synced_at: {fm.get('last_synced_at', '')}")
    lines.append(f"schema_version: {fm.get('schema_version', 1)}")
    lines.append("---")
    lines.append("")
    lines.append(body.strip())
    return "\n".join(lines) + "\n"


def _parse_frontmatter(text: str) -> dict[str, Any] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    fm_lines = parts[1].strip().splitlines()
    fm: dict[str, Any] = {}
    for line in fm_lines:
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            if v == "true":
                v = True
            elif v == "false":
                v = False
            elif v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
            fm[k] = v
    return {"frontmatter": fm, "body": parts[2].strip()}


def _atomic_write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))
    return path
