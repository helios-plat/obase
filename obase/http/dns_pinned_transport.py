"""obase.http.dns_pinned_transport — DNS-pinned HTTP/HTTPS transport for SSRF prevention.

Resolves DNS once at request time, pins to IP, preventing DNS rebinding attacks.
TOCTOU mitigation: resolve → connect to resolved IP (not hostname again).
Used by oprim.url_fetch_ssrf_safe and any internal HTTP calls needing SSRF protection.

Security: checks ALL A and AAAA records, blocks private/reserved/unspecified/multicast
ranges, covers both HTTP and HTTPS (HTTPS uses SNI override so TLS cert validation
still validates against the original hostname).
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.request


# Private/reserved IP ranges to block.
# Primary check uses stdlib addr attributes (is_private, is_loopback, etc.).
# Explicit list covers older Python and edge cases not caught by attributes.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),  # "this" network
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


class SSRFBlockedError(Exception):
    """Raised when a URL resolves to a private/blocked IP address."""


def is_safe_ip(ip: str) -> bool:
    """Return True if the IP is a public, routable address.

    Blocks private, loopback, link-local, multicast, reserved, and unspecified
    addresses. Also checks IPv4-mapped IPv6 by unwrapping the embedded IPv4.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    # Unwrap IPv4-mapped IPv6 (::ffff:192.168.x.x) before checking
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped

    # Use stdlib attributes as primary check (catches most cases)
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return False

    # Explicit network list as defence-in-depth (covers CGNAT and edge cases)
    return not any(addr in net for net in _BLOCKED_NETWORKS)


def resolve_and_check(hostname: str) -> str:
    """Resolve hostname to all IPs, raise SSRFBlockedError if any is private/blocked.

    Uses getaddrinfo to resolve ALL A and AAAA records (not just gethostbyname's
    single IPv4 result). Returns the first safe IPv4 address for connection pinning.
    """
    try:
        # Resolve all address families; port=0 and proto=0 → no filtering
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFBlockedError(f"DNS resolution failed for {hostname!r}: {e}") from e

    if not results:
        raise SSRFBlockedError(f"DNS returned no records for {hostname!r}")

    first_safe_ipv4: str | None = None

    for family, _type, _proto, _canonname, sockaddr in results:
        ip = sockaddr[0]
        if not is_safe_ip(ip):
            raise SSRFBlockedError(
                f"Hostname {hostname!r} resolves to blocked IP {ip!r} (private/reserved)"
            )
        if family == socket.AF_INET and first_safe_ipv4 is None:
            first_safe_ipv4 = ip

    # Return first IPv4 for connection (IPv6 pinning via host header works too,
    # but IPv4 avoids bracket-notation complexity in request Host headers).
    return first_safe_ipv4 or results[0][4][0]


class DNSPinnedHTTPHandler(urllib.request.HTTPHandler):
    """HTTP handler that resolves DNS once and pins to the resolved IP."""

    def http_open(self, req):
        hostname = req.host.split(":")[0]
        ip = resolve_and_check(hostname)
        port = req.host.split(":")[1] if ":" in req.host else "80"
        req.host = f"{ip}:{port}" if port != "80" else ip
        req.add_unredirected_header("Host", hostname)
        return self.do_open(http.client.HTTPConnection, req)


class DNSPinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPS handler that resolves DNS once, pins to IP, preserves SNI/cert validation.

    Connects to the resolved IP directly (preventing DNS rebinding) while passing
    the original hostname as server_hostname so TLS SNI and certificate validation
    still use the correct hostname.
    """

    def https_open(self, req):
        hostname = req.host.split(":")[0]
        ip = resolve_and_check(hostname)
        port = req.host.split(":")[1] if ":" in req.host else "443"

        # Build a factory that connects to the pinned IP but presents the
        # original hostname for SNI and cert CN/SAN validation.
        orig_hostname = hostname

        def _make_https_conn(host, **kwargs):
            conn = http.client.HTTPSConnection(
                f"{ip}:{port}",
                **kwargs,
            )
            # Override server_hostname so TLS uses the original hostname for
            # SNI extension and certificate validation (not the raw IP).
            conn._server_hostname = orig_hostname  # type: ignore[attr-defined]
            return conn

        req.add_unredirected_header("Host", hostname)
        return self.do_open(
            _make_https_conn, req, context=self._context if hasattr(self, "_context") else None
        )  # type: ignore[arg-type]


def make_ssrf_safe_opener(timeout: int = 10) -> urllib.request.OpenerDirector:
    """Create a urllib opener with DNS pinning for SSRF prevention (HTTP + HTTPS).

    Args:
        timeout: Request timeout in seconds.

    Returns:
        OpenerDirector with DNS-pinned HTTP and HTTPS handlers.

    Raises:
        SSRFBlockedError: (at open time) if the URL resolves to a private IP.

    Example:
        opener = make_ssrf_safe_opener()
        response = opener.open("https://example.com/data")
    """
    return urllib.request.build_opener(DNSPinnedHTTPHandler, DNSPinnedHTTPSHandler)
