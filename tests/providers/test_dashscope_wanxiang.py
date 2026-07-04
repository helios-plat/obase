"""Tests for obase DashScopeWanxiangProvider + ProviderRegistry integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from obase.exceptions import ObaseSecretsError
from obase.provider_registry import ProviderRegistry

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_FAKE_KEY = "sk-test-dashscope"
_TASK_ID = "task-abc-123"
_IMAGE_URL = "https://cdn.dashscope.example/out.png"
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _submit_response() -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"output": {"task_id": _TASK_ID}}
    return r


def _poll_response(status: str = "SUCCEEDED") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {
        "output": {
            "task_status": status,
            "results": [{"url": _IMAGE_URL}],
        }
    }
    return r


def _download_response() -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.content = _PNG_BYTES
    return r


def _make_client(
    submit_resp: MagicMock | None = None,
    poll_resp: MagicMock | None = None,
    download_resp: MagicMock | None = None,
) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=submit_resp or _submit_response())
    client.get = AsyncMock(
        side_effect=[
            poll_resp or _poll_response(),
            download_resp or _download_response(),
        ]
    )
    return client


# ---------------------------------------------------------------------------
# registration tests
# ---------------------------------------------------------------------------


class TestWanxiangRegistration:
    def test_register_with_api_key_adds_to_registry(self) -> None:
        with patch("obase.providers._image.dashscope_wanxiang.get_secret", return_value=_FAKE_KEY):
            from obase.providers._image.dashscope_wanxiang import register

            register()

        assert ProviderRegistry.has("image_gen", "wanxiang")

    def test_register_without_api_key_skips_silently(self) -> None:
        with patch(
            "obase.providers._image.dashscope_wanxiang.get_secret",
            side_effect=ObaseSecretsError("not found"),
        ):
            from obase.providers._image.dashscope_wanxiang import register

            register()  # must not raise

        assert not ProviderRegistry.has("image_gen", "wanxiang")

    def test_registered_provider_in_list_providers(self) -> None:
        with patch("obase.providers._image.dashscope_wanxiang.get_secret", return_value=_FAKE_KEY):
            from obase.providers._image.dashscope_wanxiang import register

            register()

        assert ("image_gen", "wanxiang") in ProviderRegistry.list_providers()


# ---------------------------------------------------------------------------
# synthesis tests
# ---------------------------------------------------------------------------


class TestWanxiangProviderSynthesis:
    async def test_successful_generation_writes_file(self, tmp_path: Path) -> None:
        client = _make_client()
        out = tmp_path / "out.png"

        with (
            patch("obase.providers._image.dashscope_wanxiang.get_secret", return_value=_FAKE_KEY),
            patch(
                "obase.providers._image.dashscope_wanxiang.httpx.AsyncClient", return_value=client
            ),
        ):
            from obase.providers._image.dashscope_wanxiang import DashScopeWanxiangProvider

            provider = DashScopeWanxiangProvider()
            await provider(prompt="a sunset", output_path=out)

        assert out.exists()
        assert out.read_bytes() == _PNG_BYTES

    async def test_submit_4xx_raises(self, tmp_path: Path) -> None:
        bad = MagicMock()
        bad.status_code = 400
        bad.text = "Bad Request"
        client = _make_client(submit_resp=bad)

        with (
            patch("obase.providers._image.dashscope_wanxiang.get_secret", return_value=_FAKE_KEY),
            patch(
                "obase.providers._image.dashscope_wanxiang.httpx.AsyncClient", return_value=client
            ),
        ):
            from obase.providers._image.dashscope_wanxiang import (
                DashScopeWanxiangProvider,
                WanxiangError,
            )

            with pytest.raises(WanxiangError, match="submit failed"):
                await DashScopeWanxiangProvider()(prompt="cat", output_path=tmp_path / "x.png")

    async def test_submit_5xx_raises(self, tmp_path: Path) -> None:
        bad = MagicMock()
        bad.status_code = 503
        bad.text = "Service Unavailable"
        client = _make_client(submit_resp=bad)

        with (
            patch("obase.providers._image.dashscope_wanxiang.get_secret", return_value=_FAKE_KEY),
            patch(
                "obase.providers._image.dashscope_wanxiang.httpx.AsyncClient", return_value=client
            ),
        ):
            from obase.providers._image.dashscope_wanxiang import (
                DashScopeWanxiangProvider,
                WanxiangError,
            )

            with pytest.raises(WanxiangError, match="submit failed"):
                await DashScopeWanxiangProvider()(prompt="cat", output_path=tmp_path / "x.png")

    async def test_size_parameter_from_width_height(self, tmp_path: Path) -> None:
        captured_payload: list[dict] = []

        async def _post(url: str, *, headers: dict, content: str) -> MagicMock:
            captured_payload.append(json.loads(content))
            return _submit_response()

        client = _make_client()
        client.post = _post

        with (
            patch("obase.providers._image.dashscope_wanxiang.get_secret", return_value=_FAKE_KEY),
            patch(
                "obase.providers._image.dashscope_wanxiang.httpx.AsyncClient", return_value=client
            ),
        ):
            from obase.providers._image.dashscope_wanxiang import DashScopeWanxiangProvider

            await DashScopeWanxiangProvider()(
                prompt="mountain",
                width=512,
                height=768,
                output_path=tmp_path / "out.png",
            )

        assert captured_payload[0]["parameters"]["size"] == "512*768"

    async def test_seed_injected_into_parameters(self, tmp_path: Path) -> None:
        captured_payload: list[dict] = []

        async def _post(url: str, *, headers: dict, content: str) -> MagicMock:
            captured_payload.append(json.loads(content))
            return _submit_response()

        client = _make_client()
        client.post = _post

        with (
            patch("obase.providers._image.dashscope_wanxiang.get_secret", return_value=_FAKE_KEY),
            patch(
                "obase.providers._image.dashscope_wanxiang.httpx.AsyncClient", return_value=client
            ),
        ):
            from obase.providers._image.dashscope_wanxiang import DashScopeWanxiangProvider

            await DashScopeWanxiangProvider()(
                prompt="cat",
                seed=42,
                output_path=tmp_path / "out.png",
            )

        assert captured_payload[0]["parameters"]["seed"] == 42

    async def test_task_failed_status_raises(self, tmp_path: Path) -> None:
        poll_failed = _poll_response(status="FAILED")
        client = _make_client(poll_resp=poll_failed)

        with (
            patch("obase.providers._image.dashscope_wanxiang.get_secret", return_value=_FAKE_KEY),
            patch(
                "obase.providers._image.dashscope_wanxiang.httpx.AsyncClient", return_value=client
            ),
        ):
            from obase.providers._image.dashscope_wanxiang import (
                DashScopeWanxiangProvider,
                WanxiangError,
            )

            with pytest.raises(WanxiangError, match="FAILED"):
                await DashScopeWanxiangProvider()(prompt="cat", output_path=tmp_path / "x.png")

    async def test_no_api_key_raises_wanxiang_error(self, tmp_path: Path) -> None:
        with patch(
            "obase.providers._image.dashscope_wanxiang.get_secret",
            side_effect=ObaseSecretsError("not found"),
        ):
            from obase.providers._image.dashscope_wanxiang import (
                DashScopeWanxiangProvider,
                WanxiangError,
            )

            with pytest.raises(WanxiangError, match="DASHSCOPE_API_KEY not configured"):
                await DashScopeWanxiangProvider()(prompt="cat", output_path=tmp_path / "x.png")
