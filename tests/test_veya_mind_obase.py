"""Tests for Veya 终极前沿认知能力 — obase 层 (1 个).

Covers: kv_cache_shared_memory（跨进程潜空间共享内存管道）.
"""

from __future__ import annotations

import pytest


def _shm_writer(name: str) -> None:
    from obase import KVCacheSharedMemory

    w = KVCacheSharedMemory(shm_name=name, size=4096)
    w.allocate_buffer()
    w.write_latent_state({"from": "child"})
    w.close()


class TestKVCacheSharedMemory:
    async def test_write_read_roundtrip(self):
        from obase import KVCacheSharedMemory

        shm = KVCacheSharedMemory(shm_name="test_latent_bus_1", size=4096)
        try:
            name = shm.allocate_buffer()
            assert name == "test_latent_bus_1"
            assert shm.write_latent_state({"vector": [0.1, 0.2], "token": 42}) is True
            state = shm.read_latent_state()
            assert state == {"vector": [0.1, 0.2], "token": 42}
        finally:
            shm.close()
            shm.unlink()

    async def test_oversize_write_rejected(self):
        from obase import KVCacheSharedMemory

        shm = KVCacheSharedMemory(shm_name="test_latent_bus_2", size=128)
        try:
            shm.allocate_buffer()
            assert shm.write_latent_state({"payload": "x" * 500}) is False
        finally:
            shm.close()
            shm.unlink()

    async def test_empty_read(self):
        from obase import KVCacheSharedMemory

        shm = KVCacheSharedMemory(shm_name="test_latent_bus_3", size=1024)
        try:
            shm.allocate_buffer()
            assert shm.read_latent_state() == {}
        finally:
            shm.close()
            shm.unlink()

    async def test_cross_process_access(self):
        """子进程写入 → 父进程读取（同一命名块）。"""
        import multiprocessing as mp

        from obase import KVCacheSharedMemory

        shm = KVCacheSharedMemory(shm_name="test_latent_bus_4", size=4096)
        try:
            shm.allocate_buffer()
            proc = mp.Process(target=_shm_writer, args=("test_latent_bus_4",))
            proc.start()
            proc.join(timeout=10)
            assert proc.exitcode == 0
            assert shm.read_latent_state() == {"from": "child"}
        finally:
            shm.close()
            shm.unlink()

    async def test_validation(self):
        from obase import KVCacheSharedMemory

        with pytest.raises(ValueError):
            KVCacheSharedMemory(shm_name="")
        with pytest.raises(ValueError):
            KVCacheSharedMemory(shm_name="x", size=0)

    async def test_health(self):
        from obase import KVCacheSharedMemory

        shm = KVCacheSharedMemory(shm_name="test_latent_bus_5", size=1024)
        try:
            assert shm.health()["status"] == "idle"
            shm.allocate_buffer()
            assert shm.health()["status"] == "healthy"
        finally:
            shm.close()
            shm.unlink()
