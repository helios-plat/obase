"""obase.pseudo_anonymizer — PII 脱敏与伪名化转换 (SPEC §5.5.1).

规范: 伪名 = sha256(salt + 原始值).hexdigest()[:24]。
真实 PII（user_id、手机号、真名）禁止进入 fingerprint 与 decision_trail；
服务层必须先经本模块伪名化。

Example:
    >>> p = PseudoAnonymizer(salt="dev-salt")
    >>> p.user("u_1001")
    '1f9d8e...'  # 24 hex chars
    >>> p.user("u_1001") == p.user("u_1001")
    True
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

__all__ = [
    "PseudoAnonymizer",
    "pseudo_anonymize",
    "pseudo_anonymize_user",
    "ENV_SALT_KEY",
]

ENV_SALT_KEY = "OBASE_PSEUDO_SALT"


def pseudo_anonymize(value: str, *, salt: str) -> str:
    """sha256(salt + value) 的前 24 个 hex 字符 —— 确定性伪名。

    Args:
        value: 待脱敏的原始值（user_id / 手机号 / 邮箱…）。
        salt: 固定盐（项目级部署密钥），保证跨调用确定性且不可逆。

    Raises:
        ValueError: value 或 salt 为空。
    """
    if not value:
        raise ValueError("pseudo_anonymize: value must not be empty")
    if not salt:
        raise ValueError("pseudo_anonymize: salt must not be empty")
    digest = hashlib.sha256((salt + value).encode("utf-8")).hexdigest()
    return digest[:24]


def pseudo_anonymize_user(user_id: str, *, salt: str | None = None) -> str:
    """用户 ID 伪名化；salt 缺省取环境变量 OBASE_PSEUDO_SALT。"""
    salt = salt or os.environ.get(ENV_SALT_KEY, "")
    return pseudo_anonymize(user_id, salt=salt)


class PseudoAnonymizer:
    """持盐的伪名化器：对用户 / 手机号 / 邮箱 / 任意字段做确定性转换。

    Example:
        >>> p = PseudoAnonymizer(salt="s")
        >>> p.user("u_1") == pseudo_anonymize("u_1", salt="s")
        True
    """

    def __init__(self, salt: str | None = None) -> None:
        self.salt = salt or os.environ.get(ENV_SALT_KEY, "")
        if not self.salt:
            raise ValueError(
                "PseudoAnonymizer requires a salt — pass salt=... or set "
                f"{ENV_SALT_KEY} env var"
            )

    def user(self, user_id: str) -> str:
        return pseudo_anonymize(user_id, salt=self.salt)

    def phone(self, phone: str) -> str:
        return pseudo_anonymize(phone, salt=self.salt)

    def email(self, email: str) -> str:
        return pseudo_anonymize(email, salt=self.salt)

    def field(self, value: str) -> str:
        """任意字段伪名化（统一入口）。"""
        return pseudo_anonymize(value, salt=self.salt)

    def anonymize_payload(self, payload: dict[str, Any], *, fields: list[str]) -> dict[str, Any]:
        """对 dict 中指定顶层字段做伪名化替换，返回新 dict（不原地改）。"""
        out = dict(payload)
        for f in fields:
            if f in out and out[f] is not None:
                out[f] = self.field(str(out[f]))
        return out
