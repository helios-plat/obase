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
        response_format: Optional[str] = None
    ) -> Dict[str, Any]:
        # 转换格式 (Anthropic 消息格式处理)
        system = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                user_messages.append({"role": m["role"], "content": m["content"]})
        
        # 处理 JSON 强制模式 (Claude 3.5 Sonnet 支持)
        # 简单模拟 response_format="json"
        
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
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

def register_default_providers():
    """注册默认的 LLM/VLM 提供商。"""
    api_key = settings.ANTHROPIC_API_KEY
    if api_key and api_key != "your_key_here":
        registry = ProviderRegistry.get()
        claude = ClaudeCaller(api_key)
        vlm = ClaudeVLMCaller(api_key)
        registry.register_llm("default", claude)
        registry.register_vlm("default", vlm)
    else:
        # Mock providers for dev/CI
        register_mock_providers()

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
    registry.register_llm("default", MockLLM())
    registry.register_vlm("default", MockVLM())
