"""Tests for obase EdgeTTSProvider + ProviderRegistry integration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from obase.provider_registry import ProviderRegistry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_edge_tts_mock(output_path_ref: list[Path]) -> MagicMock:
    """Return a mock edge_tts module whose Communicate.save writes a real file."""

    async def _save(path: str) -> None:
        p = Path(path)
        p.write_bytes(b"\xff\xfb\x90" * 100)  # fake mp3 header bytes
        output_path_ref.append(p)

    communicate_instance = MagicMock()
    communicate_instance.save = _save
    communicate_cls = MagicMock(return_value=communicate_instance)

    mock_mod = MagicMock()
    mock_mod.Communicate = communicate_cls
    return mock_mod


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestEdgeTTSProviderRegistration:
    def test_register_adds_to_registry(self) -> None:
        mock_edge_tts = MagicMock()
        with patch.dict(sys.modules, {"edge_tts": mock_edge_tts}):
            from obase.providers._tts.edge_tts import register

            register()

        assert ProviderRegistry.has("tts", "edge_tts")

    def test_register_listed_in_list_providers(self) -> None:
        mock_edge_tts = MagicMock()
        with patch.dict(sys.modules, {"edge_tts": mock_edge_tts}):
            from obase.providers._tts.edge_tts import register

            register()

        assert ("tts", "edge_tts") in ProviderRegistry.list_providers()

    def test_register_missing_dep_raises_import_error(self) -> None:
        with patch.dict(sys.modules, {"edge_tts": None}):  # type: ignore[dict-item]
            # reimport to avoid cached module
            import importlib

            import obase.providers._tts.edge_tts as _m

            importlib.reload(_m)
            with pytest.raises(ImportError):
                _m.register()


class TestEdgeTTSProviderSynthesis:
    async def test_synthesis_writes_file(self, tmp_path: Path) -> None:
        written: list[Path] = []
        mock_mod = _make_edge_tts_mock(written)

        with patch.dict(sys.modules, {"edge_tts": mock_mod}):
            from obase.providers._tts.edge_tts import EdgeTTSProvider

            provider = EdgeTTSProvider()
            out = tmp_path / "speech.mp3"
            await provider(
                text="你好，世界",
                voice="zh-CN-XiaoxiaoNeural",
                output_path=out,
            )

        assert out.exists()
        assert out.stat().st_size > 0

    async def test_synthesis_english_voice(self, tmp_path: Path) -> None:
        written: list[Path] = []
        mock_mod = _make_edge_tts_mock(written)

        with patch.dict(sys.modules, {"edge_tts": mock_mod}):
            from obase.providers._tts.edge_tts import EdgeTTSProvider

            provider = EdgeTTSProvider()
            out = tmp_path / "en.mp3"
            await provider(
                text="Hello, world",
                voice="en-US-AriaNeural",
                output_path=out,
            )

        assert out.exists()

    async def test_communicate_receives_rate_and_pitch(self, tmp_path: Path) -> None:
        captured: dict[str, Any] = {}

        async def _save(path: str) -> None:
            Path(path).write_bytes(b"\x00")

        comm_instance = MagicMock()
        comm_instance.save = _save

        def _communicate_cls(text: str, voice: str, **kw: Any) -> MagicMock:
            captured.update({"text": text, "voice": voice, **kw})
            return comm_instance

        mock_mod = MagicMock()
        mock_mod.Communicate = _communicate_cls

        with patch.dict(sys.modules, {"edge_tts": mock_mod}):
            from obase.providers._tts.edge_tts import EdgeTTSProvider

            provider = EdgeTTSProvider()
            await provider(
                text="Hi",
                voice="en-US-GuyNeural",
                output_path=tmp_path / "out.mp3",
                rate="+20%",
                pitch="-5Hz",
            )

        assert captured["rate"] == "+20%"
        assert captured["pitch"] == "-5Hz"
        assert captured["text"] == "Hi"
        assert captured["voice"] == "en-US-GuyNeural"

    async def test_provider_error_propagates(self, tmp_path: Path) -> None:
        async def _fail(path: str) -> None:
            raise RuntimeError("edge-tts network error")

        comm_instance = MagicMock()
        comm_instance.save = _fail
        mock_mod = MagicMock()
        mock_mod.Communicate = MagicMock(return_value=comm_instance)

        with patch.dict(sys.modules, {"edge_tts": mock_mod}):
            from obase.providers._tts.edge_tts import EdgeTTSProvider

            provider = EdgeTTSProvider()
            with pytest.raises(RuntimeError, match="edge-tts network error"):
                await provider(
                    text="Hi",
                    voice="zh-CN-XiaoxiaoNeural",
                    output_path=tmp_path / "out.mp3",
                )

    async def test_extra_kwargs_ignored(self, tmp_path: Path) -> None:
        """Provider tolerates extra kwargs forwarded by tts_synthesize."""
        written: list[Path] = []
        mock_mod = _make_edge_tts_mock(written)

        with patch.dict(sys.modules, {"edge_tts": mock_mod}):
            from obase.providers._tts.edge_tts import EdgeTTSProvider

            provider = EdgeTTSProvider()
            out = tmp_path / "out.mp3"
            # timeout_s is forwarded by tts_synthesize but not used by edge_tts
            await provider(
                text="Hi",
                voice="zh-CN-XiaoxiaoNeural",
                output_path=out,
                timeout_s=30.0,
                unexpected_kwarg="ignored",
            )

        assert out.exists()


class TestRegisterDefaultProvidersTTS:
    def test_register_default_providers_with_edge_tts(self) -> None:
        mock_edge_tts = MagicMock()
        with patch.dict(sys.modules, {"edge_tts": mock_edge_tts}):
            from obase.providers import register_default_providers

            register_default_providers()

        assert ProviderRegistry.has("tts", "edge_tts")

    def test_register_default_providers_without_edge_tts_no_error(self) -> None:
        with patch.dict(sys.modules, {"edge_tts": None}):  # type: ignore[dict-item]
            from obase.providers import register_default_providers

            register_default_providers()  # must not raise
