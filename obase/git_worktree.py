"""obase.git_worktree — Git Worktree 底层文件目录隔离管理工具.

基于 obase.git.run_git 的 porcelain 句柄，封装 worktree 全生命周期：
add / remove / list / prune。供多 Agent 并行开发（omodul.multi_agent_worktree_workflow）
与沙箱隔离场景使用。

Example:
    >>> path = await add_worktree(repo=Path("/repo"), branch="feat/x")
    >>> await list_worktrees(repo=Path("/repo"))
    [{'path': '/repo-worktrees/feat-x', 'branch': 'feat/x', 'head': '...'}]
    >>> await remove_worktree(repo=Path("/repo"), path=path)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from obase.git import GitResult, run_git

__all__ = [
    "GitWorktreeError",
    "add_worktree",
    "list_worktrees",
    "prune_worktrees",
    "remove_worktree",
]


class GitWorktreeError(RuntimeError):
    """Git worktree 操作失败（含命令非零退出）。"""


def _ensure_ok(result: GitResult, *, op: str) -> None:
    if not result.ok:
        raise GitWorktreeError(
            f"git worktree {op} failed (rc={result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _branch_of(path: Path) -> str | None:
    """从 worktree 的 .git 文件解析分支名（"gitdir: ..." 方案的解析）。"""
    git_file = path / ".git"
    if git_file.is_file():
        try:
            text = git_file.read_text(encoding="utf-8")
        except OSError:
            return None
        m = re.search(r"worktrees/([^/]+)", text)
        return m.group(1) if m else None
    return None


async def add_worktree(
    *,
    repo: str | Path,
    branch: str,
    path: str | Path | None = None,
    create_branch: bool = True,
    timeout: float = 30,
) -> Path:
    """创建 worktree 并切到目标分支，返回 worktree 目录绝对路径。

    Args:
        repo: 仓库根目录。
        branch: worktree 分支名；create_branch=True 时不存在则创建。
        path: worktree 落盘位置；None 自动取 "<repo-parent>/<repo>-worktrees/<branch-safe>"。
        create_branch: 是否允许新建分支（False 时分支必须已存在）。
    """
    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        raise GitWorktreeError(f"repo dir not found: {repo_path}")

    wt_path: Path
    if path is None:
        branch_safe = branch.replace("/", "-").replace(" ", "_")
        wt_path = repo_path.parent / f"{repo_path.name}-worktrees" / branch_safe
    else:
        wt_path = Path(path).resolve()
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    args = ["worktree", "add"]
    if create_branch:
        args += ["-b", branch]
    args.append(str(wt_path))
    if not create_branch:
        args.append(branch)
    result = await run_git(args, cwd=repo_path, timeout=timeout)
    _ensure_ok(result, op="add")
    return wt_path


async def remove_worktree(
    *,
    repo: str | Path,
    path: str | Path,
    force: bool = False,
    timeout: float = 30,
) -> None:
    """移除 worktree（先 remove 再删除目录；force=True 时 --force）。"""
    repo_path = Path(repo).resolve()
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(Path(path).resolve()))
    result = await run_git(args, cwd=repo_path, timeout=timeout)
    _ensure_ok(result, op="remove")


async def list_worktrees(*, repo: str | Path, timeout: float = 30) -> list[dict[str, Any]]:
    """列出仓库全部 worktree：{path, branch, head, dirty}。"""
    repo_path = Path(repo).resolve()
    result = await run_git(["worktree", "list", "--porcelain"], cwd=repo_path, timeout=timeout)
    if not result.ok:
        raise GitWorktreeError(
            f"git worktree list failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "HEAD":
            current["head"] = value
        elif key == "bare":
            current["bare"] = True
        elif key == "detached":
            current["detached"] = True
    if current:
        entries.append(current)
    for entry in entries:
        entry.setdefault("branch", None)
        entry.setdefault("head", None)
        wt = Path(entry["path"])
        if entry.get("branch") is None:
            entry["branch"] = _branch_of(wt)
        entry["dirty"] = await _has_changes(wt, timeout=timeout)
    return entries


async def _has_changes(worktree: Path, *, timeout: float) -> bool:
    """探测 worktree 是否有未提交变更（git status --porcelain 非空）。"""
    if not (worktree / ".git").exists() and not (worktree / ".git").is_file():
        return False
    result = await run_git(["status", "--porcelain"], cwd=worktree, timeout=timeout)
    return bool(result.ok and result.stdout.strip())


async def prune_worktrees(*, repo: str | Path, timeout: float = 30) -> None:
    """清理失效 worktree 元数据（git worktree prune）。"""
    repo_path = Path(repo).resolve()
    result = await run_git(["worktree", "prune"], cwd=repo_path, timeout=timeout)
    _ensure_ok(result, op="prune")
