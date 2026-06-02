"""DashScope wanxiang text-to-image provider (阿里云通义万相)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from obase.exceptions import OBaseError, ObaseSecretsError
from obase.provider_registry import ProviderRegistry
from obase.secrets import get_secret


class WanxiangError(OBaseError):
    """DashScope wanxiang generation failed."""


_SUBMIT_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
_STATUS_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
_DEFAULT_MODEL = "wanx2.1-t2i-turbo"
_POLL_INTERVAL = 2.0
_MAX_POLLS = 60


class DashScopeWanxiangProvider:
    """Async-callable image generation provider using DashScope wanxiang.

    Registers as ProviderRegistry(category='image_gen', name='wanxiang').

    Uses DashScope async task API: submit → poll → download.
    Requires env: DASHSCOPE_API_KEY.

    Usage::

        ProviderRegistry.register("image_gen", "wanxiang", DashScopeWanxiangProvider())
    """

    async def __call__(
        self,
        *,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        output_path: Path,
        seed: int | None = None,
        timeout_s: float = 120.0,
        extra: dict[str, Any] | None = None,
        **_: Any,
    ) -> None:
        """Generate image via DashScope wanxiang async task API.

        Args:
            prompt: Text prompt for generation.
            width: Output width in pixels.
            height: Output height in pixels.
            output_path: Destination file path (written as PNG/JPEG bytes).
            seed: Optional seed for reproducibility.
            timeout_s: Total timeout across submit + poll + download.
            extra: Additional parameters passed to DashScope API.
        """
        try:
            api_key = get_secret("DASHSCOPE_API_KEY")
        except ObaseSecretsError as exc:
            raise WanxiangError("DASHSCOPE_API_KEY not configured") from exc

        extra = extra or {}
        parameters: dict[str, Any] = {
            "size": f"{width}*{height}",
            **({"seed": seed} if seed is not None else {}),
            **extra,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": extra.get("model", _DEFAULT_MODEL),
            "input": {"prompt": prompt},
            "parameters": parameters,
        }

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            task_id = await self._submit(client, headers, payload)
            image_url = await self._poll(client, headers, task_id)
            await self._download(client, image_url, output_path)

    async def _submit(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> str:
        resp = await client.post(_SUBMIT_URL, headers=headers, content=json.dumps(payload))
        if resp.status_code >= 400:
            raise WanxiangError(f"DashScope submit failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        task_id: str = data["output"]["task_id"]
        return task_id

    async def _poll(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        task_id: str,
    ) -> str:
        for _ in range(_MAX_POLLS):
            resp = await client.get(_STATUS_URL.format(task_id=task_id), headers=headers)
            if resp.status_code >= 400:
                raise WanxiangError(f"DashScope poll failed: {resp.status_code} {resp.text[:200]}")
            data = resp.json()
            status = data["output"]["task_status"]
            if status == "SUCCEEDED":
                return str(data["output"]["results"][0]["url"])
            if status in ("FAILED", "CANCELED"):
                raise WanxiangError(f"DashScope task {status}: {data}")
            await asyncio.sleep(_POLL_INTERVAL)
        raise WanxiangError(f"DashScope task timed out after {_MAX_POLLS} polls")

    async def _download(
        self,
        client: httpx.AsyncClient,
        url: str,
        output_path: Path,
    ) -> None:
        resp = await client.get(url)
        if resp.status_code >= 400:
            raise WanxiangError(f"Image download failed: {resp.status_code}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.content)


def register(*, replace: bool = False) -> None:
    """Register DashScopeWanxiangProvider if DASHSCOPE_API_KEY is configured.

    Silently skips if the key is absent (allows environments without DashScope
    to import obase without error).
    """
    try:
        get_secret("DASHSCOPE_API_KEY")
    except ObaseSecretsError:
        return
    ProviderRegistry.register("image_gen", "wanxiang", DashScopeWanxiangProvider(), replace=replace)
