"""obase.permission_contract — HMAC 能力令牌（CapabilityToken）与能力校验契约.

受控动作契约：
- 所有需要管控的动作必须持有对应 capability（如 executor.restart / causal_graph.write）。
- 令牌 = HMAC-SHA256 签名的紧凑 payload（subject + capabilities + envelope_ref + 过期时间）。
- capability 命名规范：<domain>.<action>；校验支持 domain.* 通配匹配。
- 可撤销：CapabilityRevoker 按 nonce 撤销（内存 + 可选 JSONL 持久化）。

零反向依赖（obase 铁律）：不 import oprim/oskill/omodul。
纯 stdlib：hmac / hashlib / base64 / json / time / secrets。

例:
    >>> secret = "dev-secret-32chars-xxxxxxxxxxxxxxxx"
    >>> tok = issue_capability_token(secret, subject="scheduler",
    ...                              capabilities={"executor.restart", "causal_graph.write"})
    >>> verified = verify_capability_token(secret, tok)
    >>> verified.has_capability("executor.restart")
    True
    >>> check_capability(verified, "executor.restart")
    True
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "CapabilityToken",
    "CapabilityError",
    "CapabilityExpiredError",
    "CapabilityDeniedError",
    "issue_capability_token",
    "verify_capability_token",
    "check_capability",
    "CapabilityRevoker",
]


class CapabilityError(ValueError):
    """能力令牌无效（格式/签名错误）。"""


class CapabilityExpiredError(CapabilityError):
    """能力令牌已过期或已撤销。"""


class CapabilityDeniedError(PermissionError):
    """缺少所需 capability。"""


@dataclass(frozen=True)
class CapabilityToken:
    """解析后的能力令牌（不可变）。"""

    subject: str
    capabilities: frozenset[str]
    envelope_ref: str | None = None
    issuer: str = "obase"
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    nonce: str = ""

    def has_capability(self, required: str) -> bool:
        """required 支持 domain.* 通配；令牌侧声明的通配能力也生效。"""
        for cap in self.capabilities:
            if cap == required:
                return True
            # required 通配: "executor.*" 匹配令牌里的 "executor.restart"
            if required.endswith(".*") and cap.startswith(required[:-1]):
                return True
            # 令牌通配: "executor.*" 匹配 required "executor.restart"
            if cap.endswith(".*") and required.startswith(cap[:-1]):
                return True
        return False

    def is_expired(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self.expires_at > 0 and now > self.expires_at

    def to_payload(self) -> dict[str, Any]:
        return {
            "sub": self.subject,
            "caps": sorted(self.capabilities),
            "env": self.envelope_ref,
            "iss": self.issuer,
            "iat": self.issued_at,
            "exp": self.expires_at,
            "nonce": self.nonce,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CapabilityToken:
        return cls(
            subject=payload["sub"],
            capabilities=frozenset(payload.get("caps", [])),
            envelope_ref=payload.get("env"),
            issuer=payload.get("iss", "obase"),
            issued_at=float(payload.get("iat", 0.0)),
            expires_at=float(payload.get("exp", 0.0)),
            nonce=payload.get("nonce", ""),
        )


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(secret: str, payload_b64: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    return _b64e(digest)


def issue_capability_token(
    secret: str,
    *,
    subject: str,
    capabilities: Iterable[str],
    envelope_ref: str | None = None,
    ttl_s: float = 3600.0,
    issuer: str = "obase",
    nonce: str | None = None,
) -> str:
    """签发 HMAC-SHA256 能力令牌（紧凑字符串：<payload_b64>.<signature_b64>）。"""
    if not secret:
        raise CapabilityError("issue_capability_token: secret must not be empty")
    if not subject:
        raise CapabilityError("issue_capability_token: subject must not be empty")
    caps = frozenset(capabilities)
    if not caps:
        raise CapabilityError("issue_capability_token: at least one capability required")
    now = time.time()
    payload = {
        "sub": subject,
        "caps": sorted(caps),
        "env": envelope_ref,
        "iss": issuer,
        "iat": now,
        "exp": now + ttl_s if ttl_s > 0 else 0.0,
        "nonce": nonce or secrets.token_hex(8),
    }
    payload_b64 = _b64e(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    return f"{payload_b64}.{_sign(secret, payload_b64)}"


def verify_capability_token(
    secret: str,
    token: str,
    *,
    revoker: CapabilityRevoker | None = None,
) -> CapabilityToken:
    """验签并解析；签名错误/过期/已撤销均抛错。"""
    if not token:
        raise CapabilityError("verify_capability_token: empty token")
    try:
        payload_b64, signature = token.rsplit(".", 1)
    except (ValueError, AttributeError) as exc:
        raise CapabilityError("verify_capability_token: malformed token") from exc
    expected = _sign(secret, payload_b64)
    if not hmac.compare_digest(signature, expected):
        raise CapabilityError("verify_capability_token: signature mismatch")
    try:
        payload = json.loads(_b64d(payload_b64))
        tok = CapabilityToken.from_payload(payload)
    except (ValueError, KeyError, TypeError) as exc:
        raise CapabilityError("verify_capability_token: invalid payload") from exc
    if tok.is_expired():
        raise CapabilityExpiredError("verify_capability_token: token expired")
    if revoker is not None and revoker.is_revoked(tok.nonce):
        raise CapabilityExpiredError("verify_capability_token: token revoked")
    return tok


def check_capability(token: CapabilityToken, required: str) -> bool:
    """断言式校验：持有返回 True，否则抛 CapabilityDeniedError。"""
    if token.has_capability(required):
        return True
    raise CapabilityDeniedError(
        f"capability denied: subject={token.subject!r} requires {required!r}; "
        f"holds {sorted(token.capabilities)}"
    )


class CapabilityRevoker:
    """能力令牌撤销表（内存 + 可选 JSONL 持久化）。

    按 nonce 撤销：签发时 nonce 随机生成，撤销 nonce 即可在 verify 时拒绝该令牌。
    """

    def __init__(self, persist_path: str | Path | None = None) -> None:
        self._revoked: set[str] = set()
        self._lock = threading.Lock()
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path is not None:
            self._load()

    def revoke(self, nonce: str) -> None:
        with self._lock:
            self._revoked.add(nonce)
        self._flush()

    def is_revoked(self, nonce: str) -> bool:
        with self._lock:
            return nonce in self._revoked

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        for line in self._persist_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                self._revoked.add(line)

    def _flush(self) -> None:
        if self._persist_path is None:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        with self._persist_path.open("w", encoding="utf-8") as f:
            for nonce in sorted(self._revoked):
                f.write(nonce + "\n")
