from __future__ import annotations

from pathlib import Path

import pytest

from obase.fs import FS
from obase.provider_registry import ProviderRegistry
from obase.rate_limit import RateLimitRegistry
from obase.tool_registry import ToolRegistry


@pytest.fixture(autouse=True)
def isolated_working_dir(tmp_path: Path):
    """Each test gets its own working dir to avoid cross-contamination."""
    FS.set_default_working_dir(tmp_path / "obase_work")
    yield tmp_path / "obase_work"
    FS.reset_working_dir()


@pytest.fixture(autouse=True)
def clean_registries():
    """Reset class-level registries between tests."""
    ProviderRegistry.clear()
    RateLimitRegistry.clear()
    ToolRegistry.clear()
    yield
    ProviderRegistry.clear()
    RateLimitRegistry.clear()
    ToolRegistry.clear()
