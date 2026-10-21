import pytest
from obase.tv_cache import SlidingWindowRateGate, TTLCache

def test_ttl_cache_fresh_value():
    now = [10.0]
    cache = TTLCache(clock=lambda: now[0])
    cache.store("key", {"price": 1}, ttl_seconds=2, stale_seconds=5)
    assert cache.lookup("key") == (True, {"price": 1}, False)

def test_stale_value_requires_opt_in():
    now = [0.0]
    cache = TTLCache(clock=lambda: now[0])
    cache.store("key", "value", ttl_seconds=1, stale_seconds=5)
    now[0] = 2
    assert cache.lookup("key") == (False, None, False)
    assert cache.lookup("key", allow_stale=True) == (True, "value", True)

def test_entry_expires_after_stale_window():
    now = [0.0]
    cache = TTLCache(clock=lambda: now[0])
    cache.store("key", "value", ttl_seconds=1, stale_seconds=1)
    now[0] = 3
    assert cache.lookup("key", allow_stale=True) == (False, None, False)
    assert len(cache) == 0

def test_lru_evicts_least_recently_used():
    cache = TTLCache(max_entries=2)
    cache.store("a", 1, 20)
    cache.store("b", 2, 20)
    cache.lookup("a")
    cache.store("c", 3, 20)
    assert cache.lookup("b")[0] is False
    assert cache.lookup("a")[1] == 1
    assert len(cache) == 2

def test_cache_rejects_invalid_configuration_and_clears():
    with pytest.raises(ValueError): TTLCache(max_entries=0)
    with pytest.raises(ValueError): TTLCache().store("key", 1, -1)
    cache = TTLCache(); cache.store("key", 1, 20); cache.clear()
    assert len(cache) == 0

def test_rate_gate_enforces_minimum_interval():
    now, delays = [0.0], []
    def sleep(delay):
        delays.append(delay)
        now[0] += delay
    gate = SlidingWindowRateGate(.25, clock=lambda: now[0], sleeper=sleep)
    gate.acquire(); gate.acquire()
    assert delays == [.25]
