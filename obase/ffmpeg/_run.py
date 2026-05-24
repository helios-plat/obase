"""FFmpeg subprocess runner with timeout, error capture, and output validation.

Example:
    >>> import asyncio
    >>> from obase.ffmpeg import run, FFmpegError
    >>> stderr = asyncio.run(run(args=["-i", "in.mp4", "-c:a", "aac", "out.mp4"]))

Raises:
    FFmpegNotFoundError: ffmpeg binary not found on PATH.
    FFmpegError: Process exited non-zero, timed out, or expected output missing.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class FFmpegError(Exception):
    """FFmpeg process exited != 0 or timed out."""

    def __init__(self, message: str, *, code: int = -1, stderr: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.stderr = stderr


class FFmpegNotFoundError(Exception):
    """ffmpeg binary not found on PATH."""


async def run(
    *,
    args: list[str],
    timeout_s: float = 300.0,
    cwd: Path | None = None,
    expected_output: Path | None = None,
) -> str:
    """Run ffmpeg with given arguments.

    Args:
        args: FFmpeg arguments (without the leading 'ffmpeg').
        timeout_s: Maximum seconds before killing the process.
        cwd: Working directory for the subprocess.
        expected_output: If set, verify this file exists after completion.

    Returns:
        The stderr output (FFmpeg writes progress/info to stderr).

    Raises:
        FFmpegNotFoundError: ffmpeg binary not found.
        FFmpegError: Non-zero exit, timeout, or missing expected output.

    Example:
        >>> stderr = await run(args=["-i", "input.wav", "-ar", "44100", "output.wav"])
    """
    if shutil.which("ffmpeg") is None:
        raise FFmpegNotFoundError("ffmpeg binary not found on PATH")

    cmd = ["ffmpeg", "-y", *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError("ffmpeg binary not found on PATH") from exc

    try:
        _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise FFmpegError("FFmpeg timed out", code=-1, stderr="") from None

    stderr_text = stderr_bytes.decode(errors="replace")

    if proc.returncode != 0:
        raise FFmpegError(
            f"FFmpeg exited with code {proc.returncode}",
            code=proc.returncode or 1,
            stderr=stderr_text,
        )

    if expected_output is not None and not expected_output.exists():
        raise FFmpegError(
            f"Expected output file not found: {expected_output}",
            code=0,
            stderr=stderr_text,
        )

    return stderr_text
