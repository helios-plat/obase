"""obase.sandbox.process_jail — jailed argv subprocess. No shell."""

from __future__ import annotations

import subprocess
from pathlib import Path

from obase.sandbox.path_jail import PathJail


class ProcessJail:
    """OS-level process jail: cwd locked to workspace, argv only, timeout.

    Not docker/netns. Network is not blocked. Stronger isolation stays on
    oprim.sandbox_exec backends.
    """

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        timeout_s: int = 15,
    ) -> None:
        self.path_jail = PathJail(workspace_root)
        self.timeout_s = int(timeout_s)

    @property
    def root(self) -> Path:
        return self.path_jail.root

    def run(
        self,
        argv: list[str],
        *,
        timeout: int | None = None,
        cwd: str = ".",
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        if not argv:
            raise ValueError("argv must not be empty")
        work = self.path_jail.resolve_and_verify(cwd)
        if not work.is_dir():
            raise FileNotFoundError(f"jail cwd is not a directory: {work}")
        limit = self.timeout_s if timeout is None else int(timeout)
        try:
            proc = subprocess.run(
                list(argv),
                cwd=str(work),
                env=env,
                capture_output=True,
                timeout=limit,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 124, "", "timed out"
        stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
        return int(proc.returncode), stdout, stderr

    async def run_in_sandbox(
        self,
        argv: list[str],
        *,
        timeout: int | None = None,
        cwd: str = ".",
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        return self.run(argv, timeout=timeout, cwd=cwd, env=env)
