"""obase.media_scraper — 媒体内容抓取适配器.

- extract_from_html：纯函数提取 HTML 中的媒体资源（img/video/audio/source）
- scrape：抓取页面 + 提取（httpx 惰性依赖）
- download：媒体二进制下载（带大小/类型校验）

Example:
    >>> items = extract_from_html(html, base_url="https://x.com")
    >>> items[0]["kind"]
    'image'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ["MediaItem", "MediaScraper", "MediaScraperError", "extract_from_html"]

_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
_VIDEO_RE = re.compile(r'<video[^>]+src=["\']([^"\']+)["\']', re.I)
_SOURCE_RE = re.compile(
    r'<source[^>]+src=["\']([^"\']+)["\'][^>]*type=["\']([^"\']+)["\']', re.I
)
_AUDIO_RE = re.compile(r'<audio[^>]+src=["\']([^"\']+)["\']', re.I)


@dataclass
class MediaItem:
    """抓取到的媒体条目。"""

    url: str
    kind: str  # image | video | audio
    mime: str = ""
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "kind": self.kind, "mime": self.mime, "title": self.title}


class MediaScraperError(RuntimeError):
    """抓取失败。"""


def extract_from_html(
    html: str, *, base_url: str = "", max_items: int = 100
) -> list[dict[str, Any]]:
    """从 HTML 提取媒体资源（纯函数）。"""
    items: list[MediaItem] = []

    def add(url: str, kind: str, mime: str = "") -> None:
        url = url.strip()
        if not url or url.startswith("data:"):
            return
        if len(items) >= max_items:
            return
        items.append(MediaItem(url=_resolve(base_url, url), kind=kind, mime=mime))

    for m in _IMG_RE.finditer(html):
        add(m.group(1), "image")
    for m in _VIDEO_RE.finditer(html):
        add(m.group(1), "video")
    for m in _AUDIO_RE.finditer(html):
        add(m.group(1), "audio")
    for m in _SOURCE_RE.finditer(html):
        add(m.group(1), "video" if "video" in m.group(2) else "audio", m.group(2))

    return [i.to_dict() for i in items]


def _resolve(base_url: str, url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        scheme = base_url.split("://")[0] if "://" in base_url else "https"
        return f"{scheme}:{url}"
    if base_url:
        return base_url.rstrip("/") + "/" + url.lstrip("/")
    return url


class MediaScraper:
    """页面媒体抓取器（httpx 惰性依赖）。"""

    def __init__(self, *, user_agent: str = "obase-media-scraper/1.0") -> None:
        self.user_agent = user_agent

    async def scrape(
        self, url: str, *, max_items: int = 100, timeout: float = 15.0
    ) -> dict[str, Any]:
        """抓取页面并提取媒体。"""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx 是 obase 基础依赖
            raise MediaScraperError("httpx not available") from exc
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": self.user_agent}, timeout=timeout, follow_redirects=True
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
        except Exception as exc:
            raise MediaScraperError(f"scrape failed for {url}: {exc}") from exc
        items = extract_from_html(html, base_url=str(response.url), max_items=max_items)
        return {"status": "ok", "url": url, "html_chars": len(html), "items": items}

    async def download(
        self, url: str, *, max_bytes: int = 50 * 1024 * 1024, timeout: float = 30.0
    ) -> dict[str, Any]:
        """下载媒体二进制（大小上限校验）。"""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise MediaScraperError("httpx not available") from exc
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    total = 0
                    chunks: list[bytes] = []
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise MediaScraperError(
                                f"download exceeds max_bytes={max_bytes}: {url}"
                            )
                        chunks.append(chunk)
        except MediaScraperError:
            raise
        except Exception as exc:
            raise MediaScraperError(f"download failed for {url}: {exc}") from exc
        return {
            "status": "ok",
            "url": url,
            "bytes": total,
            "content": b"".join(chunks),
        }
