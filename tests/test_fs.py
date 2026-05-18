from __future__ import annotations

from pathlib import Path

import pytest

from obase.exceptions import FSError
from obase.fs import FS


class TestWorkingDir:
    def test_default_creates_dir(self, tmp_path):
        FS.set_default_working_dir(tmp_path / "work")
        d = FS.working_dir()
        assert d.exists()
        assert d.is_dir()

    def test_set_and_reset(self, tmp_path):
        FS.set_default_working_dir(tmp_path / "custom")
        assert FS.working_dir() == tmp_path / "custom"
        FS.reset_working_dir()
        # After reset it should default to ~/.obase/work
        d = FS.working_dir()
        assert d.exists()
        FS.set_default_working_dir(tmp_path / "safe")  # re-isolate

    def test_run_dir_creates_subdir(self, tmp_path):
        FS.set_default_working_dir(tmp_path / "work")
        d = FS.run_dir("my-run")
        assert d.exists()
        assert d.name == "my-run"


class TestHashFile:
    def test_hash_file_sha256(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello")
        digest = FS.hash_file(f)
        assert len(digest) == 64

    def test_hash_file_missing(self, tmp_path):
        with pytest.raises(FSError):
            FS.hash_file(tmp_path / "nonexistent.bin")

    def test_hash_file_md5(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("hello")
        digest = FS.hash_file(f, algorithm="md5")
        assert len(digest) == 32


class TestCleanupOldRuns:
    def test_cleanup_removes_old(self, tmp_path):
        FS.set_default_working_dir(tmp_path / "work")
        FS.working_dir()
        old_dir = tmp_path / "work" / "old-run"
        old_dir.mkdir(parents=True)
        import os
        os.utime(old_dir, (0, 0))
        removed = FS.cleanup_old_runs(max_age_seconds=1)
        assert any(p.name == "old-run" for p in removed)

    def test_cleanup_keeps_fresh(self, tmp_path):
        FS.set_default_working_dir(tmp_path / "work")
        FS.working_dir()
        fresh = tmp_path / "work" / "fresh-run"
        fresh.mkdir()
        removed = FS.cleanup_old_runs(max_age_seconds=9999)
        assert not any(p.name == "fresh-run" for p in removed)


class TestWSLPaths:
    def test_to_wsl_path(self, tmp_path):
        result = FS.to_wsl_path("C:\\Users\\foo\\bar")
        assert str(result) == "/mnt/c/Users/foo/bar"

    def test_to_wsl_path_invalid(self):
        with pytest.raises(FSError):
            FS.to_wsl_path("/already/unix")

    def test_from_wsl_path(self):
        result = FS.from_wsl_path(Path("/mnt/d/some/path"))
        assert result == "D:\\some\\path"

    def test_from_wsl_path_invalid(self):
        with pytest.raises(FSError):
            FS.from_wsl_path("/not/mnt/path")


class TestSafeWrite:
    def test_write_text(self, tmp_path):
        f = tmp_path / "out.txt"
        FS.safe_write(f, "hello world")
        assert f.read_text() == "hello world"

    def test_write_bytes(self, tmp_path):
        f = tmp_path / "out.bin"
        FS.safe_write(f, b"\x00\x01\x02")
        assert f.read_bytes() == b"\x00\x01\x02"

    def test_ensure_dir(self, tmp_path):
        d = tmp_path / "a" / "b" / "c"
        FS.ensure_dir(d)
        assert d.is_dir()
