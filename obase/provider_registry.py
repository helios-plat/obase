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
        response_format: Optional[str] = None
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

__version__ = "0.1.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-13",
    "elements": [
        {"name": "ProviderRegistry", "layer": "obase", "summary": "LLM/VLM 提供商注册中心"},
        {"name": "LLMCaller", "layer": "obase", "summary": "LLM 调用协议"},
        {"name": "VLMCaller", "layer": "obase", "summary": "VLM 调用协议"},
    ]
}
