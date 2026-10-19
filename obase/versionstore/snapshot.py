"""obase.versionstore.snapshot — Agent 快照与配置版本持久化管理存储.

在 JSONL append-only 索引之上提供目录级快照语义：
- snapshot(paths)  -> rev：把一组文件/目录复制进版本库，追加索引条目
- restore(rev)    -> None：把某版本内容还原到目标位置
- list_versions() / latest()：版本浏览

Example:
    >>> vs = VersionStore(Path("/tmp/verstore"))
    >>> rev = vs.snapshot([Path("agent.json")], message="pre-update")
    >>> vs.latest()["rev"] == rev
    True
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = ["SnapshotMeta", "VersionStore", "VersionStoreError"]

_INDEX = "index.jsonl"


class VersionStoreError(RuntimeError):
    """版本库操作失败。"""


class SnapshotMeta:
    """单版本元数据（rev / ts / message / paths / size / checksum）。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self.rev: str = data["rev"]
        self.ts: float = data.get("ts", 0.0)
        self.message: str = data.get("message", "")
        self.paths: list[str] = data.get("paths", [])
        self.size_bytes: int = data.get("size_bytes", 0)
        self.checksum: str = data.get("checksum", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rev": self.rev,
            "ts": self.ts,
            "message": self.message,
            "paths": self.paths,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
        }


class VersionStore:
    """目录级版本库：root/revs/<rev>/... + root/index.jsonl。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._revs = self.root / "revs"
        self._index = self.root / _INDEX
        self.root.mkdir(parents=True, exist_ok=True)
        self._revs.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def snapshot(
        self,
        paths: list[str | Path],
        *,
        message: str = "",
        rev: str | None = None,
    ) -> str:
        """把 paths 中的文件/目录复制进版本库，返回 rev。

        Args:
            paths: 待快照的绝对路径列表（文件或目录）。
            message: 版本说明（如 "pre-changeset"）。
            rev: 自定义版本号；缺省自动生成 "rev-<uuid7-ish>"。
        """
        if not paths:
            raise VersionStoreError("snapshot: paths must not be empty")

        rev = rev or f"rev-{uuid.uuid4().hex[:12]}"
        dest = self._revs / rev
        if dest.exists():
            raise VersionStoreError(f"snapshot: rev {rev!r} already exists")
        dest.mkdir(parents=True)

        copied: list[str] = []
        total = 0
        digest = hashlib.sha256()
        for raw in paths:
            src = Path(raw).expanduser()
            if not src.exists():
                raise VersionStoreError(f"snapshot: path not found: {src}")
            # 以绝对路径的 sha256 前缀做相对定位，避免名字冲突
            rel = f"{hashlib.sha256(str(src.resolve()).encode()).hexdigest()[:10]}-{src.name}"
            target = dest / rel
            if src.is_dir():
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
            copied.append(str(src))
            for part in _walk(src):
                total += part.stat().st_size
                digest.update(part.read_bytes() if part.is_file() else b"")

        meta = SnapshotMeta(
            {
                "rev": rev,
                "ts": time.time(),
                "message": message,
                "paths": copied,
                "size_bytes": total,
                "checksum": digest.hexdigest()[:16],
            }
        )
        with self._index.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(meta.to_dict(), ensure_ascii=False) + "\n")
        return rev

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def list_versions(self) -> list[dict[str, Any]]:
        """全部版本元数据（时间倒序）。"""
        if not self._index.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._index.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:  # pragma: no cover - 防御
                    continue
        out.sort(key=lambda d: d.get("ts", 0), reverse=True)
        return out

    def latest(self) -> dict[str, Any] | None:
        versions = self.list_versions()
        return versions[0] if versions else None

    def get(self, rev: str) -> dict[str, Any] | None:
        for v in self.list_versions():
            if v["rev"] == rev:
                return v
        return None

    def restore(self, rev: str, *, target_root: str | Path) -> None:
        """把 rev 版本的全部内容还原到 target_root 下（目录结构扁平展开）。

        Raises:
            VersionStoreError: rev 不存在。
        """
        meta = self.get(rev)
        if meta is None:
            raise VersionStoreError(f"restore: rev {rev!r} not found")
        src_dir = self._revs / rev
        if not src_dir.is_dir():
            raise VersionStoreError(f"restore: rev dir missing: {src_dir}")
        target_root = Path(target_root)
        target_root.mkdir(parents=True, exist_ok=True)
        for item in src_dir.iterdir():
            target = target_root / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)

    def delete(self, rev: str) -> bool:
        """删除一个版本（目录 + 索引条目）。"""
        src_dir = self._revs / rev
        removed = False
        if src_dir.exists():
            shutil.rmtree(src_dir)
            removed = True
        remaining = [v for v in self.list_versions() if v["rev"] != rev]
        with self._index.open("w", encoding="utf-8") as fh:
            for v in remaining:
                fh.write(json.dumps(v, ensure_ascii=False) + "\n")
        return removed


def _walk(path: Path):
    if path.is_dir():
        yield from sorted(path.rglob("*"))
    else:
        yield path
