"""Tests for obase.mq.EventBus — Redis Pub/Sub topic publish/subscribe."""

from __future__ import annotations

import asyncio
import os

import pytest

from obase.mq import EventBus, MQConnectionError

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")


class TestEventBusValidation:
    async def test_connection_error_when_redis_unreachable(self):
        bus = EventBus(redis_url="redis://nonexistent-host-xyz:6399/0")
        with pytest.raises(MQConnectionError):
            await bus.publish("topic", {"x": 1})


class TestEventBusIntegration:
    @pytest.fixture(autouse=True)
    async def _require_redis(self):
        try:
            import redis.asyncio as redis_lib
        except ImportError:
            pytest.skip("redis package not installed")

        client = redis_lib.Redis.from_url(TEST_REDIS_URL)
        try:
            await client.ping()
        except Exception:
            pytest.skip("Redis not available at TEST_REDIS_URL")
        finally:
            await client.aclose()

    async def test_publish_delivers_to_subscriber(self):
        topic = "it:eventbus:basic"
        bus = EventBus(redis_url=TEST_REDIS_URL)
        received: list[dict] = []

        async def handler(payload: dict) -> None:
            received.append(payload)

        subscribe_task = asyncio.create_task(bus.subscribe(topic, handler, timeout=2.0))
        await asyncio.sleep(0.3)  # let the subscription register with Redis

        publisher = EventBus(redis_url=TEST_REDIS_URL)
        n = await publisher.publish(topic, {"event": "order.created", "order_id": "o1"})
        assert n >= 1

        await subscribe_task
        assert received == [{"event": "order.created", "order_id": "o1"}]

        await bus.close()
        await publisher.close()

    async def test_publish_with_no_subscribers_returns_zero(self):
        bus = EventBus(redis_url=TEST_REDIS_URL)
        n = await bus.publish("it:eventbus:nobody-listening", {"x": 1})
        assert n == 0
        await bus.close()

    async def test_sync_handler_supported(self):
        topic = "it:eventbus:sync-handler"
        bus = EventBus(redis_url=TEST_REDIS_URL)
        received: list[dict] = []

        def handler(payload: dict) -> None:
            received.append(payload)

        subscribe_task = asyncio.create_task(bus.subscribe(topic, handler, timeout=2.0))
        await asyncio.sleep(0.3)

        publisher = EventBus(redis_url=TEST_REDIS_URL)
        await publisher.publish(topic, {"n": 42})

        await subscribe_task
        assert received == [{"n": 42}]

        await bus.close()
        await publisher.close()

    async def test_handler_exception_does_not_kill_loop(self):
        topic = "it:eventbus:bad-handler"
        bus = EventBus(redis_url=TEST_REDIS_URL)
        received: list[dict] = []

        async def flaky_handler(payload: dict) -> None:
            if payload.get("bad"):
                raise RuntimeError("boom")
            received.append(payload)

        subscribe_task = asyncio.create_task(bus.subscribe(topic, flaky_handler, timeout=2.0))
        await asyncio.sleep(0.3)

        publisher = EventBus(redis_url=TEST_REDIS_URL)
        await publisher.publish(topic, {"bad": True})
        await publisher.publish(topic, {"bad": False, "ok": True})

        await subscribe_task
        assert received == [{"bad": False, "ok": True}]

        await bus.close()
        await publisher.close()

    async def test_context_manager_closes_connection(self):
        topic = "it:eventbus:ctx-mgr"
        async with EventBus(redis_url=TEST_REDIS_URL) as bus:
            n = await bus.publish(topic, {"x": 1})
            assert n == 0
