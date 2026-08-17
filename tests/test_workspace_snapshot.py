"""WorkspaceInspector is read-only git + AST."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from obase.workspace_snapshot import WorkspaceInspector, WorkspaceSnapshot


def _git(root: Path, *args: str) -> None:
    env = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.local",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.local"}
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env={**subprocess.os.environ, **env},
    )


@pytest.mark.asyncio
async def test_snapshot_diff_and_ast(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.local")
    _git(tmp_path, "config", "user.name", "t")
    src = tmp_path / "mod.py"
    src.write_text("def old():\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-m", "init")
    src.write_text("class Box:\n    pass\n\ndef neu():\n    return 2\n", encoding="utf-8")

    snap = await WorkspaceInspector(tmp_path).capture_snapshot()
    assert isinstance(snap, WorkspaceSnapshot)
    assert "mod.py" in snap.git_diff
    assert "mod.py" in snap.active_files
    assert "Box" in snap.ast_summary["mod.py"]["classes"]
    assert "neu" in snap.ast_summary["mod.py"]["functions"]


@pytest.mark.asyncio
async def test_non_git_is_empty(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def x():\n    return 0\n", encoding="utf-8")
    snap = await WorkspaceInspector(tmp_path).capture_snapshot()
    assert snap.git_diff == ""
    assert snap.active_files == []
