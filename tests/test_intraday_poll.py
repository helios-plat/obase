"""Tests for obase.scheduler.IntradayPollScheduler (D1)."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from obase.scheduler import IntradayPollScheduler


class TestIntradayPollScheduler:
    def test_register_multiple_windows(self) -> None:
        s = IntradayPollScheduler()
        s.register_window(name="morning", trigger_time=time(9, 30), handler=lambda: "ok")
        s.register_window(name="close", trigger_time=time(15, 0), handler=lambda: "ok")
        assert len(s.status()) == 2

    def test_start_stop_idempotent(self) -> None:
        s = IntradayPollScheduler()
        s.register_window(name="x", trigger_time=time(10, 0), handler=lambda: None)
        s.start()
        s.start()  # idempotent
        assert s.is_running
        s.stop()
        s.stop()  # idempotent
        assert not s.is_running

    def test_handler_exception_isolated(self) -> None:
        s = IntradayPollScheduler()
        s.register_window(name="good", trigger_time=time(10, 0), handler=lambda: "ok")
        s.register_window(name="bad", trigger_time=time(10, 0), handler=lambda: 1/0)
        s.start()
        now = datetime(2026, 5, 25, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        results = s.tick(now=now)
        statuses = {r["name"]: r["status"] for r in results}
        assert statuses["good"] == "success"
        assert statuses["bad"] == "error"
        # Good handler still succeeded despite bad handler failing
        assert s.status()["good"] == "success"

    def test_timezone_conversion(self) -> None:
        s = IntradayPollScheduler(timezone="UTC")
        s.register_window(name="utc_noon", trigger_time=time(12, 0), handler=lambda: "noon")
        s.start()
        now = datetime(2026, 5, 25, 12, 0, tzinfo=ZoneInfo("UTC"))
        results = s.tick(now=now)
        assert len(results) == 1

    def test_status_reflects_state(self) -> None:
        s = IntradayPollScheduler()
        s.register_window(name="w1", trigger_time=time(8, 0), handler=lambda: None)
        assert s.status()["w1"] == "registered"
        s.start()
        assert s.status()["w1"] == "active"
        s.stop()
        assert s.status()["w1"] == "stopped"

    def test_edge_times_00_00_23_59(self) -> None:
        s = IntradayPollScheduler()
        s.register_window(name="midnight", trigger_time=time(0, 0), handler=lambda: "mid")
        s.register_window(name="end", trigger_time=time(23, 59), handler=lambda: "end")
        s.start()
        now_mid = datetime(2026, 5, 25, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        results = s.tick(now=now_mid)
        assert any(r["name"] == "midnight" for r in results)
