"""Batch A tests: canonical_json, sha256_hash, mq, hmmlearn_runtime."""
from __future__ import annotations

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from obase.canonical_json import canonical_json
from obase.sha256_hash import sha256_hash


# ─────────────────────────── canonical_json ────────────────────────────


class TestCanonicalJson:
    def test_simple_dict(self):
        result = canonical_json({"b": 2, "a": 1})
        data = json.loads(result)
        assert data == {"a": 1, "b": 2}

    def test_key_order_independence(self):
        a = canonical_json({"z": 3, "a": 1, "m": 2})
        b = canonical_json({"a": 1, "m": 2, "z": 3})
        assert a == b

    def test_nested_dict_sorted(self):
        obj = {"outer": {"beta": 2, "alpha": 1}, "key": "val"}
        raw = json.loads(canonical_json(obj))
        assert list(raw["outer"].keys()) == ["alpha", "beta"]

    def test_numpy_integer(self):
        import numpy as np

        result = canonical_json({"v": np.int64(42)})
        assert json.loads(result) == {"v": 42}

    def test_numpy_float(self):
        import numpy as np

        result = canonical_json({"v": np.float64(3.14)})
        parsed = json.loads(result)
        assert abs(parsed["v"] - 3.14) < 1e-10

    def test_numpy_array(self):
        import numpy as np

        result = canonical_json({"arr": np.array([1, 2, 3])})
        assert json.loads(result) == {"arr": [1, 2, 3]}

    def test_same_body_different_construction(self):
        obj1 = {"x": 1, "y": [2, 3]}
        obj2 = dict(y=[2, 3], x=1)
        assert canonical_json(obj1) == canonical_json(obj2)

    def test_returns_bytes(self):
        assert isinstance(canonical_json({"k": "v"}), bytes)

    def test_unicode_not_escaped(self):
        result = canonical_json({"msg": "你好"})
        assert "你好".encode() in result

    def test_float_precision_stable(self):
        a = canonical_json({"f": 1.0 / 3.0})
        b = canonical_json({"f": 1.0 / 3.0})
        assert a == b


# ─────────────────────────── sha256_hash ────────────────────────────


class TestSha256Hash:
    def test_known_vector_abc(self):
        expected = hashlib.sha256(b"abc").digest()
        assert sha256_hash(b"abc") == expected

    def test_known_vector_empty(self):
        expected = hashlib.sha256(b"").digest()
        assert sha256_hash(b"") == expected

    def test_output_length_32(self):
        assert len(sha256_hash(b"hello world")) == 32

    def test_returns_bytes(self):
        assert isinstance(sha256_hash(b"data"), bytes)

    def test_large_input(self):
        data = b"x" * (10 * 1024 * 1024)  # 10 MB
        result = sha256_hash(data)
        assert len(result) == 32
        assert result == hashlib.sha256(data).digest()

    def test_different_inputs_differ(self):
        assert sha256_hash(b"a") != sha256_hash(b"b")

    def test_deterministic(self):
        assert sha256_hash(b"test") == sha256_hash(b"test")


# ─────────────────────────── mq ────────────────────────────


class TestMQPublisher:
    @pytest.mark.asyncio
    async def test_connect_failure_raises(self):
        """Connection failure must raise MQConnectionError, not be silently swallowed."""
        from obase.mq import MQConnectionError, MQPublisher

        with patch("aio_pika.connect_robust", side_effect=OSError("refused")):
            pub = MQPublisher("amqp://bad-host/")
            with pytest.raises(MQConnectionError):
                await pub.connect()

    @pytest.mark.asyncio
    async def test_publish_without_connect_raises(self):
        from obase.mq import MQConnectionError, MQPublisher

        pub = MQPublisher("amqp://localhost/")
        with pytest.raises(MQConnectionError):
            await pub.publish(b"hello")

    @pytest.mark.asyncio
    async def test_publish_calls_exchange_publish(self):
        from obase.mq import MQPublisher

        mock_conn = AsyncMock()
        mock_chan = AsyncMock()
        mock_exchange = AsyncMock()
        mock_chan.default_exchange = mock_exchange
        mock_conn.channel = AsyncMock(return_value=mock_chan)

        with patch("aio_pika.connect_robust", return_value=mock_conn):
            pub = MQPublisher("amqp://localhost/", routing_key="q")
            await pub.connect()
            await pub.publish(b"payload")
            mock_exchange.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_custom_routing_key(self):
        from obase.mq import MQPublisher

        mock_conn = AsyncMock()
        mock_chan = AsyncMock()
        mock_exchange = AsyncMock()
        mock_chan.default_exchange = mock_exchange
        mock_conn.channel = AsyncMock(return_value=mock_chan)

        with patch("aio_pika.connect_robust", return_value=mock_conn):
            pub = MQPublisher("amqp://localhost/", routing_key="default")
            await pub.connect()
            await pub.publish(b"data", routing_key="override")
            call_kwargs = mock_exchange.publish.call_args
            assert call_kwargs.kwargs.get("routing_key") == "override" or \
                   call_kwargs.args[-1] == "override"

    @pytest.mark.asyncio
    async def test_context_manager_closes(self):
        from obase.mq import MQPublisher

        mock_conn = AsyncMock()
        mock_chan = AsyncMock()
        mock_chan.default_exchange = AsyncMock()
        mock_conn.channel = AsyncMock(return_value=mock_chan)

        with patch("aio_pika.connect_robust", return_value=mock_conn):
            async with MQPublisher("amqp://localhost/"):
                pass
            mock_conn.close.assert_called_once()


class TestMQConsumer:
    @pytest.mark.asyncio
    async def test_connect_failure_raises(self):
        from obase.mq import MQConnectionError, MQConsumer

        with patch("aio_pika.connect_robust", side_effect=OSError("refused")):
            con = MQConsumer("amqp://bad/", queue="q")
            with pytest.raises(MQConnectionError):
                await con.connect()

    @pytest.mark.asyncio
    async def test_consume_without_connect_raises(self):
        from obase.mq import MQConnectionError, MQConsumer

        con = MQConsumer("amqp://localhost/", queue="q")
        with pytest.raises(MQConnectionError):
            await con.consume(lambda _: None, timeout=0.01)

    @pytest.mark.asyncio
    async def test_ack_on_success(self):
        """Handler success → message.ack() called."""
        from obase.mq import MQConsumer

        mock_conn = AsyncMock()
        mock_chan = AsyncMock()
        mock_queue = AsyncMock()
        mock_chan.declare_queue = AsyncMock(return_value=mock_queue)
        mock_conn.channel = AsyncMock(return_value=mock_chan)

        received: list[bytes] = []
        captured_cb: list = []

        async def _fake_consume(cb):
            captured_cb.append(cb)

        mock_queue.consume = _fake_consume

        with patch("aio_pika.connect_robust", return_value=mock_conn):
            con = MQConsumer("amqp://localhost/", queue="q")
            await con.connect()

            async def handler(body: bytes) -> None:
                received.append(body)

            # start consume in background
            task = asyncio.create_task(con.consume(handler, timeout=0.05))

            await asyncio.sleep(0.01)
            assert captured_cb, "consume callback not registered"

            # Simulate a message
            msg = AsyncMock()
            msg.body = b"hello"
            msg.__aenter__ = AsyncMock(return_value=msg)
            msg.__aexit__ = AsyncMock(return_value=False)
            await captured_cb[0](msg)

            await task
            assert b"hello" in received
            msg.ack.assert_called_once()

    @pytest.mark.asyncio
    async def test_nack_on_handler_failure(self):
        """Handler raises → message.nack() called, not ack()."""
        from obase.mq import MQConsumer

        mock_conn = AsyncMock()
        mock_chan = AsyncMock()
        mock_queue = AsyncMock()
        mock_chan.declare_queue = AsyncMock(return_value=mock_queue)
        mock_conn.channel = AsyncMock(return_value=mock_chan)

        captured_cb: list = []

        async def _fake_consume(cb):
            captured_cb.append(cb)

        mock_queue.consume = _fake_consume

        with patch("aio_pika.connect_robust", return_value=mock_conn):
            con = MQConsumer("amqp://localhost/", queue="q")
            await con.connect()

            async def bad_handler(body: bytes) -> None:
                raise RuntimeError("processing failed")

            task = asyncio.create_task(con.consume(bad_handler, timeout=0.05))
            await asyncio.sleep(0.01)

            msg = AsyncMock()
            msg.body = b"bad"
            msg.__aenter__ = AsyncMock(return_value=msg)
            msg.__aexit__ = AsyncMock(return_value=False)
            await captured_cb[0](msg)

            await task
            msg.ack.assert_not_called()
            msg.nack.assert_called_once()


# ─────────────────────────── hmmlearn_runtime ────────────────────────────


class TestHmmlearnRuntime:
    def test_fit_returns_expected_keys(self):
        from obase.hmmlearn_runtime import HmmlearnRuntime

        obs = [0.1, 0.5, 0.9, 0.2, 0.8, 0.3, 0.7]
        result = HmmlearnRuntime.fit(obs, n_states=2)
        for key in ("n_states", "transmat", "means", "covars", "startprob", "_model"):
            assert key in result

    def test_fit_n_states(self):
        from obase.hmmlearn_runtime import HmmlearnRuntime

        obs = list(range(20))
        result = HmmlearnRuntime.fit(obs, n_states=3)
        assert result["n_states"] == 3
        assert len(result["transmat"]) == 3

    def test_predict_returns_list_of_ints(self):
        from obase.hmmlearn_runtime import HmmlearnRuntime

        obs = [0.1, 0.5, 0.9, 0.2, 0.8]
        model = HmmlearnRuntime.fit(obs, n_states=2)
        states = HmmlearnRuntime.predict(obs, model=model)
        assert isinstance(states, list)
        assert all(isinstance(s, int) for s in states)

    def test_predict_length_matches_observations(self):
        from obase.hmmlearn_runtime import HmmlearnRuntime

        obs = [float(i) for i in range(30)]
        model = HmmlearnRuntime.fit(obs, n_states=2)
        states = HmmlearnRuntime.predict(obs, model=model)
        assert len(states) == len(obs)

    def test_predict_states_in_range(self):
        from obase.hmmlearn_runtime import HmmlearnRuntime

        obs = [0.0, 1.0, 0.0, 1.0, 0.5] * 4
        model = HmmlearnRuntime.fit(obs, n_states=2)
        states = HmmlearnRuntime.predict(obs, model=model)
        assert all(0 <= s < 2 for s in states)

    def test_predict_invalid_model_raises_value_error(self):
        from obase.hmmlearn_runtime import HmmlearnRuntime

        with pytest.raises(ValueError, match="_model"):
            HmmlearnRuntime.predict([1.0, 2.0], model={"n_states": 2})

    def test_missing_hmmlearn_fit_raises_import_error(self):
        import sys
        from unittest.mock import patch as _patch

        # Temporarily hide hmmlearn
        with _patch.dict(sys.modules, {"hmmlearn": None, "hmmlearn.hmm": None}):
            from importlib import reload

            import obase.hmmlearn_runtime as _m
            reload(_m)
            with pytest.raises(ImportError, match="pip install"):
                _m.HmmlearnRuntime.fit([1.0, 2.0], n_states=2)
            reload(_m)  # restore

    def test_1d_observations_auto_reshape(self):
        from obase.hmmlearn_runtime import HmmlearnRuntime

        obs = [0.1, 0.4, 0.9, 0.2, 0.7, 0.3, 0.8]
        model = HmmlearnRuntime.fit(obs, n_states=2)
        states = HmmlearnRuntime.predict(obs, model=model)
        assert len(states) == len(obs)
