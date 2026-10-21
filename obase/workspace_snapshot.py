"""obase.workspace_snapshot — read-only git + AST section. No writes."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from obase.git import run_git

_MAX_DIFF_CHARS = 16_000
_MAX_AST_FILES = 40
_MAX_FILE_BYTES = 200_000
_SKIP_NAME_PARTS = (
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "/venv/",
    ".pyc",
    ".egg-info",
)


class WorkspaceSnapshot(BaseModel):
    git_diff: str = ""
    ast_summary: dict[str, Any] = Field(default_factory=dict)
    active_files: list[str] = Field(default_factory=list)


class WorkspaceInspector:
    """One-way read of local git + AST signatures. Never writes."""

    def __init__(self, project_root: Path | str) -> None:
        self.root = Path(project_root).expanduser().resolve()

    async def capture_snapshot(self) -> WorkspaceSnapshot:
        """Atomic from the caller: uncommitted diff + core AST signatures."""
        git_diff, active = await self._git_section()
        ast_summary = _ast_signatures(self.root, active)
        return WorkspaceSnapshot(
            git_diff=git_diff,
            ast_summary=ast_summary,
            active_files=active,
        )

    async def _git_section(self) -> tuple[str, list[str]]:
        if not (self.root / ".git").exists() and not _is_git_worktree(self.root):
            return "", []
        diff = await run_git(["diff", "HEAD"], cwd=self.root)
        status = await run_git(["status", "--porcelain"], cwd=self.root)
        text = diff.stdout if diff.ok else ""
        if len(text) > _MAX_DIFF_CHARS:
            text = text[:_MAX_DIFF_CHARS] + "\n...[diff truncated]..."
        active = _active_from_status(status.stdout if status.ok else "")
        if not active:
            active = _active_from_diff(text)
        return text, active[:_MAX_AST_FILES]


def _is_git_worktree(root: Path) -> bool:
    git_file = root / ".git"
    if git_file.is_file():
        return True
    return git_file.is_dir()


def _active_from_status(porcelain: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for raw in porcelain.splitlines():
        if len(raw) < 4:
            continue
        path = raw[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if not path or path in seen or _noisy(path):
            continue
        seen.add(path)
        files.append(path)
    return files


def _active_from_diff(diff_text: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for line in diff_text.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split(" b/", 1)
        if len(parts) != 2:
            continue
        path = parts[1].strip()
        if not path or path in seen or _noisy(path):
            continue
        seen.add(path)
        files.append(path)
    return files


def _noisy(path: str) -> bool:
    lowered = path.replace("\\", "/")
    return any(part in lowered for part in _SKIP_NAME_PARTS)


def _ast_signatures(root: Path, active_files: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for rel in active_files[:_MAX_AST_FILES]:
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        if path.suffix != ".py":
            summary[rel] = {"kind": path.suffix.lstrip(".") or "file"}
            continue
        summary[rel] = _py_signature(path)
    return summary


def _py_signature(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"error": str(exc)}
    if len(raw) > _MAX_FILE_BYTES:
        return {"skipped": "too_large"}
    try:
        tree = ast.parse(raw.decode("utf-8", errors="replace"))
    except SyntaxError as exc:
        return {"error": f"syntax: {exc.msg}"}
    classes: list[str] = []
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
    return {"classes": classes[:50], "functions": functions[:80]}
