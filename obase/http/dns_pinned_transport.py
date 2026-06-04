"""obase.http.dns_pinned_transport — DNS-pinned HTTP/HTTPS transport for SSRF prevention.

Resolves DNS once at request time, pins to IP, preventing DNS rebinding attacks.
TOCTOU mitigation: resolve → connect to resolved IP (not hostname again).
Used by oprim.url_fetch_ssrf_safe and any internal HTTP calls needing SSRF protection.

Security: checks ALL A and AAAA records, blocks private/reserved/unspecified/multicast
ranges. HTTPS uses ssl.create_default_context() with a connect() override so TLS
SNI and certificate validation still use the original hostname (not the raw IP).

Docker bridge: ONLY the default Docker bridge 172.17.0.0/16 is explicitly allowed
(checked before the blocklist). The full RFC-1918 172.16.0.0/12 range remains
blocked. If your deployment uses a non-default bridge subnet, add it to
_ALLOWED_DOCKER_NETWORKS.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.request


# Narrow allowlist for Docker internal service calls.
# Checked BEFORE _BLOCKED_NETWORKS — only what's listed here bypasses the block.
# Default Docker bridge is 172.17.0.0/16. Expand only if your deployment
# uses additional subnets for legitimate internal services.
_ALLOWED_DOCKER_NETWORKS: list[ipaddress.IPv4Network] = [
    ipaddress.ip_network("172.17.0.0/16"),  # Docker default bridge (searxng etc.)
]

# Private/reserved IP ranges to block.
# 172.16.0.0/12 is kept in the blocklist; only 172.17.0.0/16 (above) is allowed.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),  # "this" network
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918 private
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata endpoint
    ipaddress.ip_network(
        "172.16.0.0/12"
    ),  # RFC 1918 private (Docker bridge excepted via allowlist)
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918 private
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


class SSRFBlockedError(Exception):
    """Raised when a URL resolves to a private/blocked IP address."""


def is_safe_ip(ip: str) -> bool:
    """Return True if the IP is a public, routable, or explicitly allowed address.

    Allowlist (_ALLOWED_DOCKER_NETWORKS) is checked first — entries there bypass
    the blocklist. Everything else follows: loopback, link-local, metadata endpoints,
    full RFC-1918, CGNAT, multicast, reserved, and unspecified addresses are blocked.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    # Unwrap IPv4-mapped IPv6 (::ffff:192.168.x.x) before checking
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped

    # Narrow Docker allowlist takes precedence over the blocklist
    if any(addr in net for net in _ALLOWED_DOCKER_NETWORKS):
        return True

    # stdlib attributes + explicit blocklist
    if (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return False

    return not any(addr in net for net in _BLOCKED_NETWORKS)


def resolve_and_check(hostname: str) -> str:
    """Resolve hostname to all IPs via getaddrinfo, raise SSRFBlockedError if any is blocked.

    Checks ALL A and AAAA records — if any single record resolves to a blocked
    address the entire request is rejected. Returns first safe IPv4 address.
    """
    try:
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

    return first_safe_ipv4 or results[0][4][0]


# ---------------------------------------------------------------------------
# HTTP handler — DNS pinning via host replacement
# ---------------------------------------------------------------------------


class DNSPinnedHTTPHandler(urllib.request.HTTPHandler):
    """HTTP handler that resolves DNS once and pins to the resolved IP."""

    def http_open(self, req):
        hostname = req.host.split(":")[0]
        ip = resolve_and_check(hostname)
        port = req.host.split(":")[1] if ":" in req.host else "80"
        req.host = f"{ip}:{port}" if port != "80" else ip
        req.add_unredirected_header("Host", hostname)
        return self.do_open(http.client.HTTPConnection, req)


# ---------------------------------------------------------------------------
# HTTPS handler — DNS pinning + proper TLS with ssl.create_default_context()
# ---------------------------------------------------------------------------


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that connects to a pinned IP but validates TLS against the
    original hostname.

    Python 3.14 removed the private ``_server_hostname`` constructor path.
    We override ``connect()`` to call ``ssl.create_default_context().wrap_socket``
    with the original hostname explicitly — 100% public stdlib API.
    """

    # Set by DNSPinnedHTTPSHandler before handing to do_open
    _sni_hostname: str = ""

    def connect(self) -> None:
        # Establish the raw TCP socket to the pinned IP (super = HTTPConnection)
        http.client.HTTPConnection.connect(self)

        # Determine SNI / certificate hostname:
        # - tunnel host if we're going through a proxy
        # - our override (_sni_hostname) otherwise — NOT self.host which is the IP
        if self._tunnel_host:
            sni = self._tunnel_host
        else:
            sni = self._sni_hostname or self.host

        ctx = (
            self._context
            if (hasattr(self, "_context") and self._context)
            else ssl.create_default_context()
        )
        self.sock = ctx.wrap_socket(self.sock, server_hostname=sni)


class DNSPinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPS handler: resolves DNS once, connects to IP, validates TLS against original hostname.

    Uses ssl.create_default_context() (public API) for certificate validation.
    SNI passes the original hostname so the server returns the correct certificate.
    """

    def https_open(self, req):
        orig_hostname = req.host.split(":")[0]
        ip = resolve_and_check(orig_hostname)
        port = req.host.split(":")[1] if ":" in req.host else "443"
        ctx = ssl.create_default_context()
        pinned_sni = orig_hostname

        def _make_pinned_conn(host, **kwargs):
            # Ignore 'host' (comes from req.host = original name); we connect to IP
            kwargs.pop("context", None)  # we supply our own context
            conn = _PinnedHTTPSConnection(f"{ip}:{port}", context=ctx, **kwargs)
            conn._sni_hostname = pinned_sni
            return conn

        req.add_unredirected_header("Host", orig_hostname)
        return self.do_open(_make_pinned_conn, req, context=ctx)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def make_ssrf_safe_opener(timeout: int = 10) -> urllib.request.OpenerDirector:
    """Create a urllib opener with DNS pinning for SSRF prevention (HTTP + HTTPS).

    Args:
        timeout: Request timeout in seconds.

    Returns:
        OpenerDirector with DNS-pinned HTTP and HTTPS handlers.

    Raises:
        SSRFBlockedError: (at open time) if URL resolves to a private/blocked IP.

    Example:
        opener = make_ssrf_safe_opener()
        response = opener.open("https://api.github.com/zen")
    """
    return urllib.request.build_opener(DNSPinnedHTTPHandler, DNSPinnedHTTPSHandler)
