"""obase.secrets.master_key — 从外部源装载 32 字节主加密密钥.

从显式 source URI 解析主密钥,替代"由应用 secret 派生"(无域分离、强度受限)的做法。
装载器**绝不静默回退**:源不可用或不合法即抛错,使调用方无法在无察觉下降级到弱密钥。

支持的 scheme (D2-min):
    env://VAR_NAME   — 从进程环境读 VAR_NAME
    file:///abs/path — 读密钥文件(裸 32 字节,或 base64 / hex 文本)

未知 scheme 抛 ObaseSecretsError;age:// / sops:// 作为后续独立 backend 引入。

Example:
    >>> import base64, os
    >>> os.environ["MK"] = base64.b64encode(b"x" * 32).decode()
    >>> load_master_key(source="env://MK") == b"x" * 32
    True

Raises:
    ObaseSecretsError: source 非 URI、scheme 不支持、源缺失、或解码后非 32 字节.
"""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path

from obase.exceptions import ObaseSecretsError

_KEY_LEN = 32


def _decode_key(raw: bytes) -> bytes:
    """把源字节归一化为 32 字节密钥(裸 / base64 / hex)."""
    if len(raw) == _KEY_LEN:
        return raw

    text = raw.strip()
    for decoder in (
        lambda b: base64.b64decode(b, validate=True),
        binascii.unhexlify,
    ):
        try:
            decoded = decoder(text)
        except (binascii.Error, ValueError):
            continue
        if len(decoded) == _KEY_LEN:
            return decoded

    raise ObaseSecretsError(
        f"master key must be {_KEY_LEN} bytes raw, or base64/hex encoding thereof; "
        f"got {len(raw)} source bytes that decode to neither"
    )


def load_master_key(*, source: str) -> bytes:
    """从外部 source 装载 32 字节主密钥.

    Args:
        source: 密钥源 URI. env://VAR_NAME 或 file:///abs/path.

    Returns:
        32 字节主密钥.

    Raises:
        ObaseSecretsError: source 非 URI、scheme 不支持、源缺失或解码后非 32 字节.
            绝不回退——调用方据此确保不会静默降级到弱密钥.
    """
    if "://" not in source:
        raise ObaseSecretsError(
            f"master key source must be a URI (env://VAR or file:///path); got {source!r}"
        )

    scheme, _, rest = source.partition("://")
    scheme = scheme.lower()

    if scheme == "env":
        if not rest:
            raise ObaseSecretsError("env:// source requires a variable name")
        val = os.environ.get(rest)
        if val is None:
            raise ObaseSecretsError(f"env var {rest!r} is not set for master key")
        return _decode_key(val.encode("utf-8"))

    if scheme == "file":
        path = Path(rest)
        if not path.is_file():
            raise ObaseSecretsError(f"master key file not found: {path}")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ObaseSecretsError(f"cannot read master key file {path}: {exc}") from exc
        return _decode_key(raw)

    raise ObaseSecretsError(
        f"unsupported master-key source scheme {scheme!r}; "
        "supported: env, file (age/sops planned as follow-on backends)"
    )
