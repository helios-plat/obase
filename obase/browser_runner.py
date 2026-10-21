"""obase.browser_runner — Playwright / Chromium 无头浏览器实例管理器.

职责:
- 单实例管理浏览器生命周期（launch / new_page / close / 健康状态）
- 惰性 import playwright（未安装时给出明确错误，不污染无浏览器环境）
- 页面句柄暴露给上层（oprim.browser_fetch_dom / browser_click_element 经协议注入使用）

Example:
    >>> runner = BrowserRunner(headless=True)
    >>> await runner.start()
    >>> page = await runner.new_page()
    >>> await page.goto("https://example.com")
    >>> html = await page.content()
    >>> await runner.close()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["BrowserError", "BrowserRunner", "BrowserPageHandle"]


class BrowserError(RuntimeError):
    """浏览器管理器错误（含 playwright 未安装）。"""


@dataclass
class BrowserPageHandle:
    """对 playwright Page 的最小句柄封装（防上层直接依赖 playwright 类型）。"""

    page: Any
    runner: BrowserRunner

    async def goto(self, url: str, *, timeout_ms: int = 30_000) -> None:
        await self.page.goto(url, timeout=timeout_ms)

    async def content(self) -> str:
        return await self.page.content()

    async def dom(self) -> str:
        """返回页面 DOM（outerHTML 序列化）。"""
        return await self.page.content()

    async def click(self, selector: str, *, timeout_ms: int = 10_000) -> None:
        await self.page.click(selector, timeout=timeout_ms)

    async def screenshot(self, *, path: str | None = None) -> bytes:
        if path is not None:
            await self.page.screenshot(path=path)
            return b""
        return await self.page.screenshot()

    async def close(self) -> None:
        await self.page.close()


class BrowserRunner:
    """无头浏览器实例管理器：单浏览器进程，多页面句柄。

    线程安全注意：playwright API 是 async 单事件循环友好的；
    runner 实例不应跨事件循环复用 —— 每实例绑定一个 loop。
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        executable_path: str | None = None,
        extra_args: list[str] | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.headless = headless
        self.executable_path = executable_path
        self.extra_args = extra_args or ["--no-sandbox", "--disable-dev-shm-usage"]
        self.user_agent = user_agent
        self._browser: Any = None
        self._pages: list[Any] = []

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动浏览器。playwright 未安装时抛 BrowserError。"""
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - 环境相关
            raise BrowserError(
                "playwright is not installed — run `pip install playwright` "
                "and `playwright install chromium`"
            ) from exc

        self._pw = async_playwright()
        pw = await self._pw.start()
        launch_kwargs: dict[str, Any] = {"headless": self.headless}
        if self.executable_path:
            launch_kwargs["executable_path"] = self.executable_path
        if self.extra_args:
            launch_kwargs["args"] = self.extra_args
        self._browser = await pw.chromium.launch(**launch_kwargs)

    async def new_page(self, *, viewport: dict[str, int] | None = None) -> BrowserPageHandle:
        """新建页面句柄。未 start 时自动 start。"""
        if self._browser is None:
            await self.start()
        context = await self._browser.new_context(
            viewport=viewport or {"width": 1280, "height": 800},
            user_agent=self.user_agent,
        )
        page = await context.new_page()
        self._pages.append(page)
        return BrowserPageHandle(page=page, runner=self)

    async def close(self) -> None:
        """关闭浏览器与全部页面。"""
        for page in list(self._pages):
            try:
                await page.close()
            except Exception:  # pragma: no cover - 关闭竞态
                pass
        self._pages.clear()
        if self._browser is not None:
            try:
                await self._browser.close()
            finally:
                self._browser = None
        pw = getattr(self, "_pw", None)
        if pw is not None:
            try:
                await pw.stop()
            except Exception:  # pragma: no cover - 关闭竞态
                pass
            self._pw = None  # type: ignore[attr-defined]

    @property
    def is_running(self) -> bool:
        return self._browser is not None

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self.is_running else "idle",
            "running": self.is_running,
            "pages": len(self._pages),
            "headless": self.headless,
        }

    async def __aenter__(self) -> BrowserRunner:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
