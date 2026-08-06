"""obase.support_bundle_pack — DeerFlow-style redacted diagnostic support bundle.

Creates a ZIP archive containing redacted config files, environment variables,
system info, and recent logs — safe to share for community troubleshooting.

3O element: ``obase.support_bundle_pack``.
"""

from __future__ import annotations

import json
import os
import platform
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|private[_-]?key|key|token|secret|password|passwd"
    r"|authorization|cookie|credential|dsn)",
)
_BEARER_RE = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def support_bundle_pack(
    output_dir: str | Path | None = None,
    include_doctor: bool = True,
    context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a redacted support bundle ZIP.

    Args:
        output_dir: Where to write the bundle (default: ~/.veya/bundles).
        include_doctor: Include system health check output.
        context: Optional config.

    Returns:
        {status, bundle_path, files_included, size_bytes}
    """
    ctx = context or {}
    base = Path(output_dir) if output_dir else Path.home() / ".veya" / "bundles"
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bundle_path = base / f"support-bundle-{ts}.zip"

    files: dict[str, str] = {}

    # system info
    files["system.json"] = json.dumps({
        "platform": platform.platform(),
        "python": platform.python_version(),
        "node": _sh("node --version") or "N/A",
        "cwd": str(Path.cwd()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)

    # redacted env
    env_lines = []
    for k, v in sorted(os.environ.items()):
        if _SECRET_RE.search(k):
            v = "***REDACTED***"
        elif _BEARER_RE.search(v or ""):
            v = _BEARER_RE.sub(r"\1***REDACTED***", v)
        elif _SK_KEY_RE.search(v or ""):
            v = _SK_KEY_RE.sub("sk-***REDACTED***", v)
        env_lines.append(f"{k}={v}")
    files["env.txt"] = "\n".join(env_lines)

    # redacted config (if present)
    for cfg in ("config.yaml", "config.yml", "config.example.yaml"):
        p = Path(ctx.get("project_root", ".")) / cfg
        if p.exists():
            text = _redact_yaml(p.read_text(encoding="utf-8"))
            files[cfg] = text

    # logs (last 200 lines)
    log_dir = Path(ctx.get("log_dir", Path.home() / ".veya" / "logs"))
    if log_dir.exists():
        for logf in sorted(log_dir.glob("*.log"))[-3:]:
            lines = logf.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            files[f"logs/{logf.name}"] = "\n".join(lines)

    # doctor
    if include_doctor:
        doctor = {}
        for name, cmd in [("disk", "df -h /"), ("memory", "free -m"), ("python_pkgs", f"{_py()} -m pip freeze 2>/dev/null | head -30")]:
            doctor[name] = _sh(cmd) or "N/A"
        files["doctor.txt"] = "\n\n".join(f"--- {k} ---\n{v}" for k, v in doctor.items())

    # write ZIP
    with zipfile.ZipFile(str(bundle_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)

    size = bundle_path.stat().st_size
    return {"status": "completed", "bundle_path": str(bundle_path), "files_included": len(files), "size_bytes": size}


def _redact_yaml(text: str) -> str:
    import re as _re
    for pattern in [
        r"(?im)^(\s*[\w.-]*(?:api[_-]?key|token|secret|password|passwd|authorization|cookie|credential|private[_-]?key)[\w.-]*\s*:\s*)(.+)$",
    ]:
        text = _re.sub(pattern, r"\1***REDACTED***", text)
    text = _BEARER_RE.sub(r"\1***REDACTED***", text)
    text = _SK_KEY_RE.sub("sk-***REDACTED***", text)
    return text


def _sh(cmd: str) -> str | None:
    import subprocess
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
    except Exception:
        return None


def _py() -> str:
    import sys
    return sys.executable
