"""
obase.gpu — GPU Resource Scheduler and Model Management
=======================================================
G1 + G2 Merger + G3 Protocol Implementation.

This module provides infrastructure for managing GPU VRAM and local model 
lifecycle (load/unload) to prevent OOM in concurrent environments.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Dict, Optional, Any, Protocol, runtime_checkable
from contextlib import asynccontextmanager

# Optional imports for hardware interaction
try:
    import pynvml
except ImportError:
    pynvml = None

try:
    import torch
except ImportError:
    torch = None

logger = logging.getLogger(__name__)

@runtime_checkable
class LocalModelProvider(Protocol):
    """
    Protocol for local model providers. 
    Enables GpuScheduler to manage model lifecycle.
    """
    async def load(self) -> None:
        """Load the model into GPU memory."""
        ...

    async def unload(self) -> None:
        """Unload the model from GPU memory."""
        ...

    def is_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        ...


class ModelRegistry:
    """
    Registry for managing multiple local model providers.
    Independently instantiable for testing/mocking.
    """
    def __init__(self) -> None:
        self._providers: Dict[str, LocalModelProvider] = {}

    def register(self, model_key: str, provider: LocalModelProvider) -> None:
        """Register a model provider."""
        self._providers[model_key] = provider

    async def load(self, model_key: str) -> None:
        """Load a specific model."""
        if provider := self._providers.get(model_key):
            if not provider.is_loaded():
                await provider.load()
        else:
            raise KeyError(f"Model {model_key} not registered")

    async def unload(self, model_key: str) -> None:
        """Unload a specific model."""
        if provider := self._providers.get(model_key):
            if provider.is_loaded():
                await provider.unload()

    async def unload_all_except(self, keep_model_key: str) -> None:
        """Unload all models except the specified one."""
        for key, provider in self._providers.items():
            if key != keep_model_key and provider.is_loaded():
                logger.info(f"Unloading model {key} to free VRAM")
                await provider.unload()


class GpuScheduler:
    """
    Singleton GPU scheduler for VRAM management and model coordination.
    """
    _instance: Optional[GpuScheduler] = None

    def __init__(self, registry: Optional[ModelRegistry] = None) -> None:
        self.registry = registry or ModelRegistry()
        self._vram_lock = asyncio.Lock()

    @classmethod
    def get(cls) -> GpuScheduler:
        """Get or create the GpuScheduler singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def free_vram_mb(self) -> float:
        """
        Query available GPU VRAM in MB.
        Priority: pynvml -> nvidia-smi -> default(0.0).
        """
        # 1. Try pynvml
        if pynvml:
            try:
                pynvml.nvmlInit()
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                pynvml.nvmlShutdown()
                return float(info.free) / 1024 / 1024
            except Exception as e:
                logger.debug(f"pynvml query failed: {e}")

        # 2. Fallback to nvidia-smi
        try:
            cmd = "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits"
            # Use asyncio for command execution to remain fully async
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                return float(stdout.decode().strip())
        except Exception as e:
            logger.debug(f"nvidia-smi query failed: {e}")

        # 3. Default fallback
        return 0.0

    async def ensure_available(self, model_key: str, required_vram_mb: float) -> bool:
        """
        Ensure VRAM and model are available.
        Unloads other models if necessary.
        """
        await self.registry.unload_all_except(model_key)
        
        if torch and torch.cuda.is_available():
            # torch.cuda.empty_cache() is synchronous, but we can't do much about it
            torch.cuda.empty_cache()
            
        free_mb = await self.free_vram_mb()
        if free_mb >= required_vram_mb:
            await self.registry.load(model_key)
            return True
        
        logger.warning(f"Insufficient VRAM for {model_key}: {free_mb:.1f}MB < {required_vram_mb:.1f}MB")
        return False

    @asynccontextmanager
    async def acquire(self, required_vram_mb: float = 0):
        """
        Async context manager to acquire GPU resources.
        If vram == 0, yields immediately without locking.
        """
        if required_vram_mb <= 0:
            yield
            return

        async with self._vram_lock:
            # Serialized access for VRAM-heavy operations
            yield
