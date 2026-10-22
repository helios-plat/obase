from __future__ import annotations

import pytest

from obase import IVFS_Sandbox, LocalVFS, VFSProvider


@pytest.mark.asyncio
async def test_local_vfs_file_roundtrip_and_parent_creation(tmp_path):
    vfs = LocalVFS(tmp_path / "sandbox")
    assert isinstance(vfs, IVFS_Sandbox)
    assert VFSProvider is IVFS_Sandbox
    await vfs.write_file("nested/data.txt", "café".encode())
    assert await vfs.read_file("nested/data.txt") == "café".encode()


@pytest.mark.asyncio
async def test_local_vfs_rejects_path_escape(tmp_path):
    vfs = LocalVFS(tmp_path / "sandbox")
    with pytest.raises(ValueError, match="within the VFS root"):
        await vfs.write_file("../outside.txt", b"no")
    with pytest.raises(ValueError, match="within the VFS root"):
        await vfs.read_file(str(tmp_path / "outside.txt"))


@pytest.mark.asyncio
async def test_local_vfs_command_result_and_timeout(tmp_path):
    vfs = LocalVFS(tmp_path / "sandbox")
    result = await vfs.execute_isolated("printf 'atom-ok'", timeout=3)
    assert result == {"exit_code": 0, "stdout": "atom-ok", "stderr": ""}
    failure = await vfs.execute_isolated("exit 3", timeout=3)
    assert failure["exit_code"] == 3
    timeout = await vfs.execute_isolated("sleep 5", timeout=1)
    assert timeout["exit_code"] == -1
    assert "timed out" in timeout["stderr"]
