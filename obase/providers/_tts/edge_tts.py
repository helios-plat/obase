"""Edge TTS provider — Microsoft Edge Read Aloud (free cloud TTS)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from obase.provider_registry import ProviderRegistry


class EdgeTTSProvider:
    """Async-callable TTS provider wrapping edge-tts.

    Registers as ProviderRegistry(category='tts', name='edge_tts').
    Free cloud service, no GPU needed, supports zh-CN / en-US / 300+ voices.

    Usage::

        ProviderRegistry.register("tts", "edge_tts", EdgeTTSProvider())
        # then oprim.tts_synthesize(provider="edge_tts", ...) works
    """

    async def __call__(
        self,
        *,
        text: str,
        voice: str,
        output_path: Path,
        rate: str = "+0%",
        pitch: str = "+0Hz",
        timeout_s: float = 60.0,
        **_: Any,
    ) -> None:
        """Synthesize speech via Edge TTS cloud API.

        Args:
            text: Text to speak.
            voice: Voice identifier e.g. "zh-CN-XiaoxiaoNeural".
            output_path: Destination audio file (mp3).
            rate: Speed adjustment ("-50%" to "+200%").
            pitch: Pitch adjustment in Hz e.g. "+0Hz".
            timeout_s: Not used by edge-tts directly (cloud call).
        """
        import edge_tts  # optional dep — ImportError if not installed

        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(str(output_path))


def register(*, replace: bool = False) -> None:
    """Register EdgeTTSProvider into ProviderRegistry.

    Raises:
        ImportError: edge-tts package not installed.
    """
    import edge_tts as _  # noqa: F401  — verify importable before registering

    ProviderRegistry.register("tts", "edge_tts", EdgeTTSProvider(), replace=replace)
