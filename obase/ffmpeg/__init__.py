"""obase.ffmpeg — Unified FFmpeg subprocess wrapper.

Example:
    >>> from obase.ffmpeg import run
    >>> stderr = await run(args=["-i", "in.mp4", "-c", "copy", "out.mp4"])
"""

from obase.ffmpeg._run import FFmpegError, FFmpegNotFoundError, run

__all__ = ["FFmpegError", "FFmpegNotFoundError", "run"]
