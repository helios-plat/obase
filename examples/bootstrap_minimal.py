"""Minimal bootstrap usage — no .env, default working dir."""

from __future__ import annotations

from obase.bootstrap import bootstrap
from obase.fs import FS

bootstrap(auto_discover_providers=False)
print("obase initialized!")

print(f"Working dir: {FS.working_dir()}")
