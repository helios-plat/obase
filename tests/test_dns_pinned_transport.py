"""Tests for obase.http.dns_pinned_transport."""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import patch

import pytest

from obase.http.dns_pinned_transport import (
    DNSPinnedHTTPSHandler,
    SSRFBlockedError,
    _BLOCKED_NETWORKS,
    is_safe_ip,
    make_ssrf_safe_opener,
    resolve_and_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _addrinfo_ipv4(ip: str):
    """Build a single-record getaddrinfo result for an IPv4 address."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _addrinfo_ipv6(ip: str):
    """Build a single-record getaddrinfo result for an IPv6 address."""
    return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))]


def _addrinfo_multi(ipv4: str, ipv6: str):
    """Build a dual-stack getaddrinfo result."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ipv4, 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ipv6, 0, 0, 0)),
    ]


# ---------------------------------------------------------------------------
# is_safe_ip — public / private / new ranges
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

    def test_private_172_is_blocked(self):
        assert is_safe_ip("172.16.0.1") is False

    def test_loopback_is_blocked(self):
        assert is_safe_ip("127.0.0.1") is False

    def test_link_local_is_blocked(self):
        assert is_safe_ip("169.254.0.0") is False

    def test_zero_network_is_blocked(self):
        # Fix #2: 0.0.0.0/8 must be blocked
        assert is_safe_ip("0.0.0.1") is False

    def test_cgnat_is_blocked(self):
        # Fix #2: CGNAT 100.64.0.0/10 must be blocked (RFC 6598)
        assert is_safe_ip("100.64.0.1") is False
        assert is_safe_ip("100.127.255.255") is False

    def test_ipv4_mapped_ipv6_private_is_blocked(self):
        # Fix #2: ::ffff:192.168.1.1 must be blocked
        assert is_safe_ip("::ffff:192.168.1.1") is False

    def test_ipv4_mapped_ipv6_public_is_safe(self):
        # ::ffff:8.8.8.8 should pass (maps to a public IP)
        assert is_safe_ip("::ffff:8.8.8.8") is True

    def test_ipv6_loopback_is_blocked(self):
        assert is_safe_ip("::1") is False

    def test_ipv6_link_local_is_blocked(self):
        # Fix #2: fe80::/10 must be blocked
        assert is_safe_ip("fe80::1") is False

    def test_ipv6_unique_local_is_blocked(self):
        assert is_safe_ip("fc00::1") is False

    def test_invalid_ip_returns_false(self):
        assert is_safe_ip("not-an-ip") is False


# ---------------------------------------------------------------------------
# resolve_and_check — uses getaddrinfo, checks ALL records
# ---------------------------------------------------------------------------


class TestResolveAndCheck:
    def test_public_ipv4_returns_ip(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("93.184.216.34")):
            result = resolve_and_check("example.com")
        assert result == "93.184.216.34"

    def test_private_ip_raises(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("192.168.1.1")):
            with pytest.raises(SSRFBlockedError, match="blocked IP"):
                resolve_and_check("internal.example.com")

    def test_loopback_raises(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("127.0.0.1")):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("localhost")

    def test_cgnat_raises(self):
        with patch("socket.getaddrinfo", return_value=_addrinfo_ipv4("100.64.1.1")):
            with pytest.raises(SSRFBlockedError):
                resolve_and_check("carrier-nat.example.com")

    def test_any_private_record_in_multirecord_blocks_all(self):
        # Fix #2: if ANY resolved record is private, the whole request is blocked
        results = _addrinfo_multi("8.8.8.8", "::1")  # one public, one loopback
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
# make_ssrf_safe_opener — covers HTTPS
# ---------------------------------------------------------------------------


class TestMakeSsrfSafeOpener:
    def test_returns_opener_director(self):
        import urllib.request

        assert isinstance(make_ssrf_safe_opener(), urllib.request.OpenerDirector)

    def test_returns_new_opener_each_call(self):
        assert make_ssrf_safe_opener() is not make_ssrf_safe_opener()

    def test_opener_has_https_handler(self):
        # Fix #1: HTTPS must be covered — verify DNSPinnedHTTPSHandler is registered
        opener = make_ssrf_safe_opener()
        handler_types = [type(h) for h in opener.handlers]
        assert DNSPinnedHTTPSHandler in handler_types


# ---------------------------------------------------------------------------
# _BLOCKED_NETWORKS completeness
# ---------------------------------------------------------------------------


class TestBlockedNetworks:
    def test_contains_rfc1918_10(self):
        assert ipaddress.ip_network("10.0.0.0/8") in _BLOCKED_NETWORKS

    def test_contains_rfc1918_172(self):
        assert ipaddress.ip_network("172.16.0.0/12") in _BLOCKED_NETWORKS

    def test_contains_rfc1918_192(self):
        assert ipaddress.ip_network("192.168.0.0/16") in _BLOCKED_NETWORKS

    def test_contains_loopback(self):
        assert ipaddress.ip_network("127.0.0.0/8") in _BLOCKED_NETWORKS

    def test_contains_link_local(self):
        assert ipaddress.ip_network("169.254.0.0/16") in _BLOCKED_NETWORKS

    def test_contains_zero_network(self):
        # Fix #2
        assert ipaddress.ip_network("0.0.0.0/8") in _BLOCKED_NETWORKS

    def test_contains_cgnat(self):
        # Fix #2
        assert ipaddress.ip_network("100.64.0.0/10") in _BLOCKED_NETWORKS

    def test_contains_ipv4_mapped_ipv6(self):
        # Fix #2
        assert ipaddress.ip_network("::ffff:0:0/96") in _BLOCKED_NETWORKS

    def test_contains_ipv6_link_local(self):
        # Fix #2
        assert ipaddress.ip_network("fe80::/10") in _BLOCKED_NETWORKS

    def test_contains_ipv6_unique_local(self):
        assert ipaddress.ip_network("fc00::/7") in _BLOCKED_NETWORKS
