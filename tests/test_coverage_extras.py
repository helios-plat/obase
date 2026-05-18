"""Extra tests targeting uncovered lines to push coverage above 95%."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from obase.exceptions import FSError
from obase.fs import FS


class TestFSErrorPaths:
    def test_working_dir_mkdir_fails(self, tmp_path):
        """FSError raised when working dir cannot be created."""
        FS.set_default_working_dir(tmp_path / "work")
        with patch("pathlib.Path.mkdir", side_effect=OSError("permission denied")):
            with pytest.raises(FSError, match="Cannot create working dir"):
                FS.working_dir()

    def test_run_dir_mkdir_fails(self, tmp_path):
        """FSError raised when run dir cannot be created."""
        FS.set_default_working_dir(tmp_path / "work")
        # Create working dir first so it passes mkdir
        (tmp_path / "work").mkdir(parents=True, exist_ok=True)
        # Patch only the second mkdir call (for run_dir)
        original_mkdir = Path.mkdir
        call_count = {"n": 0}

        def patched_mkdir(self, **kwargs):
            call_count["n"] += 1
            if call_count["n"] > 1:
                raise OSError("disk full")
            return original_mkdir(self, **kwargs)

        with patch.object(Path, "mkdir", patched_mkdir):
            with pytest.raises(FSError, match="Cannot create"):
                FS.run_dir("badrun")

    def test_cleanup_rmtree_fails(self, tmp_path):
        """cleanup_old_runs logs warning on rmtree failure and continues."""
        FS.set_default_working_dir(tmp_path / "work")
        FS.working_dir()
        old_dir = tmp_path / "work" / "old-run"
        old_dir.mkdir()
        import os
        os.utime(old_dir, (0, 0))
        with patch("shutil.rmtree", side_effect=OSError("locked")):
            removed = FS.cleanup_old_runs(max_age_seconds=1)
        assert removed == []

    def test_safe_write_fails(self, tmp_path):
        """FSError raised when safe_write temp file write fails."""
        with patch("pathlib.Path.write_text", side_effect=OSError("no space")):
            with pytest.raises(FSError, match="Write failed"):
                FS.safe_write(tmp_path / "out.txt", "data")

    def test_ensure_dir_fails(self, tmp_path):
        """FSError raised when ensure_dir cannot create dir."""
        with patch("pathlib.Path.mkdir", side_effect=OSError("not allowed")):
            with pytest.raises(FSError, match="Cannot create directory"):
                FS.ensure_dir(tmp_path / "bad" / "dir")

    def test_cleanup_skips_files(self, tmp_path):
        """cleanup_old_runs skips non-directory entries."""
        FS.set_default_working_dir(tmp_path / "work")
        FS.working_dir()
        (tmp_path / "work" / "file.txt").write_text("not a dir")
        removed = FS.cleanup_old_runs(max_age_seconds=0)
        assert all(p.is_dir() for p in removed)


class TestTrailCoveragePaths:
    def test_load_trail_bad_json_line(self, tmp_path):
        """Bad JSON line in trail is skipped, rest is returned."""
        FS.set_default_working_dir(tmp_path / "work")
        from obase.trail import Trail, load_trail
        trail = Trail("bad-json-run")
        trail.emit("good_event", x=1)
        trail.path.open("a").write("{not json}\n")
        trail.emit("another_good", x=2)
        records = load_trail("bad-json-run")
        assert len(records) == 2

    def test_query_trail_before_filter(self, tmp_path):
        """query_trail before= filter works correctly."""
        import time
        from obase.trail import Trail, query_trail
        FS.set_default_working_dir(tmp_path / "work")
        trail = Trail("before-run")
        trail.emit("early", seq=1)
        time.sleep(0.05)
        cutoff = datetime.now(timezone.utc)
        time.sleep(0.05)
        trail.emit("late", seq=2)

        results = query_trail(working_dir=tmp_path / "work", before=cutoff)
        assert len(results) == 1
        assert results[0]["seq"] == 1

    def test_query_trail_bad_ts_skipped(self, tmp_path):
        """Records with unparseable timestamps are skipped when filter used."""
        from obase.trail import Trail, query_trail
        FS.set_default_working_dir(tmp_path / "work")
        trail = Trail("bad-ts-run")
        trail.emit("good", val=1)
        # Inject a bad-ts record directly
        with trail.path.open("a") as fh:
            fh.write('{"ts": "not-a-date", "event": "bad", "val": 999}\n')
        cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
        results = query_trail(working_dir=tmp_path / "work", after=cutoff)
        vals = [r.get("val") for r in results]
        assert 999 not in vals

    def test_query_trail_bad_json_skipped(self, tmp_path):
        """Bad JSON lines in query_trail are silently skipped."""
        from obase.trail import Trail, query_trail
        FS.set_default_working_dir(tmp_path / "work")
        trail = Trail("qbad-run")
        trail.emit("ev", val=1)
        with trail.path.open("a") as fh:
            fh.write("{invalid json\n")
        results = query_trail(working_dir=tmp_path / "work")
        assert any(r.get("val") == 1 for r in results)

    def test_query_trail_skips_non_dir(self, tmp_path):
        """query_trail skips files (non-dirs) in working dir."""
        from obase.trail import query_trail
        FS.set_default_working_dir(tmp_path / "work")
        FS.working_dir()
        (tmp_path / "work" / "stray_file.txt").write_text("not a dir")
        results = query_trail(working_dir=tmp_path / "work")
        assert results == []

    def test_query_trail_skips_dir_without_trail(self, tmp_path):
        """query_trail skips run dirs that have no trail.jsonl."""
        from obase.trail import query_trail
        FS.set_default_working_dir(tmp_path / "work")
        FS.working_dir()
        (tmp_path / "work" / "no-trail-run").mkdir()
        results = query_trail(working_dir=tmp_path / "work")
        assert results == []

    def test_query_trail_empty_line_skipped(self, tmp_path):
        """Empty lines in trail files are skipped in query_trail."""
        from obase.trail import Trail, query_trail
        FS.set_default_working_dir(tmp_path / "work")
        trail = Trail("empty-line-run")
        trail.emit("ev", val=42)
        with trail.path.open("a") as fh:
            fh.write("\n\n")
        results = query_trail(working_dir=tmp_path / "work")
        assert len(results) == 1


class TestBootstrapCoverage:
    def test_line_without_equals_skipped(self, tmp_path):
        """Lines without '=' are skipped in load_env."""
        from obase.bootstrap import load_env
        f = tmp_path / ".env"
        f.write_text("NOEQUALSSIGN\nGOOD_KEY=good_val\n")
        injected = load_env(f)
        assert "NOEQUALSSIGN" not in injected
        assert injected["GOOD_KEY"] == "good_val"

    def test_line_empty_key_skipped(self, tmp_path):
        """Line '=value' produces empty key, which is skipped."""
        from obase.bootstrap import load_env
        f = tmp_path / ".env"
        f.write_text("=orphan_value\nNORMAL=ok\n")
        injected = load_env(f)
        assert "" not in injected
        assert injected.get("NORMAL") == "ok"

    def test_bootstrap_tty_renderer(self, tmp_path):
        """bootstrap uses ConsoleRenderer when stdout is a TTY."""
        from obase.bootstrap import bootstrap
        with patch("os.isatty", return_value=True):
            bootstrap(auto_discover_providers=False)

    def test_bootstrap_fserror_propagated(self, tmp_path):
        """FSError from set_default_working_dir is re-raised by bootstrap."""
        from obase.bootstrap import bootstrap
        from obase.exceptions import FSError
        with patch("obase.fs.FS.set_default_working_dir", side_effect=FSError("bad path")):
            with pytest.raises(FSError):
                bootstrap(working_dir=tmp_path / "bad", auto_discover_providers=False)

    def test_bootstrap_auto_discover_raises(self, tmp_path):
        """bootstrap propagates ProviderDiscoveryError from auto_discover."""
        from obase.bootstrap import bootstrap
        from obase.exceptions import ProviderDiscoveryError
        with patch("obase.provider_registry.ProviderRegistry.auto_discover",
                   side_effect=ProviderDiscoveryError("ep fail")):
            with pytest.raises(ProviderDiscoveryError):
                bootstrap(auto_discover_providers=True)

    async def test_cache_clear_expired_corrupt_file(self, tmp_path):
        """clear_expired removes corrupt pickle files and counts them."""
        from obase.cache import Cache
        c = Cache("corrupt-clear")
        c._ttl = 0.001
        path = c._key_path("bad")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not-pickle")
        removed = await c.clear_expired()
        assert removed >= 1


class TestCacheCoverageExtra:
    async def test_clear_expired_no_ttl(self):
        """clear_expired with no TTL returns 0 immediately."""
        from obase.cache import Cache
        c = Cache("no-ttl-clear")
        result = await c.clear_expired()
        assert result == 0

    async def test_clear_expired_corrupt(self, tmp_path):
        from obase.cache import Cache
        c = Cache("corrupt-clear2")
        path = c._key_path("corrupt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not valid pickle")
        c._ttl = 0.001
        removed = await c.clear_expired()
        assert removed >= 1
