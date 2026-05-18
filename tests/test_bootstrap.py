from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from obase.bootstrap import load_env
from obase.exceptions import EnvLoadError


@pytest.fixture(autouse=True)
def cleanup_env():
    """Remove any env vars set during tests."""
    before = dict(os.environ)
    yield
    for key in list(os.environ.keys()):
        if key not in before:
            del os.environ[key]
        elif os.environ[key] != before[key]:
            os.environ[key] = before[key]


class TestLoadEnv:
    def test_basic_load(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("MY_KEY=my_value\n")
        injected = load_env(f)
        assert injected["MY_KEY"] == "my_value"
        assert os.environ["MY_KEY"] == "my_value"

    def test_load_env_strips_inline_comments(self, tmp_path):
        """KEY=VALUE  # comment → os.environ[KEY] == VALUE"""
        f = tmp_path / ".env"
        f.write_text("COMMENTED=hello_world  # this is a comment\n")
        load_env(f)
        assert os.environ["COMMENTED"] == "hello_world"

    def test_load_env_strips_tab_comment(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("TABBED=value\t# tab comment\n")
        load_env(f)
        assert os.environ["TABBED"] == "value"

    def test_load_env_empty_value_not_injected(self, tmp_path):
        """KEY= → not injected into os.environ."""
        f = tmp_path / ".env"
        f.write_text("EMPTY_KEY=\n")
        injected = load_env(f)
        assert "EMPTY_KEY" not in injected
        assert "EMPTY_KEY" not in os.environ

    def test_load_env_url_validation_strict(self, tmp_path):
        """*_URL with invalid URL, strict=True → EnvLoadError."""
        f = tmp_path / ".env"
        f.write_text("API_URL=not-a-url\n")
        with pytest.raises(EnvLoadError, match="API_URL"):
            load_env(f, strict=True)

    def test_load_env_url_validation_lenient(self, tmp_path):
        """*_URL with invalid URL, strict=False → injected but warning."""
        f = tmp_path / ".env"
        f.write_text("API_URL=not-a-url\n")
        injected = load_env(f, strict=False)
        assert "API_URL" in injected
        assert os.environ["API_URL"] == "not-a-url"

    def test_load_env_valid_url(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("API_BASE_URL=https://api.example.com\n")
        injected = load_env(f)
        assert injected["API_BASE_URL"] == "https://api.example.com"

    def test_load_env_skips_comments(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("# comment line\nREAL_KEY=real_val\n")
        injected = load_env(f)
        assert "# comment line" not in injected
        assert injected["REAL_KEY"] == "real_val"

    def test_bootstrap_env_not_found_strict(self, tmp_path):
        """env_path not found, strict=True → EnvLoadError."""
        missing = tmp_path / "nonexistent.env"
        with pytest.raises(EnvLoadError, match="not found"):
            load_env(missing, strict=True)

    def test_bootstrap_env_not_found_lenient(self, tmp_path):
        """env_path not found, strict=False → returns empty dict."""
        missing = tmp_path / "nonexistent.env"
        injected = load_env(missing, strict=False)
        assert injected == {}

    def test_quoted_values(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text('QUOTED="hello world"\nSINGLE=\'single quoted\'\n')
        injected = load_env(f)
        assert injected["QUOTED"] == "hello world"
        assert injected["SINGLE"] == "single quoted"

    def test_multiple_keys(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("A=1\nB=2\nC=3\n")
        injected = load_env(f)
        assert len(injected) == 3

    def test_base_url_validation(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("OPENAI_BASE_URL=not-valid\n")
        with pytest.raises(EnvLoadError):
            load_env(f, strict=True)


class TestBootstrapFn:
    def test_bootstrap_no_args(self):
        from obase.bootstrap import bootstrap
        bootstrap(auto_discover_providers=False)

    def test_bootstrap_with_working_dir(self, tmp_path):
        from obase.bootstrap import bootstrap
        from obase.fs import FS
        bootstrap(working_dir=tmp_path / "work", auto_discover_providers=False)
        assert FS.working_dir() == tmp_path / "work"

    def test_bootstrap_with_env(self, tmp_path):
        from obase.bootstrap import bootstrap
        f = tmp_path / ".env"
        f.write_text("BOOT_TEST_VAR=ok\n")
        bootstrap(env_path=f, auto_discover_providers=False)
        assert os.environ.get("BOOT_TEST_VAR") == "ok"
