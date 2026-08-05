"""obase.rag_index_store — persistent index store for codebase RAG engines.

3O layer: obase (I/O and resources).
Persists AST chunk metadata + file mtimes to disk so a workspace RAG engine
can restore its index without rescanning unchanged files after a restart.
Vectors are recomputed in memory on load (fast; avoids bulky vector dumps).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class RAGIndexStore:
    """Persists {chunk_id: chunk} + {file: mtime} snapshots as JSON."""

    def __init__(self, store_path: str | Path | None = None):
        _default = str(Path.home() / ".veya" / "rag_index.json")
        self.store_path = Path(
            store_path or os.environ.get("VEYA_RAG_INDEX_PATH", _default)
        ).expanduser()

    def save(self, chunks: dict[str, dict[str, Any]], file_mtimes: dict[str, float]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"chunks": chunks, "file_mtimes": file_mtimes}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self.store_path)

    def load(self) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
        """Returns (chunks, file_mtimes). Empty on missing/corrupt store."""
        if not self.store_path.exists():
            return {}, {}
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            return data.get("chunks", {}), data.get("file_mtimes", {})
        except (json.JSONDecodeError, OSError):
            return {}, {}

    def clear(self) -> None:
        try:
            self.store_path.unlink(missing_ok=True)
        except OSError:
            pass
