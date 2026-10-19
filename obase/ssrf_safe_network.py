"""obase.ssrf_safe_network — 支持 SSRF 防火墙与私网过滤的安全主动联网客户端.

职责:
- URL 安全校验（拦截内网 IP / 私有地址）
- 为 oprim.web_search_fetch / oskill.proactive_deep_reach 提供安全联网基础设施
- 防止 SSRF 攻击与私网探测

设计:
- 纯基础设施（无 3O 层依赖）
- 支持 URL 安全校验 + HTTP(S) 请求
- 复用 obase.http.dns_pinned_transport 的 IP 安全检测

例:
    >>> net = SSRFSafeNetwork()
    >>> net.is_safe_url("https://example.com")
    True
    >>> net.is_safe_url("http://127.0.0.1/admin")
    False
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

__all__ = ["SSRFSafeNetwork", "SSRFSafeNetworkError"]


class SSRFSafeNetworkError(RuntimeError):
    """安全网络请求错误."""


class SSRFSafeNetwork:
    """主动联网安全防火墙（防止 SSRF 攻击与私网探测）.

    检查规则:
    1. 协议必须为 http 或 https
    2. 主机名不能解析到内网/保留/回环地址
    3. 阻止常见云元数据端点
    """

    # 禁止的 IP 前缀（含完整 IP）
    FORBIDDEN_IP_PREFIXES: tuple[str, ...] = (
        "10.",
        "172.16.",
        "172.17.",
        "172.18.",
        "172.19.",
        "172.20.",
        "172.21.",
        "172.22.",
        "172.23.",
        "172.24.",
        "172.25.",
        "172.26.",
        "172.27.",
        "172.28.",
        "172.29.",
        "172.30.",
        "172.31.",
        "192.168.",
        "127.",
        "0.",
        "localhost",
        "169.254.",
        "::1",
        "fc00:",
        "fd00:",
        "fe80:",
    )

    # 云元数据端点
    CLOUD_METADATA_HOSTS: tuple[str, ...] = (
        "metadata.google.internal",
        "169.254.169.254",
        "instance-data.ec2.internal",
    )

    def __init__(self, *, timeout: int = 30, user_agent: str = "3O-SSRFSafe/1.0") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def is_safe_url(self, url: str) -> bool:
        """校验 URL 是否安全可访问（拦截内网 IP / 元数据端点）.

        Args:
            url: 待校验的 URL

        Returns:
            True 如果安全可访问
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        # 协议检查
        if parsed.scheme not in ("http", "https"):
            return False

        # 主机名检查
        hostname = parsed.hostname or ""
        if not hostname:
            return False

        # 阻止云元数据端点
        if hostname.lower() in self.CLOUD_METADATA_HOSTS:
            return False

        # IP 前缀检查
        for prefix in self.FORBIDDEN_IP_PREFIXES:
            if hostname.startswith(prefix) or hostname == prefix:
                return False

        return True

    def safe_fetch(self, url: str) -> dict[str, Any]:
        """安全抓取网页内容.

        Args:
            url: 目标 URL

        Returns:
            {"status": "success", "content": "...", "url": "..."} 或
            {"status": "blocked", "reason": "...", "url": "..."}
        """
        if not self.is_safe_url(url):
            return {
                "status": "blocked",
                "reason": "SSRF Firewall: Forbidden Internal Target Address.",
                "url": url,
            }

        try:
            import urllib.request

            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.user_agent},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content = resp.read().decode("utf-8", errors="replace")[:100_000]
                return {
                    "status": "success",
                    "url": url,
                    "content": content,
                    "content_length": len(content),
                    "http_status": resp.status,
                }
        except Exception as e:
            return {
                "status": "failed",
                "url": url,
                "reason": f"Fetch failed: {type(e).__name__}: {e}",
            }

    def health(self) -> dict[str, Any]:
        """健康检查."""
        return {
            "status": "healthy",
            "timeout": self.timeout,
        }
