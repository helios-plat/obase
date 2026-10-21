"""Canonical low-level Fernet vault substrate owned by obase."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


def fernet_load_or_create_key(key_path: str | Path, env_key: str | None = None) -> Fernet:
    if env_key:
        return Fernet(env_key.encode())
    path = Path(key_path)
    if path.exists():
        return Fernet(path.read_text(encoding="utf-8").strip().encode())
    key = Fernet.generate_key()
    path.write_text(key.decode(), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return Fernet(key)


def fernet_encrypt_dict(fernet: Fernet, secrets: dict[str, str]) -> dict[str, str]:
    return {key: fernet.encrypt(value.encode()).decode() for key, value in secrets.items()}


def fernet_decrypt_dict(fernet: Fernet, encrypted: dict[str, str]) -> dict[str, str]:
    return {key: fernet.decrypt(value.encode()).decode() for key, value in encrypted.items()}


def fernet_dump(fernet: Fernet, secrets: dict[str, str], path: str | Path) -> None:
    target = Path(path)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(fernet_encrypt_dict(fernet, secrets), indent=2), encoding="utf-8"
    )
    os.replace(temporary, target)
    with contextlib.suppress(OSError):
        os.chmod(target, 0o600)


def fernet_load(fernet: Fernet, path: str | Path) -> dict[str, str]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        encrypted: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        return fernet_decrypt_dict(fernet, encrypted)
    except (json.JSONDecodeError, OSError):
        return {}


__all__ = [
    "fernet_decrypt_dict",
    "fernet_dump",
    "fernet_encrypt_dict",
    "fernet_load",
    "fernet_load_or_create_key",
]
