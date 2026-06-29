"""
LLM / Vision provider 注册与获取
================================
obase/provider_registry.py
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable, Optional, Dict, Any, List
import logging
from importlib.metadata import entry_points

from obase.exceptions import ProviderDiscoveryError, ProviderNotFoundError

logger = logging.getLogger(__name__)


class OBaseRegistryConflict(Exception):
    """Raised when a provider is registered twice without replace=True."""


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
    _images: Dict[str, "ImageGenCaller"] = {}
    _generic: Dict[str, Dict[str, Any]] = {}
    _capabilities: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get(cls) -> ProviderRegistry:
        if cls._instance is None:
            cls._instance = ProviderRegistry()
        return cls._instance

    # ------------------------------------------------------------------
    # Instance registration methods
    # ------------------------------------------------------------------

    def register_llm(self, name: str, caller: LLMCaller, replace: bool = False) -> None:
        if not replace and name in self._llms:
            raise OBaseRegistryConflict(
                f"LLM provider {name!r} already registered. Use replace=True to override."
            )
        self._llms[name] = caller
        logger.info(f"Registered LLM: {name}")

    def register_vlm(self, name: str, caller: VLMCaller, replace: bool = False) -> None:
        if not replace and name in self._vlms:
            raise OBaseRegistryConflict(
                f"VLM provider {name!r} already registered. Use replace=True to override."
            )
        self._vlms[name] = caller
        logger.info(f"Registered VLM: {name}")

    def register_image_gen(self, name: str, caller: "ImageGenCaller", replace: bool = False) -> None:
        if not replace and name in self._images:
            raise OBaseRegistryConflict(
                f"ImageGen provider {name!r} already registered. Use replace=True to override."
            )
        self._images[name] = caller
        logger.info(f"Registered ImageGen: {name}")

    def register_generic(self, category: str, name: str, caller: Any, replace: bool = False) -> None:
        """注册任意 category 的 provider（video/audio/embedding 等）。"""
        if category not in self._generic:
            self._generic[category] = {}
        if not replace and name in self._generic[category]:
            raise OBaseRegistryConflict(
                f"{category} provider {name!r} already registered. Use replace=True to override."
            )
        self._generic[category][name] = caller
        logger.info(f"Registered {category}: {name}")

    # ------------------------------------------------------------------
    # Instance lookup methods
    # ------------------------------------------------------------------

    def llm(self, name: str = "default") -> LLMCaller:
        if name not in self._llms:
            if "default" in self._llms and name != "default":
                return self._llms["default"]
            raise ProviderNotFoundError(f"llm provider {name!r} not registered")
        return self._llms[name]

    def vlm(self, name: str = "default") -> VLMCaller:
        if name not in self._vlms:
            if "default" in self._vlms and name != "default":
                return self._vlms["default"]
            raise ProviderNotFoundError(f"vlm provider {name!r} not registered")
        return self._vlms[name]

    def image_gen(self, name: str = "default") -> "ImageGenCaller":
        if name not in self._images:
            if "default" in self._images and name != "default":
                return self._images["default"]
            raise ProviderNotFoundError(f"image_gen provider {name!r} not registered")
        return self._images[name]

    def generic(self, category: str, name: str = "default") -> Any:
        """获取任意 category 的 provider。"""
        store = self._generic.get(category, {})
        if name not in store:
            if "default" in store and name != "default":
                return store["default"]
            raise ProviderNotFoundError(f"{category} provider {name!r} not registered")
        return store[name]

    # ------------------------------------------------------------------
    # Class-level API (compat shims)
    # ------------------------------------------------------------------

    @classmethod
    def has(cls, category: str, name: str) -> bool:
        """兼容旧 API: has(category, name)"""
        builtin = {"llm": cls._llms, "vlm": cls._vlms, "image_gen": cls._images}
        store = builtin.get(category) or cls._generic.get(category, {})
        return name in store

    @classmethod
    def register(
        cls,
        category: str,
        name: str,
        caller: Any = None,
        replace: bool = False,
        *,
        fn: Any = None,
    ) -> None:
        """兼容旧 API: register(category, name, caller, replace=False).

        Also accepts ``fn`` as a keyword-only alias for ``caller``.
        """
        if caller is None and fn is not None:
            caller = fn
        if caller is None:
            raise TypeError("register() requires a callable via 'caller' or 'fn'")
        if category == "llm":
            cls.get().register_llm(name, caller, replace=replace)
        elif category == "vlm":
            cls.get().register_vlm(name, caller, replace=replace)
        elif category == "image_gen":
            cls.get().register_image_gen(name, caller, replace=replace)
        else:
            cls.get().register_generic(category, name, caller, replace=replace)

    @classmethod
    def list_providers(cls, category: str | None = None) -> list[tuple[str, str]]:
        """Return a list of (category, name) tuples for registered providers.

        Args:
            category: If given, only return providers for that category.
        """
        results: list[tuple[str, str]] = []
        builtin: dict[str, dict] = {
            "llm": cls._llms,
            "vlm": cls._vlms,
            "image_gen": cls._images,
        }
        for cat, store in builtin.items():
            if category is None or cat == category:
                for name in store:
                    results.append((cat, name))
        for cat, store in cls._generic.items():
            if category is None or cat == category:
                for name in store:
                    results.append((cat, name))
        return results

    @classmethod
    def auto_discover(cls, group: str = "obase.providers") -> None:
        """Discover and register providers via setuptools entry points.

        Entry point names must follow the ``{category}.{name}`` format.
        Malformed names are silently skipped. Load failures raise
        ``ProviderDiscoveryError``.
        """
        eps = entry_points(group=group)
        for ep in eps:
            if "." not in ep.name:
                logger.debug("auto_discover: skipping malformed entry point %r", ep.name)
                continue
            category, name = ep.name.split(".", 1)
            try:
                fn = ep.load()
            except Exception as exc:
                raise ProviderDiscoveryError(
                    f"Failed to load provider {name!r} from entry point {ep.name!r}: {exc}"
                ) from exc
            cls.register(category, name, fn)

    # ------------------------------------------------------------------
    # Capabilities API (v0.14.1 compat)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @classmethod
    def clear(cls) -> None:
        """Reset the registry state. Used in tests."""
        cls._instance = None
        cls._llms.clear()
        cls._vlms.clear()
        cls._images.clear()
        cls._generic.clear()
        cls._capabilities.clear()

    @classmethod
    def reset(cls) -> None:
        """Alias for clear(). Used in tests."""
        cls.clear()


__version__ = "0.1.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-29",
    "elements": [
        {"name": "ProviderRegistry", "layer": "obase", "summary": "LLM/VLM 提供商注册中心"},
        {"name": "LLMCaller", "layer": "obase", "summary": "LLM 调用协议"},
        {"name": "VLMCaller", "layer": "obase", "summary": "VLM 调用协议"},
        {"name": "ImageGenCaller", "layer": "obase", "summary": "图像生成调用协议"},
        {"name": "OBaseRegistryConflict", "layer": "obase", "summary": "重复注册异常"},
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
