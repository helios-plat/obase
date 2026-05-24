"""Tests for obase.ffmpeg subprocess wrapper."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from obase.ffmpeg import FFmpegError, FFmpegNotFoundError, run


@pytest.fixture()
def tmp_audio(tmp_path: Path) -> Path:
    """Create a tiny valid file to act as output."""
    f = tmp_path / "out.mp4"
    f.write_bytes(b"\x00" * 16)
    return f


class TestFFmpegNotFound:
    async def test_raises_when_binary_missing(self) -> None:
        with patch("obase.ffmpeg._run.shutil.which", return_value=None):
            with pytest.raises(FFmpegNotFoundError, match="not found"):
                await run(args=["-version"])

    async def test_raises_when_exec_file_not_found(self) -> None:
        with (
            patch("obase.ffmpeg._run.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError("No such file"),
            ),
        ):
            with pytest.raises(FFmpegNotFoundError, match="not found"):
                await run(args=["-version"])


class TestFFmpegRun:
    async def test_normal_call_returns_stderr(self, tmp_path: Path) -> None:
        out = tmp_path / "out.wav"

        async def _fake_exec(*cmd: str, **kw: object) -> AsyncMock:
            out.write_bytes(b"\x00" * 8)
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b"progress info"))
            proc.returncode = 0
            proc.kill = AsyncMock()
            return proc

        with (
            patch("obase.ffmpeg._run.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        ):
            result = await run(args=["-i", "in.wav", str(out)])
            assert result == "progress info"

    async def test_nonzero_exit_raises_ffmpeg_error(self) -> None:
        async def _fake_exec(*cmd: str, **kw: object) -> AsyncMock:
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b"error detail"))
            proc.returncode = 1
            proc.kill = AsyncMock()
            return proc

        with (
            patch("obase.ffmpeg._run.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        ):
            with pytest.raises(FFmpegError) as exc_info:
                await run(args=["-i", "bad.mp4"])
            assert exc_info.value.code == 1
            assert "error detail" in exc_info.value.stderr

    async def test_timeout_raises_ffmpeg_error(self) -> None:
        async def _fake_exec(*cmd: str, **kw: object) -> AsyncMock:
            proc = AsyncMock()

            async def _hang() -> tuple[bytes, bytes]:
                await asyncio.sleep(10)
                return (b"", b"")

            proc.communicate = _hang
            proc.returncode = None
            proc.kill = AsyncMock()
            return proc

        with (
            patch("obase.ffmpeg._run.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        ):
            with pytest.raises(FFmpegError, match="timed out"):
                await run(args=["-i", "in.mp4"], timeout_s=0.01)

    async def test_expected_output_missing_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.mp4"

        async def _fake_exec(*cmd: str, **kw: object) -> AsyncMock:
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b"done"))
            proc.returncode = 0
            proc.kill = AsyncMock()
            return proc

        with (
            patch("obase.ffmpeg._run.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        ):
            with pytest.raises(FFmpegError, match="Expected output"):
                await run(args=["-i", "in.mp4", str(missing)], expected_output=missing)

    async def test_expected_output_exists_ok(self, tmp_path: Path) -> None:
        out = tmp_path / "out.mp4"
        out.write_bytes(b"\x00")

        async def _fake_exec(*cmd: str, **kw: object) -> AsyncMock:
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b"ok"))
            proc.returncode = 0
            proc.kill = AsyncMock()
            return proc

        with (
            patch("obase.ffmpeg._run.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        ):
            result = await run(args=["-i", "in.mp4", str(out)], expected_output=out)
            assert result == "ok"

    async def test_cwd_passed_to_subprocess(self, tmp_path: Path) -> None:
        captured_kw: dict[str, object] = {}

        async def _fake_exec(*cmd: str, **kw: object) -> AsyncMock:
            captured_kw.update(kw)
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
            proc.kill = AsyncMock()
            return proc

        with (
            patch("obase.ffmpeg._run.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        ):
            await run(args=["-version"], cwd=tmp_path)
            assert captured_kw["cwd"] == tmp_path
