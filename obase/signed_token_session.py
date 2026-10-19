"""obase.signed_token_session — 签名会话令牌.

HMAC-SHA256 签名会话令牌：签发（含过期与声明）、验签、撤销（内存 + 可选持久化）。
纯 stdlib，无外部依赖。

Example:
    >>> mgr = SignedTokenSession(secret="dev-secret")
    >>> token = mgr.create("user_1", ttl_s=3600, claims={"role": "admin"})
    >>> payload = mgr.verify(token)
    >>> payload["user_id"]
    'user_1'
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from typing import Any

__all__ = ["SignedTokenSession", "TokenError", "TokenExpiredError", "TokenRevokedError"]


class TokenError(ValueError):
    """令牌无效。"""


class TokenExpiredError(TokenError):
    """令牌过期。"""


class TokenRevokedError(TokenError):
    """令牌已撤销。"""


class SignedTokenSession:
    """HMAC 签名会话管理器。"""

    def __init__(self, secret: str, *, issuer: str = "veya", leeway_s: float = 30.0) -> None:
        if not secret:
            raise ValueError("signed_token_session: secret must not be empty")
        self._secret = secret.encode()
        self._issuer = issuer
        self._leeway = leeway_s
        self._revoked: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 签发/验签
    # ------------------------------------------------------------------

    def create(
        self,
        user_id: str,
        *,
        ttl_s: float = 3600.0,
        claims: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> str:
        """签发会话令牌。"""
        if not user_id:
            raise ValueError("signed_token_session: user_id must not be empty")
        if ttl_s <= 0:
            raise ValueError("signed_token_session: ttl_s must be > 0")
        import uuid

        header = {"alg": "HS256", "typ": "JWT"}
        now = time.time()
        payload = {
            "iss": self._issuer,
            "sub": user_id,
            "iat": now,
            "exp": now + ttl_s,
            "sid": session_id or uuid.uuid4().hex[:16],
            **(claims or {}),
        }
        signing_input = f"{_b64(header)}.{_b64(payload)}"
        signature = self._sign(signing_input)
        return f"{signing_input}.{signature}"

    def verify(self, token: str) -> dict[str, Any]:
        """验签 + 过期 + 撤销检查，返回 payload。"""
        parts = token.split(".")
        if len(parts) != 3:
            raise TokenError("malformed token")
        signing_input = f"{parts[0]}.{parts[1]}"
        expected = self._sign(signing_input)
        if not hmac.compare_digest(parts[2], expected):
            raise TokenError("signature mismatch")

        try:
            payload = json.loads(_unb64(parts[1]))
        except Exception as exc:
            raise TokenError("invalid payload") from exc

        now = time.time()
        if payload.get("exp", 0) < now - self._leeway:
            raise TokenExpiredError("token expired")

        sid = payload.get("sid", "")
        with self._lock:
            if sid in self._revoked:
                raise TokenRevokedError("token revoked")
        return payload

    def refresh(self, token: str, *, ttl_s: float = 3600.0) -> str:
        """用未过期令牌换发新令牌（保留 claims，滚动 sid 需显式撤销旧令牌）。"""
        payload = self.verify(token)
        claims = {k: v for k, v in payload.items() if k not in ("iss", "sub", "iat", "exp", "sid")}
        return self.create(payload["sub"], ttl_s=ttl_s, claims=claims)

    # ------------------------------------------------------------------
    # 撤销
    # ------------------------------------------------------------------

    def revoke(self, token: str) -> bool:
        """按 sid 撤销（幂等）。"""
        parts = token.split(".")
        if len(parts) != 3:
            return False
        try:
            payload = json.loads(_unb64(parts[1]))
        except Exception:  # pragma: no cover
            return False
        sid = payload.get("sid")
        if not sid:
            return False
        with self._lock:
            self._revoked.add(sid)
        return True

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._revoked.add(session_id)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _sign(self, signing_input: str) -> str:
        digest = hmac.new(self._secret, signing_input.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "issuer": self._issuer,
            "revoked_sessions": len(self._revoked),
        }


def _b64(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
