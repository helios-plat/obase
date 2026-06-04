"""obase.http — HTTP utilities subpackage."""

from __future__ import annotations

from obase.http.dns_pinned_transport import (
    SSRFBlockedError,
    is_safe_ip,
    make_ssrf_safe_opener,
    resolve_and_check,
)

__all__ = [
    "SSRFBlockedError",
    "is_safe_ip",
    "make_ssrf_safe_opener",
    "resolve_and_check",
]
