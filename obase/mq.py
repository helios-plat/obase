"""obase.mq — Async message-queue publisher/consumer (aio_pika / RabbitMQ) and
topic pub/sub EventBus (Redis Pub/Sub).

Connection failures always raise — messages are never silently dropped.
Consumers use manual ack: handler failure leaves the message un-acked.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any


class MQConnectionError(Exception):
    """Raised when the broker connection cannot be established or is lost."""


class MQPublisher:
    """Publish messages to a RabbitMQ exchange or the default queue.

    Args:
        url: AMQP connection URL, e.g. ``"amqp://guest:guest@localhost/"``
        routing_key: Default routing key used when *publish()* is called
            without an explicit key.
        exchange: Named exchange to publish to; empty string uses the
            broker default exchange (direct queue routing).
    """

    def __init__(self, url: str, *, routing_key: str = "default", exchange: str = "") -> None:
        self._url = url
        self._default_rk = routing_key
        self._exchange_name = exchange
        self._connection: Any = None
        self._channel: Any = None
        self._exchange: Any = None

    async def connect(self) -> None:
        """Open connection and channel.  Raises *MQConnectionError* on failure."""
        try:
            import aio_pika  # noqa: PLC0415

            self._connection = await aio_pika.connect_robust(self._url)
            self._channel = await self._connection.channel()
            if self._exchange_name:
                self._exchange = await self._channel.declare_exchange(
                    self._exchange_name,
                    aio_pika.ExchangeType.DIRECT,
                    durable=True,
                )
        except (MQConnectionError, ImportError):
            raise
        except Exception as exc:
            raise MQConnectionError(
                f"MQPublisher: failed to connect to {self._url!r}: {exc}"
            ) from exc

    async def publish(self, body: bytes, *, routing_key: str | None = None) -> None:
        """Publish *body* to the broker.

        Args:
            body: Message payload.
            routing_key: Override the default routing key for this message.

        Raises:
            MQConnectionError: If the channel is not open or the publish fails.
        """
        if self._channel is None:
            raise MQConnectionError("MQPublisher: not connected — call connect() first")
        try:
            import aio_pika  # noqa: PLC0415

            rk = routing_key if routing_key is not None else self._default_rk
            msg = aio_pika.Message(body=body)
            target = (
                self._exchange if self._exchange is not None else self._channel.default_exchange
            )
            await target.publish(msg, routing_key=rk)
        except (MQConnectionError, ImportError):
            raise
        except Exception as exc:
            raise MQConnectionError(f"MQPublisher: publish failed: {exc}") from exc

    async def close(self) -> None:
        """Close connection gracefully."""
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                pass

    async def __aenter__(self) -> MQPublisher:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


class MQConsumer:
    """Consume messages from a RabbitMQ queue with manual acknowledgement.

    Each received message is passed to *handler*; it is acked only after
    the handler returns without raising.  On exception the message is
    left un-acked (it will be requeued according to broker policy).

    Args:
        url: AMQP connection URL.
        queue: Name of the queue to consume from (declared durable).
    """

    def __init__(self, url: str, *, queue: str) -> None:
        self._url = url
        self._queue_name = queue
        self._connection: Any = None
        self._channel: Any = None
        self._queue: Any = None

    async def connect(self) -> None:
        """Open connection and declare queue.  Raises *MQConnectionError* on failure."""
        try:
            import aio_pika  # noqa: PLC0415

            self._connection = await aio_pika.connect_robust(self._url)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=1)
            self._queue = await self._channel.declare_queue(self._queue_name, durable=True)
        except (MQConnectionError, ImportError):
            raise
        except Exception as exc:
            raise MQConnectionError(
                f"MQConsumer: failed to connect to {self._url!r}: {exc}"
            ) from exc

    async def consume(
        self,
        handler: Callable[[bytes], Any],
        *,
        timeout: float | None = None,
    ) -> None:
        """Consume messages, calling *handler(body)* for each.

        Acks only on successful handler return.  On handler exception the
        message is not acked and a warning is logged.

        Args:
            handler: Async or sync callable receiving the raw message bytes.
            timeout: If set, stop consuming after this many seconds (useful
                for tests).  None means consume until cancelled.
        """
        if self._queue is None:
            raise MQConnectionError("MQConsumer: not connected — call connect() first")

        async def _on_message(message: Any) -> None:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message.body)
                else:
                    handler(message.body)
                await message.ack()
            except Exception:
                # Do NOT ack — message stays in queue for redelivery
                await message.nack(requeue=True)

        await self._queue.consume(_on_message)
        if timeout is not None:
            await asyncio.sleep(timeout)
        else:
            await asyncio.Future()  # block until cancelled

    async def close(self) -> None:
        """Close connection gracefully."""
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                pass

    async def __aenter__(self) -> MQConsumer:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


class EventBus:
    """Topic-based publish/subscribe over Redis Pub/Sub.

    Simpler than MQPublisher/MQConsumer's exchange/queue model — for
    fire-and-forget event fanout (e.g. order.created, cart.abandoned) where
    no delivery guarantee or persistence is needed. Payloads are JSON-encoded.

    Args:
        redis_url: Redis connection URL, e.g. ``"redis://localhost:6379/0"``.
    """

    def __init__(self, *, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._redis: Any = None

    async def _client(self) -> Any:
        if self._redis is None:
            try:
                import redis.asyncio as redis_lib  # noqa: PLC0415
            except ImportError as exc:
                raise MQConnectionError(
                    "EventBus requires the 'redis' package (obase[cache] extra)"
                ) from exc
            try:
                self._redis = redis_lib.from_url(self._redis_url)
                await self._redis.ping()
            except MQConnectionError:
                raise
            except Exception as exc:
                raise MQConnectionError(
                    f"EventBus: failed to connect to {self._redis_url!r}: {exc}"
                ) from exc
        return self._redis

    async def publish(self, topic: str, payload: dict[str, Any]) -> int:
        """Publish a JSON-encoded payload to `topic`.

        Args:
            topic: Redis Pub/Sub channel name.
            payload: JSON-serializable event payload.

        Returns:
            Number of subscribers that received the message (0 if none are
            currently listening — Pub/Sub does not persist/replay).

        Raises:
            MQConnectionError: Redis unavailable or the publish call failed.
        """
        client = await self._client()
        try:
            return int(await client.publish(topic, json.dumps(payload)))
        except Exception as exc:
            raise MQConnectionError(f"EventBus: publish to {topic!r} failed: {exc}") from exc

    async def subscribe(
        self,
        topic: str,
        handler: Callable[[dict[str, Any]], Any],
        *,
        timeout: float | None = None,
    ) -> None:
        """Subscribe to `topic`, calling `handler(payload)` for each message.

        A handler exception is logged (not re-raised) so one bad message
        doesn't kill the whole listener loop — unlike MQConsumer, Pub/Sub has
        no redelivery/nack concept, so there is nothing to leave un-acked.

        Args:
            topic: Redis Pub/Sub channel name.
            handler: Async or sync callable receiving the decoded payload dict.
            timeout: Stop listening after this many seconds (useful for tests).
                None means listen until the task is cancelled.

        Raises:
            MQConnectionError: Redis unavailable.
        """
        import structlog

        log = structlog.get_logger()
        client = await self._client()
        pubsub = client.pubsub()
        await pubsub.subscribe(topic)
        try:
            deadline = time.monotonic() + timeout if timeout is not None else None
            while deadline is None or time.monotonic() < deadline:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                try:
                    payload = json.loads(message["data"])
                    if asyncio.iscoroutinefunction(handler):
                        await handler(payload)
                    else:
                        handler(payload)
                except Exception as exc:
                    log.warning("obase.mq.eventbus_handler_error", topic=topic, error=str(exc))
        finally:
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()

    async def close(self) -> None:
        """Close the underlying Redis connection, if open."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def __aenter__(self) -> EventBus:
        await self._client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
