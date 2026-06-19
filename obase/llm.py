"""
LLM 提供商实现 (Anthropic / Claude)
==================================
obase/llm.py
"""

from __future__ import annotations
import os
import json
import base64
from typing import List, Dict, Any, Optional
from anthropic import AsyncAnthropic
from obase.config import settings
from obase.provider_registry import ProviderRegistry

class ClaudeCaller:
    """Anthropic Claude API 调用封装。"""
    
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20240620"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def __call__(
        self, 
        *, 
        messages: List[Dict[str, str]], 
        max_tokens: int = 1000,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        # 转换格式 (Anthropic 消息格式处理)
        system_prompt = system or ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_prompt = m["content"]
            else:
                user_messages.append({"role": m["role"], "content": m["content"]})
        
        # 处理 JSON 强制模式 (Claude 3.5 Sonnet 支持)
        # 简单模拟 response_format="json"
        
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=user_messages,
        )
        
        content = response.content[0].text
        
        return {
            "content": content,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        }

class ClaudeVLMCaller:
    """Claude Vision 调用封装。"""
    
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20240620"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def __call__(
        self, 
        *, 
        prompt: str, 
        image_b64: str,
        response_format: str = "text"
    ) -> Dict[str, Any]:
        
        # 如果 image_b64 是本地路径，则读取并编码 (可选，协议要求是 b64)
        
        message_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64,
                },
            },
            {
                "type": "text",
                "text": prompt
            }
        ]
        
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {"role": "user", "content": message_content}
            ],
        )
        
        raw_text = response.content[0].text
        
        # 简单解析 JSON 如果要求的话
        parsed = raw_text
        if response_format == "json":
            # 尝试从 markdown 代码块中提取
            if "```json" in raw_text:
                json_str = raw_text.split("```json")[1].split("```")[0].strip()
                try:
                    parsed = json.loads(json_str)
                except:
                    pass
            else:
                try:
                    parsed = json.loads(raw_text)
                except:
                    pass
                    
        return {
            "content": parsed,
            "raw_text": raw_text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        }



# ---------------------------------------------------------------------------
# DeepSeekCaller — OpenAI 兼容接口，中国网信办已备案
# ---------------------------------------------------------------------------

class DeepSeekCaller:
    """DeepSeek API 调用封装（OpenAI 兼容接口）。

    DeepSeek 已在中国网信办完成生成式人工智能服务备案，
    适用于面向中国大陆用户的合规生产环境。

    Example:
        >>> caller = DeepSeekCaller(api_key="sk-...", model="deepseek-chat")
    """

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self.api_key = api_key
        self.model = model

    async def __call__(
        self,
        *,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        import httpx
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "content": content,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        }


# ---------------------------------------------------------------------------
# OpenAICaller — GPT-4o / GPT-4o-mini 等
# ---------------------------------------------------------------------------

class OpenAICaller:
    """OpenAI API 调用封装（GPT-4o / GPT-4o-mini）。

    Example:
        >>> caller = OpenAICaller(api_key="sk-...", model="gpt-4o-mini")
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model

    async def __call__(
        self,
        *,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        import httpx
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        return {
            "content": content,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        }


# ---------------------------------------------------------------------------
# QwenCaller — 阿里云 DashScope Qwen 系列，中国已备案
# ---------------------------------------------------------------------------

class QwenCaller:
    """阿里云 DashScope Qwen 调用封装。

    中国网信办已备案，适用于合规生产环境。
    model: qwen-plus / qwen-max / qwen-turbo / qwen3-235b-a22b 等。

    Example:
        >>> caller = QwenCaller(api_key="sk-...", model="qwen-plus")
    """

    def __init__(self, api_key: str, model: str = "qwen-plus"):
        self.api_key = api_key
        self.model = model

    async def __call__(
        self,
        *,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        import httpx
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": {"messages": api_messages},
            "parameters": {"max_tokens": max_tokens},
        }
        if response_format == "json":
            payload["parameters"]["result_format"] = "message"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["output"]["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "content": content,
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        }


# ---------------------------------------------------------------------------
# GeminiCaller — Google Gemini
# ---------------------------------------------------------------------------

class GeminiCaller:
    """Google Gemini API 调用封装。

    Example:
        >>> caller = GeminiCaller(api_key="AIza...", model="gemini-1.5-flash")
    """

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.model = model

    async def __call__(
        self,
        *,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        import httpx
        # 转换为 Gemini 格式
        contents = []
        system_text = system or ""
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        return {
            "content": content,
            "usage": {
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
            },
        }


def register_default_providers():
    """注册默认 LLM/VLM 提供商。

    优先级（可通过环境变量配置）：
      LLM: DEEPSEEK_API_KEY > QWEN_API_KEY > ANTHROPIC_API_KEY > OPENAI_API_KEY > Mock
      VLM: ANTHROPIC_API_KEY > GEMINI_API_KEY > Mock
    中国合规优先（DeepSeek/Qwen 已在网信办备案）。

    Example:
        >>> register_default_providers()
    """
    registry = ProviderRegistry.get()

    # --- LLM 注册（按优先级，首个可用的注册为 default）---
    _llm_registered = False

    deepseek_key = getattr(settings, "DEEPSEEK_API_KEY", None)
    if deepseek_key and deepseek_key not in ("", "your_key_here"):
        registry.register_llm("default", DeepSeekCaller(deepseek_key))
        registry.register_llm("deepseek", DeepSeekCaller(deepseek_key))
        _llm_registered = True

    qwen_key = getattr(settings, "QWEN_API_KEY", None) or getattr(settings, "DASHSCOPE_API_KEY", None)
    if qwen_key and qwen_key not in ("", "your_key_here"):
        caller = QwenCaller(qwen_key)
        if not _llm_registered:
            registry.register_llm("default", caller)
            _llm_registered = True
        registry.register_llm("qwen", caller)

    anthropic_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if anthropic_key and anthropic_key not in ("", "your_key_here"):
        caller = ClaudeCaller(anthropic_key)
        if not _llm_registered:
            registry.register_llm("default", caller)
            _llm_registered = True
        registry.register_llm("anthropic", caller)
        registry.register_llm("claude", caller)

    openai_key = getattr(settings, "OPENAI_API_KEY", None)
    if openai_key and openai_key not in ("", "your_key_here"):
        caller = OpenAICaller(openai_key)
        if not _llm_registered:
            registry.register_llm("default", caller)
            _llm_registered = True
        registry.register_llm("openai", caller)

    # --- VLM 注册 ---
    _vlm_registered = False
    if anthropic_key and anthropic_key not in ("", "your_key_here"):
        registry.register_vlm("default", ClaudeVLMCaller(anthropic_key))
        registry.register_vlm("claude", ClaudeVLMCaller(anthropic_key))
        _vlm_registered = True

    gemini_key = getattr(settings, "GEMINI_API_KEY", None)
    if gemini_key and gemini_key not in ("", "your_key_here"):
        # Gemini 支持多模态，注册为备用 VLM
        if not _vlm_registered:
            registry.register_vlm("default", GeminiCaller(gemini_key))
            _vlm_registered = True
        registry.register_vlm("gemini", GeminiCaller(gemini_key))
        registry.register_llm("gemini", GeminiCaller(gemini_key))
        if not _llm_registered:
            registry.register_llm("default", GeminiCaller(gemini_key))
            _llm_registered = True

    # 独立判断：LLM 和 VLM 分别 fallback，互不影响
    if not _llm_registered:
        registry.register_llm("default", _MockLLM())
    if not _vlm_registered:
        registry.register_vlm("default", _MockVLM())



# ---------------------------------------------------------------------------
# Mock providers（开发/CI 用）
# ---------------------------------------------------------------------------

class _MockLLM:
    async def __call__(self, **kwargs):
        return {"content": "Mock Response", "usage": {"input_tokens": 0, "output_tokens": 0}}

class _MockVLM:
    async def __call__(self, **kwargs):
        return {"content": {"questions": []}, "raw_text": "Mock VLM Response",
                "usage": {"input_tokens": 0, "output_tokens": 0}}

def register_mock_providers():
    """注册用于开发/CI 的 Mock 提供商。"""
    class MockLLM:
        async def __call__(self, **kwargs):
            return {"content": "Mock Response", "usage": {"input_tokens": 0, "output_tokens": 0}}
            
    class MockVLM:
        async def __call__(self, **kwargs):
            # 默认返回一个空的 questions 列表
            return {
                "content": {"questions": []}, 
                "raw_text": "Mock VLM Response", 
                "usage": {"input_tokens": 0, "output_tokens": 0}
            }
            
    registry = ProviderRegistry.get()
    registry.register_llm("default", _MockLLM())
    registry.register_vlm("default", _MockVLM())
