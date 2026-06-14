"""obase.git — git subprocess 底座."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    stdout: str
    stderr: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


async def run_git(args: list[str], *, cwd: Path, timeout: float = 30) -> GitResult:
    """单次 git subprocess 调用。
    非零退出码返回 GitResult(returncode!=0)，不 raise。
    超时 raise TimeoutError。
    cwd 不存在 raise FileNotFoundError。

    Example:
        >>> result = await run_git(["status", "--porcelain"], cwd=Path("/repo"))
        >>> result.ok
        True
    """
    if not cwd.exists():
        raise FileNotFoundError(f"cwd does not exist: {cwd}")
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return GitResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            returncode=proc.returncode or 0,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"git {args[0]!r} timed out after {timeout}s")
