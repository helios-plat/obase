"""obase.sandbox.path_jail — workspace path prison. No I/O beyond resolve."""

from __future__ import annotations

from pathlib import Path


class PathJail:
    def __init__(self, workspace_root: Path | str) -> None:
        self.root = Path(workspace_root).expanduser().resolve()

    def resolve_and_verify(self, target_path: str) -> Path:
        """Resolve ``target_path`` under the root. ``../`` and absolute escapes fail."""
        raw = Path(target_path)
        candidate = raw if raw.is_absolute() else (self.root / raw)
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError(f"Path escape attempt blocked: {target_path}") from exc
        return resolved
