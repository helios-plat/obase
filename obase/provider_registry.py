"""
LLM / Vision provider 注册与获取
================================
obase/provider_registry.py
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable, Optional, Dict, Any, List
import logging
from abc import abstractmethod

logger = logging.getLogger(__name__)

@runtime_checkable
class LLMCaller(Protocol):
    """LLM 调用协议。"""
    async def __call__(
        self, 
        *, 
        messages: List[Dict[str, str]], 
        max_tokens: int = 1000,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[str] = None,
        system: Optional[str] = None
    ) -> Dict[str, Any]: 
        ...

@runtime_checkable
class VLMCaller(Protocol):
    """Vision-LLM 调用协议。"""
    async def __call__(
        self, 
        *, 
        prompt: str, 
        image_b64: str,
        response_format: str = "text"
    ) -> Dict[str, Any]: 
        ...

class ProviderRegistry:
    """LLM 提供商注册中心（单例）。"""
    _instance: Optional[ProviderRegistry] = None
    _llms: Dict[str, LLMCaller] = {}
    _vlms: Dict[str, VLMCaller] = {}
    _images: Dict[str, ImageGenCaller] = {}

    @classmethod
    def get(cls) -> ProviderRegistry:
        if cls._instance is None:
            cls._instance = ProviderRegistry()
        return cls._instance

    def register_llm(self, name: str, caller: LLMCaller) -> None:
        self._llms[name] = caller
        logger.info(f"Registered LLM: {name}")

    def register_vlm(self, name: str, caller: VLMCaller) -> None:
        self._vlms[name] = caller
        logger.info(f"Registered VLM: {name}")

    def llm(self, name: str = "default") -> LLMCaller:
        if name not in self._llms:
            if "default" in self._llms and name != "default":
                return self._llms["default"]
            raise RuntimeError(f"LLM provider '{name}' not registered")
        return self._llms[name]

    def vlm(self, name: str = "default") -> VLMCaller:
        if name not in self._vlms:
            if "default" in self._vlms and name != "default":
                return self._vlms["default"]
            raise RuntimeError(f"VLM provider '{name}' not registered")
        return self._vlms[name]

    def register_image_gen(self, name: str, caller: "ImageGenCaller") -> None:
        self._images[name] = caller
        logger.info(f"Registered ImageGen: {name}")

    def image_gen(self, name: str = "default") -> "ImageGenCaller":
        if name not in self._images:
            if "default" in self._images and name != "default":
                return self._images["default"]
            raise RuntimeError(f"ImageGen provider '{name}' not registered")
        return self._images[name]

    @classmethod
    def has(cls, category: str, name: str) -> bool:
        """兼容旧 API: has(category, name)"""
        builtin = {"llm": cls._llms, "vlm": cls._vlms, "image_gen": cls._images}
        store = builtin.get(category) or cls._generic.get(category, {})
        return name in store

    # 兼容旧 API: register(category, name, caller, replace=False)
    @classmethod
    def register(cls, category: str, name: str, caller: Any, replace: bool = False) -> None:
        if category == "llm":
            cls.get().register_llm(name, caller)
        elif category == "vlm":
            cls.get().register_vlm(name, caller)
        elif category == "image_gen":
            cls.get().register_image_gen(name, caller)
        else:
            # 通用 category（video/audio/embedding 等）
            cls.get().register_generic(category, name, caller)


    # 通用 category 存储（video/audio/embedding 等任意 category）
    _generic: Dict[str, Dict[str, Any]] = {}

    def register_generic(self, category: str, name: str, caller: Any) -> None:
        """注册任意 category 的 provider（video/audio/embedding 等）。"""
        if category not in self._generic:
            self._generic[category] = {}
        self._generic[category][name] = caller
        logger.info(f"Registered {category}: {name}")

    def generic(self, category: str, name: str = "default") -> Any:
        """获取任意 category 的 provider。"""
        store = self._generic.get(category, {})
        if name not in store:
            if "default" in store and name != "default":
                return store["default"]
            raise RuntimeError(f"{category} provider '{name}' not registered")
        return store[name]

    # capabilities API（v0.14.1 兼容）
    _capabilities: Dict[str, Dict[str, Any]] = {}

    def register_with_capability(
        self, name: str, caller: Any, *, capabilities: Dict[str, Any]
    ) -> None:
        """注册 provider 并附带 capability 元数据（v0.14.1 API）。"""
        self._llms[name] = caller
        self._capabilities[name] = capabilities
        logger.info(f"Registered provider with capabilities: {name}")

    def capabilities(self, name: str | None = None) -> Dict[str, Any]:
        """查询 provider capability 元数据（v0.14.1 API）。"""
        if name is None:
            return dict(self._capabilities)
        return self._capabilities.get(name, {})

    @classmethod
    def clear(cls) -> None:
        """Reset the registry state. Used in tests."""
        cls._instance = None
        cls._llms.clear()
        cls._vlms.clear()
        cls._images.clear()
        cls._generic.clear()
        cls._capabilities.clear()

__version__ = "0.1.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-13",
    "elements": [
        {"name": "ProviderRegistry", "layer": "obase", "summary": "LLM/VLM 提供商注册中心"},
        {"name": "LLMCaller", "layer": "obase", "summary": "LLM 调用协议"},
        {"name": "VLMCaller", "layer": "obase", "summary": "VLM 调用协议"},
        {"name": "ImageGenCaller", "layer": "obase", "summary": "图像生成调用协议"},
    ]
}


@runtime_checkable
class ImageGenCaller(Protocol):
    """图像生成调用协议。"""
    async def __call__(
        self,
        *,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        ...
