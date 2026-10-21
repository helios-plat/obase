"""Tests for obase.checkpoint_store, browser_vision_runner, ssrf_safe_network."""

from __future__ import annotations

from pathlib import Path

from obase.browser_vision_runner import (
    BrowserVisionRunner,
)
from obase.checkpoint_store import CheckpointStore
from obase.ssrf_safe_network import SSRFSafeNetwork

# ============================================================================
# CheckpointStore
# ============================================================================


class TestCheckpointStore:
    """D0 迁移: 断言对象 = Veya-lineage 唯一实现 (save/load/keys/reset, SQLite WAL)。"""

    def test_save_and_load(self, tmp_path: Path):
        store = CheckpointStore(base_dir=tmp_path)
        assert store.save("sess-1", {"step": 5, "data": "hello"}) == "sess-1"
        assert store.load("sess-1") == {"step": 5, "data": "hello"}

    def test_load_nonexistent_returns_none(self, tmp_path: Path):
        assert CheckpointStore(base_dir=tmp_path).load("nonexistent") is None

    def test_save_is_durable_in_sqlite(self, tmp_path: Path):
        CheckpointStore(base_dir=tmp_path).save("sess-2", {"a": 1})
        assert (tmp_path / "checkpoints.db").exists()
        # 新实例从同一 base_dir 恢复 (崩溃重启 hydrate 语义)
        assert CheckpointStore(base_dir=tmp_path).load("sess-2") == {"a": 1}

    def test_keys_and_count(self, tmp_path: Path):
        store = CheckpointStore(base_dir=tmp_path)
        store.save("a", {})
        store.save("b", {})
        assert sorted(store.keys()) == ["a", "b"]
        assert store.count() == 2

    def test_reset_removes_checkpoint(self, tmp_path: Path):
        store = CheckpointStore(base_dir=tmp_path)
        store.save("to-drop", {"x": 1})
        store.reset("to-drop")
        assert store.load("to-drop") is None
        assert store.keys() == []

    def test_overwrite_checkpoint(self, tmp_path: Path):
        store = CheckpointStore(base_dir=tmp_path)
        store.save("sess", {"version": 1})
        store.save("sess", {"version": 2})
        assert store.load("sess")["version"] == 2
        assert store.count() == 1

    def test_empty_state_data(self, tmp_path: Path):
        store = CheckpointStore(base_dir=tmp_path)
        store.save("empty", {})
        assert store.load("empty") == {}


# ============================================================================
# BrowserVisionRunner
# ============================================================================


class TestBrowserVisionRunner:
    def test_capture_page_returns_page_state(self):
        runner = BrowserVisionRunner(headless=True)
        state = runner.capture_page_with_bounding_boxes("https://example.com")
        assert state.url == "https://example.com"
        assert state.viewport == {"width": 1280, "height": 800}
        assert len(state.elements) > 0

    def test_elements_have_required_fields(self):
        runner = BrowserVisionRunner()
        state = runner.capture_page_with_bounding_boxes("https://test.com")
        for elem in state.elements:
            assert elem.element_id
            assert elem.element_type in ("input", "button", "link", "select", "image", "form")
            assert len(elem.box) == 4

    def test_element_at_point_finds_element(self):
        runner = BrowserVisionRunner()
        state = runner.capture_page_with_bounding_boxes("https://test.com")
        # search-input is at [100, 50, 400, 40]
        elem = runner.element_at_point(state, 200, 70)
        assert elem is not None
        assert elem.element_id == "search-input"

    def test_element_at_point_returns_none_outside(self):
        runner = BrowserVisionRunner()
        state = runner.capture_page_with_bounding_boxes("https://test.com")
        elem = runner.element_at_point(state, 0, 0)
        assert elem is None

    def test_find_element_by_id(self):
        runner = BrowserVisionRunner()
        state = runner.capture_page_with_bounding_boxes("https://test.com")
        elem = runner.find_element_by_id(state, "submit-btn")
        assert elem is not None
        assert elem.element_type == "button"

    def test_find_element_by_id_nonexistent(self):
        runner = BrowserVisionRunner()
        state = runner.capture_page_with_bounding_boxes("https://test.com")
        elem = runner.find_element_by_id(state, "nonexistent")
        assert elem is None

    def test_health(self):
        runner = BrowserVisionRunner()
        h = runner.health()
        assert h["status"] == "healthy"
        assert h["headless"] is True


# ============================================================================
# SSRFSafeNetwork
# ============================================================================


class TestSSRFSafeNetwork:
    def test_public_url_is_safe(self):
        net = SSRFSafeNetwork()
        assert net.is_safe_url("https://example.com") is True
        assert net.is_safe_url("https://api.github.com/zen") is True
        assert net.is_safe_url("http://openai.com") is True

    def test_localhost_is_blocked(self):
        net = SSRFSafeNetwork()
        assert net.is_safe_url("http://localhost:8080") is False
        assert net.is_safe_url("http://127.0.0.1/admin") is False

    def test_private_ips_blocked(self):
        net = SSRFSafeNetwork()
        assert net.is_safe_url("http://10.0.0.1/api") is False
        assert net.is_safe_url("http://192.168.1.1/") is False
        assert net.is_safe_url("http://172.16.0.1/") is False

    def test_cloud_metadata_blocked(self):
        net = SSRFSafeNetwork()
        assert net.is_safe_url("http://metadata.google.internal/") is False
        assert net.is_safe_url("http://169.254.169.254/latest/meta-data/") is False

    def test_non_http_schemes_blocked(self):
        net = SSRFSafeNetwork()
        assert net.is_safe_url("ftp://example.com") is False
        assert net.is_safe_url("file:///etc/passwd") is False
        assert net.is_safe_url("gopher://evil.com") is False

    def test_empty_hostname_blocked(self):
        net = SSRFSafeNetwork()
        assert net.is_safe_url("") is False
        assert net.is_safe_url("http://") is False

    def test_link_local_blocked(self):
        net = SSRFSafeNetwork()
        assert net.is_safe_url("http://169.254.1.1/") is False

    def test_safe_fetch_public_url(self):
        net = SSRFSafeNetwork(timeout=5)
        # No actual network call; blocked URLs should be caught first
        result = net.safe_fetch("http://127.0.0.1/secret")
        assert result["status"] == "blocked"

    def test_safe_fetch_invalid_url(self):
        net = SSRFSafeNetwork()
        result = net.safe_fetch("not-a-url")
        assert result["status"] in ("failed", "blocked")

    def test_health(self):
        net = SSRFSafeNetwork()
        h = net.health()
        assert h["status"] == "healthy"
        assert "timeout" in h
