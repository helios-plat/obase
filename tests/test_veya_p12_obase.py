"""Tests for Veya P1/P2 顶级 Agent 功能复现 — obase 层 (9 个).

Covers: zeromq_bus, durable_lease_queue, zero_egress_sandbox, livekit_webrtc,
vad_pipeline, signed_token_session, media_scraper, debounced_memory_queue,
harness_bridge.
"""

from __future__ import annotations

import asyncio
import pathlib
import struct

import pytest

# ---------------------------------------------------------------------------
# durable_lease_queue
# ---------------------------------------------------------------------------


class TestDurableLeaseQueue:
    def test_enqueue_lease_complete(self, tmp_path: pathlib.Path):
        from obase import DurableLeaseQueue

        q = DurableLeaseQueue(tmp_path / "q.db")
        iid = q.enqueue({"task": "t1"}, priority=2)
        q.enqueue({"task": "t2"}, priority=1)
        lease = q.lease("w1", timeout_s=5.0)
        assert lease["item_id"] == iid  # priority 2 先出
        assert lease["payload"] == {"task": "t1"}
        assert q.renew(lease["lease_id"], timeout_s=5.0)
        assert q.complete(lease["lease_id"]) is True
        assert q.stats()["done"] == 1

    def test_expired_lease_released(self, tmp_path: pathlib.Path):
        from obase import DurableLeaseQueue

        q = DurableLeaseQueue(tmp_path / "q2.db")
        q.enqueue({"task": "t"})
        l1 = q.lease("w1", timeout_s=-1)
        assert l1 is not None
        l2 = q.lease("w2", timeout_s=5.0)  # 过期租约可被重新领取
        assert l2["item_id"] == l1["item_id"]
        assert l2["attempts"] == 2

    def test_sweep_expired(self, tmp_path: pathlib.Path):
        from obase import DurableLeaseQueue

        q = DurableLeaseQueue(tmp_path / "q3.db")
        q.enqueue({"task": "a"})
        q.enqueue({"task": "b"})
        q.lease("w1", timeout_s=-1)
        q.lease("w1", timeout_s=-1)  # 同一任务被重新领取（过期可再租）
        assert q.sweep_expired(max_attempts=2) == 1
        assert q.stats() == {"failed": 1, "pending": 1}  # 超次数的置 failed，其余归还

    def test_release_and_fail(self, tmp_path: pathlib.Path):
        from obase import DurableLeaseQueue

        q = DurableLeaseQueue(tmp_path / "q4.db")
        q.enqueue({"task": "a"})
        lease = q.lease("w1", timeout_s=5.0)
        assert q.release(lease["lease_id"]) is True
        assert q.pending_count() == 1
        lease2 = q.lease("w1", timeout_s=5.0)
        assert q.fail(lease2["lease_id"]) is True
        assert q.stats()["failed"] == 1

    def test_unknown_lease_idempotent(self, tmp_path: pathlib.Path):
        from obase import DurableLeaseQueue

        q = DurableLeaseQueue(tmp_path / "q5.db")
        assert q.complete("nope") is False
        assert q.release("nope") is False
        assert q.get("nope") is None

    def test_persistence_across_instances(self, tmp_path: pathlib.Path):
        from obase import DurableLeaseQueue

        db = tmp_path / "q6.db"
        q1 = DurableLeaseQueue(db)
        q1.enqueue({"task": "persist"})
        q2 = DurableLeaseQueue(db)  # 新实例读同一库
        assert q2.pending_count() == 1


# ---------------------------------------------------------------------------
# zero_egress_sandbox
# ---------------------------------------------------------------------------


class TestZeroEgressSandbox:
    async def test_ok_execution(self):
        from obase import ZeroEgressSandbox

        sb = ZeroEgressSandbox(use_network_namespace=False)
        r = await sb.run("echo hi")
        assert r["status"] == "ok" and r["stdout"].strip() == "hi"

    async def test_network_command_blocked(self):
        from obase import ZeroEgressSandbox

        sb = ZeroEgressSandbox(use_network_namespace=False)
        for cmd in ("curl http://x", "wget http://x", "nc -l 8080", "git fetch origin"):
            r = await sb.run(cmd)
            assert r["status"] == "blocked" and "denied" in r["reason"], cmd

    async def test_env_sanitized(self):
        import os

        from obase import ZeroEgressSandbox

        os.environ["HTTP_PROXY"] = "http://proxy:1"
        os.environ["OPENAI_API_KEY"] = "sk-secret"
        sb = ZeroEgressSandbox()
        env = sb.sanitized_env()
        assert "HTTP_PROXY" not in env and "OPENAI_API_KEY" not in env

    async def test_timeout(self):
        from obase import ZeroEgressSandbox

        sb = ZeroEgressSandbox(use_network_namespace=False)
        r = await sb.run("sleep 5", timeout=0.2)
        assert r["status"] == "timeout"

    async def test_error_exit_code(self):
        from obase import ZeroEgressSandbox

        sb = ZeroEgressSandbox(use_network_namespace=False)
        r = await sb.run("exit 3")
        assert r["status"] == "error" and r["exit_code"] == 3


# ---------------------------------------------------------------------------
# signed_token_session
# ---------------------------------------------------------------------------


class TestSignedTokenSession:
    def test_create_verify(self):
        from obase import SignedTokenSession

        m = SignedTokenSession("secret", issuer="veya")
        token = m.create("user_1", ttl_s=60, claims={"role": "admin"})
        payload = m.verify(token)
        assert payload["sub"] == "user_1"
        assert payload["role"] == "admin"
        assert payload["iss"] == "veya"

    def test_tamper_rejected(self):
        from obase import SignedTokenSession, TokenError

        m = SignedTokenSession("secret")
        token = m.create("u", ttl_s=60)
        with pytest.raises(TokenError):
            m.verify(token[:-2] + "xx")

    def test_expired(self):
        from obase import SignedTokenSession, TokenExpiredError

        m = SignedTokenSession("secret", leeway_s=0.0)
        token = m.create("u", ttl_s=0.01)
        import time

        time.sleep(0.05)
        with pytest.raises(TokenExpiredError):
            m.verify(token)

    def test_revoke(self):
        from obase import SignedTokenSession, TokenRevokedError

        m = SignedTokenSession("secret")
        token = m.create("u", ttl_s=60)
        assert m.revoke(token) is True
        with pytest.raises(TokenRevokedError):
            m.verify(token)
        assert m.revoke(token) is True  # 幂等

    def test_refresh(self):
        from obase import SignedTokenSession

        m = SignedTokenSession("secret")
        token = m.create("u", ttl_s=60, claims={"role": "reader"})
        new_token = m.refresh(token)
        payload = m.verify(new_token)
        assert payload["sub"] == "u" and payload["role"] == "reader"


# ---------------------------------------------------------------------------
# vad_pipeline
# ---------------------------------------------------------------------------


class TestVADPipeline:
    def _noise(self) -> bytes:
        return struct.pack("<160h", *([30000] * 160))

    def test_energy_vad(self):
        from obase import VADPipeline

        vad = VADPipeline(mode="energy")
        assert not vad.is_speech(b"\x00" * 320, sample_rate=16000)
        assert vad.is_speech(self._noise(), sample_rate=16000)

    def test_speech_segments(self):
        from obase import speech_segments

        silence = b"\x00" * 320
        noise = self._noise()
        segs = speech_segments(
            [silence] * 3 + [noise] * 10 + [silence] * 3,
            sample_rate=16000, min_segment_frames=5,
        )
        assert len(segs) == 1 and segs[0]["frames"] == 10

    def test_no_speech(self):
        from obase import speech_segments

        silence = b"\x00" * 320
        assert speech_segments([silence] * 10, sample_rate=16000) == []

    def test_webrtc_missing_dep(self):
        import importlib.util

        if importlib.util.find_spec("webrtcvad") is not None:
            pytest.skip("webrtcvad installed")
        from obase import VADPipeline

        with pytest.raises(Exception, match="webrtcvad"):
            VADPipeline(mode="webrtc").is_speech(self._noise(), sample_rate=16000)


# ---------------------------------------------------------------------------
# media_scraper
# ---------------------------------------------------------------------------


class TestMediaScraper:
    def test_extract_from_html(self):
        from obase import extract_from_html

        html = (
            '<img src="/a.jpg">'
            '<video src="https://x.com/v.mp4"></video>'
            '<audio src="s.mp3"></audio>'
            '<source src="clip.webm" type="video/webm">'
        )
        items = extract_from_html(html, base_url="https://x.com/page")
        kinds = [i["kind"] for i in items]
        assert kinds == ["image", "video", "audio", "video"]
        assert items[0]["url"] == "https://x.com/page/a.jpg"  # 相对路径按 base 解析
        assert items[3]["mime"] == "video/webm"

    def test_data_uri_skipped(self):
        from obase import extract_from_html

        html = '<img src="data:image/png;base64,AAAA">'
        assert extract_from_html(html) == []

    def test_max_items(self):
        from obase import extract_from_html

        html = "".join(f'<img src="/i{n}.jpg">' for n in range(10))
        assert len(extract_from_html(html, max_items=3)) == 3


# ---------------------------------------------------------------------------
# debounced_memory_queue
# ---------------------------------------------------------------------------


class TestDebouncedMemoryQueue:
    """D0 迁移: 断言对象 = Veya-lineage 唯一实现 (enqueue/load/flush_all, 文件落盘)。"""

    async def test_debounce_merge_and_flush(self, tmp_path):
        from obase import DebouncedMemoryQueue

        q = DebouncedMemoryQueue(base_dir=tmp_path, debounce_s=0.05)
        q.enqueue("k", {"a": 1})
        q.enqueue("k", {"b": 2})
        await asyncio.sleep(0.25)
        assert q.load("k") == {"a": 1, "b": 2}
        assert q.pending_count() == 0

    async def test_flush_all_forces_write(self, tmp_path):
        from obase import DebouncedMemoryQueue

        q = DebouncedMemoryQueue(base_dir=tmp_path, debounce_s=30.0)
        q.enqueue("k", {"x": 9})
        assert await q.flush_all(timeout=2.0) == 1
        assert q.load("k") == {"x": 9}

    async def test_pending_count_tracks_keys(self, tmp_path):
        from obase import DebouncedMemoryQueue

        q = DebouncedMemoryQueue(base_dir=tmp_path, debounce_s=30.0)
        q.enqueue("a", {"v": 1})
        q.enqueue("b", {"v": 2})
        assert q.pending_count() == 2
        await q.flush_all(timeout=2.0)
        assert q.pending_count() == 0

    async def test_missing_key_loads_empty(self, tmp_path):
        from obase import DebouncedMemoryQueue

        q = DebouncedMemoryQueue(base_dir=tmp_path)
        assert q.load("nope") == {}
        assert (await q.pop("a")) is None


# ---------------------------------------------------------------------------
# harness_bridge
# ---------------------------------------------------------------------------


class TestHarnessBridge:
    async def test_emit_and_handlers(self):
        from obase import HarnessBridge

        b = HarnessBridge("h1")
        got: list[dict] = []

        async def handler(payload):
            got.append(payload)

        b.register_handler("ev", handler)
        assert await b.emit("ev", {"x": 1}) == 1
        assert got == [{"x": 1}]
        assert len(b.event_log()) == 1
        assert b.unregister_handler("ev", handler) is True
        assert await b.emit("ev", {}) == 0

    async def test_status_and_commands(self):
        from obase import HarnessBridge

        b = HarnessBridge("h2")
        b.set_status("running", detail="x")
        assert b.status == "running"
        assert b.status_report()["detail"] == {"detail": "x"}
        await b.send_command("pause", {"why": 1})
        cmd = await b.consume_command(timeout=0.5)
        assert cmd["command"] == "pause" and cmd["payload"] == {"why": 1}
        assert await b.consume_command(timeout=0.01) is None

    def test_health(self):
        from obase import HarnessBridge

        b = HarnessBridge("h3")
        assert b.health()["status"] == "healthy"
        assert b.heartbeat()["name"] == "h3"


# ---------------------------------------------------------------------------
# zeromq_bus（memory_mode；pyzmq 非必需）
# ---------------------------------------------------------------------------


class TestZeroMQBus:
    async def test_memory_mode_pubsub(self):
        from obase import ZeroMQBus

        bus = ZeroMQBus(memory_mode=True)
        await bus.start()
        got: list[dict] = []
        await bus.subscribe("ev", lambda p: got.append(p))
        await bus.publish("ev", {"k": 1})
        await bus.close()
        assert got == [{"k": 1}]

    async def test_missing_pyzmq_error(self):
        import importlib.util

        if importlib.util.find_spec("zmq") is not None:
            pytest.skip("pyzmq installed")
        from obase import ZeroMQBus, ZeroMQBusError

        bus = ZeroMQBus()
        with pytest.raises(ZeroMQBusError):
            await bus.start()

    async def test_health(self):
        from obase import ZeroMQBus

        bus = ZeroMQBus(memory_mode=True)
        await bus.start()
        assert bus.health()["status"] == "healthy"
        await bus.close()


# ---------------------------------------------------------------------------
# livekit_webrtc（簿记路径；SDK 非必需）
# ---------------------------------------------------------------------------


class TestLiveKitWebRTC:
    async def test_room_bookkeeping(self):
        from obase import LiveKitWebRTC

        lk = LiveKitWebRTC()
        rid = lk.create_room("demo")
        assert lk.join(rid, participant="u1")["joined"] is True
        assert lk.register_track(rid, track_id="t1") is True
        assert lk.status()["room_count"] == 1
        assert lk.leave(rid, participant="u1") is True
        assert lk.leave(rid, participant="u1") is False

    async def test_connect_requires_sdk(self):
        import importlib.util

        if importlib.util.find_spec("livekit") is not None:
            pytest.skip("livekit installed")
        from obase import LiveKitError, LiveKitWebRTC

        lk = LiveKitWebRTC()
        rid = lk.create_room("r")
        with pytest.raises(LiveKitError):
            await lk.connect(rid, participant="u1")

    async def test_publish_audio(self):
        from obase import LiveKitWebRTC

        lk = LiveKitWebRTC()
        rid = lk.create_room("r2")
        r = await lk.publish_audio(rid, participant="u1", data=b"\x00" * 100)
        assert r["bytes"] == 100 and r["track_id"]
