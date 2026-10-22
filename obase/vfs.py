"""Local filesystem adapter implementing the byte-oriented VFS contract.

Filesystem access is constrained to the configured root. Command execution
uses the local shell with that root as its working directory; it is not an
OS-level sandbox and should only be used for trusted local workloads.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from obase.contracts import IVFS_Sandbox


class LocalVFS(IVFS_Sandbox):
    """Local disk adapter for tests and trusted single-machine development."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty relative path")
        candidate_part = Path(path)
        if candidate_part.is_absolute() or any(part == ".." for part in candidate_part.parts):
            raise ValueError("path must stay within the VFS root")
        candidate = (self.root / candidate_part).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("path must stay within the VFS root")
        return candidate

    async def read_file(self, path: str) -> bytes:
        """Read a file as bytes from inside the root."""
        resolved = self._resolve(path)
        return await asyncio.to_thread(resolved.read_bytes)

    def _write_sync(self, target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = target.parent.resolve()
        if not resolved_parent.is_relative_to(self.root):
            raise ValueError("path must stay within the VFS root")
        fd, temp_name = tempfile.mkstemp(
            prefix=".vfs-write-", suffix=".tmp", dir=resolved_parent
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    async def write_file(self, path: str, content: bytes) -> None:
        """Atomically write bytes to a relative path inside the root."""
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes")
        resolved = self._resolve(path)
        await asyncio.to_thread(self._write_sync, resolved, content)

    @staticmethod
    def _decode_output(data: str | bytes | None) -> str:
        if data is None:
            return ""
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return data

    @classmethod
    def _run_sync(cls, command: str, root: Path, timeout: int) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                executable="/bin/bash",
            )
            return {
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        except subprocess.TimeoutExpired as exc:
            stdout = cls._decode_output(exc.stdout)
            stderr = cls._decode_output(exc.stderr)
            message = f"command timed out after {timeout}s"
            return {
                "exit_code": -1,
                "stdout": stdout,
                "stderr": (stderr + "\n" if stderr else "") + message,
            }
        except OSError as exc:
            return {"exit_code": -1, "stdout": "", "stderr": str(exc)}

    async def execute_isolated(
        self, command: str, *, timeout: int = 30
    ) -> dict[str, Any]:
        """Execute a trusted command with the VFS root as its current directory."""
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout must be a positive integer")
        return await asyncio.to_thread(self._run_sync, command, self.root, timeout)
