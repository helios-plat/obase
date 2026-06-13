"""obase.mq — Async message-queue publisher and consumer (aio_pika / RabbitMQ).

Connection failures always raise — messages are never silently dropped.
Consumers use manual ack: handler failure leaves the message un-acked.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
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
            raise MQConnectionError(f"MQPublisher: failed to connect to {self._url!r}: {exc}") from exc

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
            target = self._exchange if self._exchange is not None else self._channel.default_exchange
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

    async def __aenter__(self) -> "MQPublisher":
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
            raise MQConnectionError(f"MQConsumer: failed to connect to {self._url!r}: {exc}") from exc

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

    async def __aenter__(self) -> "MQConsumer":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
