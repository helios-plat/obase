from __future__ import annotations

import time

import pytest
import yaml

from obase.exceptions import OBaseError, RateLimitExceeded
from obase.rate_limit import RateLimiter, RateLimitRegistry


class TestRateLimiter:
    async def test_acquire_within_rate(self):
        rl = RateLimiter(rate=5, period_seconds=1.0)
        for _ in range(5):
            await rl.acquire()

    async def test_acquire_blocks_when_full(self):
        rl = RateLimiter(rate=2, period_seconds=0.2)
        await rl.acquire()
        await rl.acquire()
        start = time.monotonic()
        await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.1

    async def test_acquire_timeout_raises(self):
        rl = RateLimiter(rate=1, period_seconds=10.0)
        await rl.acquire()
        with pytest.raises(RateLimitExceeded):
            await rl.acquire(timeout=0.05)

    def test_invalid_rate(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=0, period_seconds=1.0)

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            RateLimiter(rate=5, period_seconds=0)

    def test_properties(self):
        rl = RateLimiter(rate=10, period_seconds=2.0)
        assert rl.rate == 10
        assert rl.period_seconds == 2.0


class TestRateLimitRegistry:
    def test_register_and_get(self):
        RateLimitRegistry.register("test-api", rate=10, period_seconds=1.0)
        rl = RateLimitRegistry.get("test-api")
        assert rl.rate == 10
        assert rl.period_seconds == 1.0

    def test_get_missing_raises(self):
        with pytest.raises(OBaseError, match="not found"):
            RateLimitRegistry.get("nonexistent-limiter")

    def test_has(self):
        RateLimitRegistry.register("exists", rate=5, period_seconds=1.0)
        assert RateLimitRegistry.has("exists") is True
        assert RateLimitRegistry.has("nope") is False

    def test_load_from_yaml(self, tmp_path):
        data = [
            {"name": "api-a", "rate": 10, "period_seconds": 1.0},
            {"name": "api-b", "rate": 5, "period_seconds": 60.0},
        ]
        p = tmp_path / "limits.yaml"
        p.write_text(yaml.dump(data))
        RateLimitRegistry.load_from_yaml(p)
        assert RateLimitRegistry.has("api-a")
        assert RateLimitRegistry.has("api-b")
        assert RateLimitRegistry.get("api-b").rate == 5

    def test_clear(self):
        RateLimitRegistry.register("temp", rate=1, period_seconds=1.0)
        assert RateLimitRegistry.has("temp")
        RateLimitRegistry.clear()
        assert not RateLimitRegistry.has("temp")
