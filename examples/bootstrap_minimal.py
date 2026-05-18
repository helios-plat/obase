"""Minimal bootstrap usage — no .env, default working dir."""
from __future__ import annotations

from obase.bootstrap import bootstrap

bootstrap(auto_discover_providers=False)
print("obase initialized!")

from obase.fs import FS
print(f"Working dir: {FS.working_dir()}")
