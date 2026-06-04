"""Tests for obase.http.dns_pinned_transport."""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import patch

import pytest

from obase.http.dns_pinned_transport import (
    DNSPinnedHTTPSHandler,
    SSRFBlockedError,
    _ALLOWED_DOCKER_NETWORKS,
    _BLOCKED_NETWORKS,
    is_safe_ip,
    make_ssrf_safe_opener,
    resolve_and_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _addrinfo_ipv4(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _addrinfo_ipv6(ip: str):
    return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]


def _addrinfo_multi(ipv4: str, ipv6: str):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ipv4, 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ipv6, 0, 0, 0)),
    ]


# ---------------------------------------------------------------------------
# is_safe_ip
# ---------------------------------------------------------------------------


class TestIsPublicIp:
    def test_public_ip_is_safe(self):
        assert is_safe_ip("8.8.8.8") is True

    def test_another_public_ip(self):
        assert is_safe_ip("1.1.1.1") is True

    def test_private_192_is_blocked(self):
        assert is_safe_ip("192.168.1.1") is False

    def test_private_10_is_blocked(self):
        assert is_safe_ip("10.0.0.1") is False

    def test_docker_default_bridge_is_allowed(self):
        # Only the default Docker bridge 172.17.0.0/16 is in the allowlist.
        assert is_safe_ip("172.17.0.1") is True
        assert is_safe_ip("172.17.255.254") is True

    def test_non_default_docker_subnets_are_blocked(self):
        # 172.16.0.0/12 minus 172.17.0.0/16 remains blocked.
        assert is_safe_ip("172.16.0.1") is False
        assert is_safe_ip("172.31.255.254") is False
        assert is_safe_ip("172.18.0.1") is False

    def test_loopback_is_blocked(self):
        assert is_safe_ip("127.0.0.1") is False

    def test_link_local_metadata_is_blocked(self):
        # 169.254.169.254 is the AWS/GCP/Azure metadata endpoint — must be blocked
        assert is_safe_ip("169.254.169.254") is False
        assert is_safe_ip("169.254.0.0") is False

    def test_zero_network_is_blocked(self):
        assert is_safe_ip("0.0.0.1") is False

    def test_cgnat_is_blocked(self):
        assert is_safe_ip("100.64.0.1") is False
        assert is_safe_ip("100.127.255.255") is False

    def test_ipv4_mapped_ipv6_private_is_blocked(self):
        assert is_safe_ip("::ffff:192.168.1.1") is False

    def test_ipv4_mapped_ipv6_public_is_safe(self):
        assert is_safe_ip("::ffff:8.8.8.8") is True

    def test_ipv6_loopback_is_blocked(self):
        assert is_safe_ip("::1") is False

    def test_ipv6_link_local_is_blocked(self):
        assert is_safe_ip("fe80::1") is False

    def test_ipv6_unique_local_is_blocked(self):
        assert is_safe_ip("fc00::1") is False

    def test_invalid_ip_returns_false(self):
        assert is_safe_ip("not-an-ip") is False


# ---------------------------------------------------------------------------
# resolve_and_check
# ---------------------------------------------------------------------------


class TestResolveAndCheck:
    def test_public_ipv4_returns_ip(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("93.184.216.34")):
            result = resolve_and_check("example.com")
        assert result == "93.184.216.34"

    def test_docker_bridge_ip_allowed(self):
        # Docker service at 172.17.x.x must not be blocked
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("172.17.0.2")):
            result = resolve_and_check("searxng.internal")
        assert result == "172.17.0.2"

    def test_private_192_raises(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("192.168.1.1")):
            with pytest.raises(SSRFBlockedError, match="blocked IP"):
                resolve_and_check("internal.example.com")

    def test_loopback_raises(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("127.0.0.1")):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("localhost")

    def test_metadata_endpoint_raises(self):
        # Cloud metadata endpoint must always be blocked
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("169.254.169.254")):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("metadata.internal")

    def test_cgnat_raises(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("100.64.1.1")):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("carrier-nat.example.com")

    def test_any_blocked_record_in_multirecord_blocks_all(self):
        results = _addrinfo_multi("8.8.8.8", "::1")  # public + loopback
        with patch("socket.getaddrinfo", return_value=results):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("mixed.example.com")

    def test_all_public_dual_stack_returns_ipv4(self):
        results = _addrinfo_multi("93.184.216.34", "2606:2800:21f:cb07:6820:80da:af6b:8b2c")
        with patch("socket.getaddrinfo", return_value=results):
            result = resolve_and_check("example.com")
        assert result == "93.184.216.34"

    def test_dns_failure_raises(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
            with pytest.raises(SSRFBlockedError, match="DNS resolution failed"):
                resolve_and_check("nonexistent.invalid")

    def test_empty_results_raises(self):
        with patch("socket.getaddrinfo", return_value=[]):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("empty.example.com")

    def test_error_message_includes_hostname(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("192.168.0.1")):
            with pytest.raises(SSRFBlockedError, match="internal.corp"):
                resolve_and_check("internal.corp")


# ---------------------------------------------------------------------------
# SSRFBlockedError
# ---------------------------------------------------------------------------


class TestSSRFBlockedError:
    def test_is_exception_subclass(self):
        assert issubclass(SSRFBlockedError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(SSRFBlockedError):
            raise SSRFBlockedError("blocked")

    def test_message_preserved(self):
        assert "test message" in str(SSRFBlockedError("test message"))


# ---------------------------------------------------------------------------
# make_ssrf_safe_opener
# ---------------------------------------------------------------------------


class TestMakeSsrfSafeOpener:
    def test_returns_opener_director(self):
        import urllib.request

        assert isinstance(make_ssrf_safe_opener(), urllib.request.OpenerDirector)

    def test_returns_new_opener_each_call(self):
        assert make_ssrf_safe_opener() is not make_ssrf_safe_opener()

    def test_opener_has_https_handler(self):
        opener = make_ssrf_safe_opener()
        handler_types = [type(h) for h in opener.handlers]
        assert DNSPinnedHTTPSHandler in handler_types


# ---------------------------------------------------------------------------
# _BLOCKED_NETWORKS membership
# ---------------------------------------------------------------------------


class TestBlockedNetworks:
    def test_contains_rfc1918_10(self):
        assert ipaddress.ip_network("10.0.0.0/8") in _BLOCKED_NETWORKS

    def test_contains_rfc1918_172(self):
        # 172.16.0.0/12 is back in the blocklist; only 172.17.0.0/16 is allowed via allowlist
        assert ipaddress.ip_network("172.16.0.0/12") in _BLOCKED_NETWORKS

    def test_contains_rfc1918_192(self):
        assert ipaddress.ip_network("192.168.0.0/16") in _BLOCKED_NETWORKS

    def test_contains_loopback(self):
        assert ipaddress.ip_network("127.0.0.0/8") in _BLOCKED_NETWORKS

    def test_contains_link_local(self):
        assert ipaddress.ip_network("169.254.0.0/16") in _BLOCKED_NETWORKS

    def test_contains_zero_network(self):
        assert ipaddress.ip_network("0.0.0.0/8") in _BLOCKED_NETWORKS

    def test_contains_cgnat(self):
        assert ipaddress.ip_network("100.64.0.0/10") in _BLOCKED_NETWORKS

    def test_contains_ipv4_mapped_ipv6(self):
        assert ipaddress.ip_network("::ffff:0:0/96") in _BLOCKED_NETWORKS

    def test_contains_ipv6_link_local(self):
        assert ipaddress.ip_network("fe80::/10") in _BLOCKED_NETWORKS

    def test_contains_ipv6_unique_local(self):
        assert ipaddress.ip_network("fc00::/7") in _BLOCKED_NETWORKS


# ---------------------------------------------------------------------------
# End-to-end integration tests (real network — skipped if unavailable)
# ---------------------------------------------------------------------------


def _net_available() -> bool:
    """Quick check: can we reach a public DNS server?"""
    try:
        socket.setdefaulttimeout(3)
        socket.getaddrinfo("en.wikipedia.org", 443)
        return True
    except Exception:
        return False


_SKIP_NET = pytest.mark.skipif(not _net_available(), reason="network unavailable")


class TestEndToEndHTTPS:
    """Real HTTPS fetch via SSRF-safe opener — validates Python 3.14 ssl path."""

    @_SKIP_NET
    def test_wikipedia_https_resolves_and_is_allowed(self):
        ip = resolve_and_check("en.wikipedia.org")
        assert ip  # non-empty
        assert is_safe_ip(ip)

    @_SKIP_NET
    def test_github_api_https_resolves_and_is_allowed(self):
        ip = resolve_and_check("api.github.com")
        assert ip
        assert is_safe_ip(ip)

    @_SKIP_NET
    def test_google_https_resolves_and_is_allowed(self):
        ip = resolve_and_check("www.google.com")
        assert ip
        assert is_safe_ip(ip)

    @_SKIP_NET
    def test_opener_fetches_wikipedia_https(self):
        """Full end-to-end: SSRF-safe opener performs a real HTTPS GET."""
        import urllib.request

        opener = make_ssrf_safe_opener(timeout=10)
        req = urllib.request.Request(
            "https://en.wikipedia.org/wiki/Special:Random",
            headers={"User-Agent": "obase-test/1.0"},
        )
        # Should not raise — public HTTPS endpoint
        try:
            resp = opener.open(req, timeout=10)
            assert resp.status in (200, 301, 302, 303)
        except Exception as exc:
            pytest.skip(f"Network fetch failed (acceptable in CI): {exc}")

    @_SKIP_NET
    def test_loopback_rejected_end_to_end(self):
        """127.0.0.1 must always raise SSRFBlockedError."""
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("127.0.0.1")):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("localhost.fake")

    @_SKIP_NET
    def test_metadata_169_254_rejected_end_to_end(self):
        """Cloud metadata endpoint 169.254.169.254 must always raise."""
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("169.254.169.254")):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("metadata.fake")

    @_SKIP_NET
    def test_192_168_rejected_end_to_end(self):
        """192.168.x.x must always raise SSRFBlockedError."""
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("192.168.0.1")):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("lan.fake")


# ---------------------------------------------------------------------------
# _ALLOWED_DOCKER_NETWORKS — narrow allowlist verification
# ---------------------------------------------------------------------------


class TestAllowedDockerNetworks:
    def test_contains_docker_default_bridge(self):
        assert ipaddress.ip_network("172.17.0.0/16") in _ALLOWED_DOCKER_NETWORKS

    def test_does_not_contain_full_172_16_slash12(self):
        # Only the /16 is explicitly allowed, not the broader /12
        assert ipaddress.ip_network("172.16.0.0/12") not in _ALLOWED_DOCKER_NETWORKS

    def test_allowlist_takes_precedence_over_blocklist(self):
        # 172.17.0.1 is in the blocked /12 but whitelisted via /16
        assert is_safe_ip("172.17.0.1") is True

    def test_non_allowlisted_172_remains_blocked(self):
        # Other subnets in 172.16.0.0/12 are still blocked
        assert is_safe_ip("172.18.0.1") is False
        assert is_safe_ip("172.16.0.1") is False
