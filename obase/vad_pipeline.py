"""obase.vad_pipeline — 语音活动检测 (VAD) 流水线.

- EnergyVAD：零依赖能量阈值检测（回退路径，恒可用）
- WebRtcVAD：webrtcvad 可选依赖（惰性加载，更精确）
- detect_speech_segments：把音频帧流切分为语音段（供 STT 上游）

Example:
    >>> vad = VADPipeline(mode="energy")
    >>> vad.is_speech(b"\\x00" * 320, sample_rate=16000)   # 静音帧
    False
"""

from __future__ import annotations

import math
import struct
from typing import Any, Literal

__all__ = ["EnergyVAD", "VADPipeline", "VADError", "speech_segments"]

VADMode = Literal["energy", "webrtc"]


class VADError(RuntimeError):
    """VAD 流水线错误。"""


class EnergyVAD:
    """零依赖能量 VAD：RMS 阈值 + 平滑窗。"""

    def __init__(self, *, threshold: float = 0.02, smoothing: int = 3) -> None:
        self.threshold = threshold
        self.smoothing = max(1, smoothing)
        self._history: list[bool] = []

    def is_speech(self, frame: bytes, *, sample_rate: int = 16000) -> bool:
        """单帧判断（帧宽 = sample_rate/100 采样点，16bit PCM）。"""
        rms = _rms(frame)
        raw = rms >= self.threshold
        self._history.append(raw)
        if len(self._history) > self.smoothing:
            self._history.pop(0)
        if len(self._history) < self.smoothing:
            return raw  # 窗口未满：直通原始判决
        return sum(self._history) >= math.ceil(self.smoothing / 2)


class VADPipeline:
    """VAD 流水线：energy（默认，零依赖）或 webrtc（可选）。"""

    def __init__(self, mode: VADMode = "energy", **kwargs: Any) -> None:
        self.mode = mode
        self.kwargs = kwargs
        self._webrtc: Any = None
        self._energy = EnergyVAD(**kwargs)

    @property
    def webrtc_available(self) -> bool:
        if self._webrtc is None:
            try:
                import webrtcvad  # type: ignore[import-untyped]  # noqa: F401

                self._webrtc = True
            except ImportError:
                self._webrtc = False
        return bool(self._webrtc)

    def is_speech(self, frame: bytes, *, sample_rate: int = 16000) -> bool:
        """单帧 VAD。

        Raises:
            VADError: mode=webrtc 但 webrtcvad 未安装。
        """
        if self.mode == "energy":
            return self._energy.is_speech(frame, sample_rate=sample_rate)
        return self._webrtc_is_speech(frame, sample_rate)

    def _webrtc_is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if not self.webrtc_available:
            raise VADError(
                "webrtcvad is not installed — pip install webrtcvad, or use mode='energy'"
            )

        vad = self._webrtc_instance()
        return bool(vad.is_speech(frame, sample_rate))

    def _webrtc_instance(self) -> Any:
        import webrtcvad  # type: ignore[import-untyped]

        if "vad" not in self.kwargs:
            self.kwargs["vad"] = webrtcvad.Vad(int(self.kwargs.get("aggressiveness", 2)))
        return self.kwargs["vad"]

    def detect_speech_segments(
        self,
        frames: list[bytes],
        *,
        sample_rate: int = 16000,
        min_segment_frames: int = 5,
        pad_frames: int = 2,
    ) -> list[dict[str, Any]]:
        """帧流 → 语音段列表 [{start_frame, end_frame, frames, speech}]. """
        voiced = [self.is_speech(f, sample_rate=sample_rate) for f in frames]
        segments: list[dict[str, Any]] = []
        start: int | None = None
        for i, v in enumerate(voiced):
            if v and start is None:
                start = i
            elif not v and start is not None:
                if i - start >= min_segment_frames:
                    segments.append(
                        {
                            "start_frame": max(0, start - pad_frames),
                            "end_frame": min(len(frames), i + pad_frames),
                            "frames": i - start,
                            "speech": True,
                        }
                    )
                start = None
        if start is not None and len(frames) - start >= min_segment_frames:
            segments.append(
                {
                    "start_frame": max(0, start - pad_frames),
                    "end_frame": len(frames),
                    "frames": len(frames) - start,
                    "speech": True,
                }
            )
        return segments


def speech_segments(
    frames: list[bytes], *, sample_rate: int = 16000, **kwargs: Any
) -> list[dict[str, Any]]:
    """便捷入口：能量 VAD 切分语音段。"""
    return VADPipeline(mode="energy").detect_speech_segments(
        frames, sample_rate=sample_rate, **kwargs
    )


def _rms(frame: bytes) -> float:
    """16bit PCM 小端帧 RMS。"""
    if not frame:
        return 0.0
    n = len(frame) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", frame[: n * 2])
    return math.sqrt(sum(s * s for s in samples) / n) / 32768.0
