from pathlib import Path

import pytest

from obase.git import run_git


@pytest.mark.asyncio
async def test_run_git_ok(tmp_path):
    await run_git(["init"], cwd=tmp_path)
    r = await run_git(["status", "--porcelain"], cwd=tmp_path)
    assert r.ok

@pytest.mark.asyncio
async def test_run_git_nonzero(tmp_path):
    await run_git(["init"], cwd=tmp_path)
    r = await run_git(["log"], cwd=tmp_path)
    assert not r.ok  # 无 commit

@pytest.mark.asyncio
async def test_run_git_cwd_not_exist():
    with pytest.raises(FileNotFoundError):
        await run_git(["status"], cwd=Path("/nonexistent"))

@pytest.mark.asyncio
async def test_run_git_timeout(tmp_path):
    await run_git(["init"], cwd=tmp_path)
    with pytest.raises(TimeoutError):
        await run_git(["log", "--all"], cwd=tmp_path, timeout=0.000001)

@pytest.mark.asyncio
async def test_gitresult_ok_property(tmp_path):
    await run_git(["init"], cwd=tmp_path)
    r = await run_git(["status"], cwd=tmp_path)
    assert isinstance(r.ok, bool)
