import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from obase.gpu import GpuScheduler, ModelRegistry, LocalModelProvider

class MockModelProvider:
    def __init__(self, name: str):
        self.name = name
        self._loaded = False
        self.load_called = 0
        self.unload_called = 0

    async def load(self) -> None:
        self.load_called += 1
        self._loaded = True

    async def unload(self) -> None:
        self.unload_called += 1
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

@pytest.mark.asyncio
async def test_protocol_check():
    """Test if MockModelProvider matches the LocalModelProvider protocol."""
    mock = MockModelProvider("test")
    assert isinstance(mock, LocalModelProvider)

@pytest.mark.asyncio
async def test_acquire_vram_zero():
    """acquire vram=0 should yield immediately without acquiring lock."""
    scheduler = GpuScheduler()
    # Mock the lock to track calls
    scheduler._vram_lock = MagicMock(wraps=asyncio.Lock())
    
    async with scheduler.acquire(0):
        pass
    
    assert scheduler._vram_lock.acquire.call_count == 0

@pytest.mark.asyncio
async def test_acquire_vram_positive():
    """acquire vram>0 should acquire the lock."""
    scheduler = GpuScheduler()
    
    async with scheduler.acquire(100):
        assert scheduler._vram_lock.locked()
    
    assert not scheduler._vram_lock.locked()

@pytest.mark.asyncio
async def test_acquire_serial():
    """acquire vram>0 should be serial."""
    scheduler = GpuScheduler()
    order = []

    async def task(name, delay):
        async with scheduler.acquire(100):
            order.append(f"{name}_start")
            await asyncio.sleep(delay)
            order.append(f"{name}_end")

    await asyncio.gather(task("A", 0.1), task("B", 0.05))
    
    # B should wait for A to finish
    assert order == ["A_start", "A_end", "B_start", "B_end"]

@pytest.mark.asyncio
async def test_unload_all_except():
    """unload_all_except should unload others but keep the specified one."""
    registry = ModelRegistry()
    m1 = MockModelProvider("m1")
    m2 = MockModelProvider("m2")
    m3 = MockModelProvider("m3")
    
    registry.register("m1", m1)
    registry.register("m2", m2)
    registry.register("m3", m3)
    
    await m1.load()
    await m2.load()
    await m3.load()
    
    await registry.unload_all_except("m1")
    
    assert m1.is_loaded() is True
    assert m2.is_loaded() is False
    assert m3.is_loaded() is False
    assert m2.unload_called == 1
    assert m3.unload_called == 1

@pytest.mark.asyncio
async def test_ensure_available_trigger_unload():
    """ensure_available should trigger unload_all_except."""
    registry = ModelRegistry()
    m1 = MockModelProvider("m1")
    m2 = MockModelProvider("m2")
    registry.register("m1", m1)
    registry.register("m2", m2)
    
    await m2.load()
    
    scheduler = GpuScheduler(registry=registry)
    with patch.object(scheduler, 'free_vram_mb', new_callable=AsyncMock) as mock_free:
        mock_free.return_value = 1000.0
        
        success = await scheduler.ensure_available("m1", 500)
        
        assert success is True
        assert m2.is_loaded() is False
        assert m1.is_loaded() is True

@pytest.mark.asyncio
async def test_free_vram_fallback():
    """Test fallback logic for free_vram_mb."""
    scheduler = GpuScheduler()
    
    # Mock pynvml and subprocess
    with patch("obase.gpu.pynvml", None):
        with patch("asyncio.create_subprocess_shell") as mock_shell:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"1234\n", b"")
            mock_process.returncode = 0
            mock_shell.return_value = mock_process
            
            vram = await scheduler.free_vram_mb()
            assert vram == 1234.0

@pytest.mark.asyncio
async def test_lifecycle():
    """Test register + load + unload lifecycle."""
    registry = ModelRegistry()
    m1 = MockModelProvider("m1")
    registry.register("m1", m1)
    
    await registry.load("m1")
    assert m1.is_loaded() is True
    assert m1.load_called == 1
    
    # Load again should not trigger another load
    await registry.load("m1")
    assert m1.load_called == 1
    
    await registry.unload("m1")
    assert m1.is_loaded() is False
    assert m1.unload_called == 1

@pytest.mark.asyncio
async def test_cancellation_safety():
    """CancelledError should not leave the lock held."""
    scheduler = GpuScheduler()
    
    async def task():
        try:
            async with scheduler.acquire(100):
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    t = asyncio.create_task(task())
    await asyncio.sleep(0.1) # Let it acquire the lock
    assert scheduler._vram_lock.locked()
    
    t.cancel()
    await asyncio.sleep(0.1)
    
    assert not scheduler._vram_lock.locked()
    
    # Should be able to acquire again
    async with scheduler.acquire(100):
        assert scheduler._vram_lock.locked()
