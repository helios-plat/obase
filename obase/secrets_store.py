"""obase.secrets_store — encrypted secrets persistence resource.

3O layer: obase (I/O and resources).
Wraps oprim.fernet_vault primitives into a SecretsStore resource:
vault dir management, env-key override, 0600 permissions, atomic writes.

The store NEVER exposes plaintext to LLM callers — it only hands secrets to
trusted physical callbacks via injected parameters.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet
from oprim._fernet_vault import (
    fernet_dump,
    fernet_load,
    fernet_load_or_create_key,
)

DEFAULT_VAULT_DIR = str(Path.home() / ".veya" / "vault")


class SecretsStore:
    """Encrypted key-value secrets store (vault_id -> plaintext)."""

    def __init__(self, vault_dir: str | Path | None = None, env_key_var: str = "VEYA_VAULT_KEY"):
        self.vault_dir = Path(
            vault_dir or os.environ.get("VEYA_VAULT_DIR", DEFAULT_VAULT_DIR)
        ).expanduser()
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self._env_key_var = env_key_var
        self._fernet: Fernet = fernet_load_or_create_key(
            self.vault_dir / "vault.key", env_key=os.environ.get(env_key_var)
        )
        self._secrets: dict[str, str] = fernet_load(self._fernet, self.vault_dir / "vault.json")

    # ── 密钥管理(仅后端/运维调用) ────────────────────────────────────
    def set_secret(self, vault_id: str, secret: str) -> str:
        if not vault_id or not secret:
            return "❌ vault_id 与 secret 不能为空"
        self._secrets[vault_id] = secret
        self._persist()
        return f"✅ 密钥 '{vault_id}' 已入库(Fernet 加密, 大模型不可见)"

    def has_secret(self, vault_id: str) -> bool:
        return vault_id in self._secrets

    def list_secret_ids(self) -> list[str]:
        return sorted(self._secrets)

    def delete_secret(self, vault_id: str) -> str:
        if vault_id not in self._secrets:
            return f"金库中不存在凭据 ID '{vault_id}'"
        del self._secrets[vault_id]
        self._persist()
        return f"✅ 密钥 '{vault_id}' 已删除"

    def get_secret(self, vault_id: str) -> str | None:
        """内部取用: 仅限受信物理回调路径(HITL 批准后注入), 绝不进入对话。"""
        return self._secrets.get(vault_id)

    def _persist(self) -> None:
        fernet_dump(self._fernet, self._secrets, self.vault_dir / "vault.json")
