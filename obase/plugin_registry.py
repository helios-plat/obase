"""obase.plugin_registry — Cindy-style plugin marketplace registry.

Plugins are shareable packages that reshape features, UI, and interactions.
Each plugin has a manifest (name, version, capabilities, dependencies) and
can be installed, listed, configured, and uninstalled.

3O element: ``obase.plugin_registry`` (``PluginRegistry`` class).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class PluginRegistry:
    """Cindy-style plugin marketplace registry.

    Usage::

        reg = PluginRegistry()
        reg.install("cindy-theme-dark", "1.0.0", capabilities=["ui.theme"], source="marketplace")
        plugins = reg.list_installed()
        reg.configure("cindy-theme-dark", {"primaryColor": "#1a1a2e"})
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir else Path.home() / ".veya" / "plugins"
        self._base.mkdir(parents=True, exist_ok=True)
        self._installed_path = self._base / "installed.json"
        self._marketplace_path = self._base / "marketplace.json"
        self._installed: dict[str, dict[str, Any]] = {}
        self._load()

    # -- install / uninstall -------------------------------------------------
    def install(
        self,
        name: str,
        version: str = "1.0.0",
        capabilities: list[str] | None = None,
        source: str = "local",
        source_url: str = "",
        dependencies: list[str] | None = None,
    ) -> dict[str, Any]:
        """Install a plugin from a source."""
        pid = name.replace("/", "_").replace("@", "")
        if pid in self._installed:
            return {"status": "already_installed", "name": name, "version": self._installed[pid].get("version")}

        plugin = {
            "id": pid,
            "name": name,
            "version": version,
            "capabilities": capabilities or [],
            "source": source,
            "source_url": source_url,
            "dependencies": dependencies or [],
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "enabled": True,
            "config": {},
        }
        self._installed[pid] = plugin
        self._save()
        return {"status": "installed", "plugin": plugin}

    def uninstall(self, name: str) -> dict[str, Any]:
        pid = name.replace("/", "_").replace("@", "")
        if pid not in self._installed:
            return {"status": "not_found", "name": name}
        removed = self._installed.pop(pid)
        self._save()
        return {"status": "uninstalled", "plugin": removed}

    # -- configure -----------------------------------------------------------
    def configure(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        pid = name.replace("/", "_").replace("@", "")
        if pid not in self._installed:
            return {"status": "not_found", "name": name}
        self._installed[pid]["config"] = {**self._installed[pid].get("config", {}), **config}
        self._save()
        return {"status": "configured", "name": name}

    def toggle(self, name: str, enabled: bool) -> dict[str, Any]:
        pid = name.replace("/", "_").replace("@", "")
        if pid not in self._installed:
            return {"status": "not_found", "name": name}
        self._installed[pid]["enabled"] = enabled
        self._save()
        return {"status": "toggled", "name": name, "enabled": enabled}

    # -- listing -------------------------------------------------------------
    def list_installed(self, capability: str | None = None) -> list[dict[str, Any]]:
        plugins = list(self._installed.values())
        if capability:
            plugins = [p for p in plugins if capability in p.get("capabilities", [])]
        return sorted(plugins, key=lambda p: p.get("name", ""))

    def list_customizations(self) -> list[dict[str, Any]]:
        """List plugin customizations (Cindy's ListCustomizationsResult)."""
        return [
            {"name": p["name"], "version": p["version"], "capabilities": p.get("capabilities", []),
             "enabled": p.get("enabled", True), "config": p.get("config", {})}
            for p in self._installed.values()
        ]

    def count(self) -> int:
        return len(self._installed)

    # -- marketplace ---------------------------------------------------------
    def publish_to_marketplace(self, name: str, description: str, author: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        """Publish a local plugin to the shared marketplace."""
        pid = name.replace("/", "_").replace("@", "")
        if pid not in self._installed:
            return {"status": "not_found", "needs_install_first": True}
        mkt = self._load_json(self._marketplace_path) or {}
        mkt[pid] = {
            "name": name, "description": description, "author": author,
            "tags": tags or [], "version": self._installed[pid]["version"],
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._save_json(self._marketplace_path, mkt)
        return {"status": "published", "name": name}

    def list_marketplace(self, tag: str | None = None) -> list[dict[str, Any]]:
        mkt = self._load_json(self._marketplace_path) or {}
        items = list(mkt.values())
        if tag:
            items = [i for i in items if tag in i.get("tags", [])]
        return sorted(items, key=lambda i: i.get("name", ""))

    # -- persistence ---------------------------------------------------------
    def _save(self) -> None:
        self._save_json(self._installed_path, self._installed)

    def _load(self) -> None:
        self._installed = self._load_json(self._installed_path) or {}

    @staticmethod
    def _save_json(path: Path, obj: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _load_json(path: Path) -> Any | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
