"""obase.kokoro_runtime — lazy Kokoro TTS runtime adapter (hexgrad/kokoro).

Model weights are NOT bundled. The runtime lazily imports torch/onnxruntime and
kokoro; missing deps raise ImportError with install hints.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any


class KokoroRuntimeError(RuntimeError):
    pass


class KokoroRuntime:
    """Lazy holder for a Kokoro pipeline instance."""

    def __init__(self, *, model_path: str | None = None, device: str = "cpu") -> None:
        self.model_path = model_path
        self.device = device
        self._pipeline: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            try:
                from kokoro import KPipeline  # type: ignore
            except Exception as exc:  # pragma: no cover - optional dep
                raise KokoroRuntimeError(
                    "kokoro is not installed; pip install kokoro"
                ) from exc
            try:
                import torch  # type: ignore  # noqa: F401
            except Exception as exc:  # pragma: no cover
                raise KokoroRuntimeError("torch is required for KokoroRuntime") from exc
            lang_code = "a"
            self._pipeline = KPipeline(lang_code=lang_code)
            return self._pipeline

    def synthesize(self, text: str, *, voice: str = "af_heart", speed: float = 1.0) -> Any:
        pipe = self._load()
        # Kokoro returns a generator of (graphemes, phonemes, audio)
        chunks = []
        for _gs, _ps, audio in pipe(text, voice=voice, speed=speed):
            chunks.append(audio)
        return chunks

    def is_loaded(self) -> bool:
        return self._pipeline is not None


def get_kokoro_runtime(*, model_path: str | None = None, device: str = "cpu") -> KokoroRuntime:
    return KokoroRuntime(model_path=model_path, device=device)


def write_audio_file(samples: Any, output_path: Path, *, sample_rate: int = 24000) -> Path:
    """Write audio samples to a wav file using stdlib wave (no heavy deps)."""
    import struct
    import wave

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # samples may be list of arrays; flatten
    flat = []
    try:
        for s in samples:
            flat.extend(list(s))
    except TypeError:
        flat = list(samples)
    with wave.open(str(output_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        for v in flat:
            # clamp
            iv = int(max(-32768, min(32767, float(v) * 32767)))
            w.writeframes(struct.pack("<h", iv))
    return output_path
