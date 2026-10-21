"""obase.browser_vision_runner — 带 Bounding-Box 的 Headless 浏览器操控适配器.

职责:
- 捕获网页截图并计算交互元素的 Bounding-Box
- 支持 Headless 模式控制
- 为上层视觉导航 (vlm_page_nav) 提供结构化页面状态

设计:
- 不依赖真实浏览器驱动（obase 定位为基础设施接口层）
- 返回结构化页面元素信息（含 bounding box）
- 生产环境可注入 Playwright 实现替换

例:
    >>> runner = BrowserVisionRunner(headless=True)
    >>> state = runner.capture_page_with_bounding_boxes("https://example.com")
    >>> state["url"]
    'https://example.com'
    >>> len(state["elements"]) > 0
    True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["BrowserVisionRunner", "PageElement", "PageState", "VisionRunnerError"]


class VisionRunnerError(RuntimeError):
    """视觉运行器错误."""


@dataclass
class PageElement:
    """页面交互元素描述."""

    element_id: str
    element_type: str  # "input", "button", "link", "select", "image", "form"
    box: list[int]  # [x, y, width, height]
    text: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class PageState:
    """页面状态快照."""

    url: str
    viewport: dict[str, int]  # {"width": ..., "height": ...}
    elements: list[PageElement]
    screenshot_base64: str = ""


class BrowserVisionRunner:
    """带 Bounding-Box 检测的 Headless 浏览器操控适配器.

    设计为接口抽象（非完整浏览器实现）。生产环境可通过注入
    Playwright/Puppeteer 适配器替换为真实渲染。

    线程安全：实例绑定单个事件循环，不跨 loop 复用。
    """

    def __init__(self, *, headless: bool = True) -> None:
        self.headless = headless
        self._running = False

    def capture_page_with_bounding_boxes(self, url: str) -> PageState:
        """捕获网页截图并提取交互元素的 Bounding-Box.

        Args:
            url: 目标网页 URL

        Returns:
            PageState 包含 URL、viewport、元素列表和截图 base64
        """
        # 生产实现应使用 Playwright 的 page.accessibility.snapshot()
        # 或 JavaScript evaluate 提取元素位置信息。
        # 此处为接口参考实现，返回示例结构。
        return PageState(
            url=url,
            viewport={"width": 1280, "height": 800},
            elements=[
                PageElement(
                    element_id="search-input",
                    element_type="input",
                    box=[100, 50, 400, 40],
                    text="",
                    attributes={"placeholder": "Search..."},
                ),
                PageElement(
                    element_id="submit-btn",
                    element_type="button",
                    box=[510, 50, 80, 40],
                    text="Submit",
                    attributes={"type": "submit"},
                ),
                PageElement(
                    element_id="nav-link-1",
                    element_type="link",
                    box=[20, 10, 120, 30],
                    text="Home",
                    attributes={"href": "/"},
                ),
            ],
            screenshot_base64=(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            ),
        )

    def element_at_point(
        self, page_state: PageState, x: int, y: int
    ) -> PageElement | None:
        """根据坐标查找命中的页面元素.

        Args:
            page_state: 页面状态
            x, y: 坐标

        Returns:
            命中的元素或 None
        """
        for elem in page_state.elements:
            bx, by, bw, bh = elem.box
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return elem
        return None

    def find_element_by_id(
        self, page_state: PageState, element_id: str
    ) -> PageElement | None:
        """按 ID 查找元素.

        Args:
            page_state: 页面状态
            element_id: 元素 ID

        Returns:
            找到的元素或 None
        """
        for elem in page_state.elements:
            if elem.element_id == element_id:
                return elem
        return None

    def health(self) -> dict[str, Any]:
        """健康检查."""
        return {
            "status": "healthy",
            "headless": self.headless,
            "running": self._running,
        }
