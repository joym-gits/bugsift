"""SSRF-safe URL validation.

Any outbound HTTP request that takes a user-supplied URL — today the
Jira ``site_url`` — passes through :func:`assert_safe_public_url`. The
function refuses URLs whose hostnames resolve to private, loopback,
link-local, multicast, or unspecified addresses, so an authenticated
dashboard user can't turn the backend into an oracle for the
compose-internal services (Postgres, Redis, the cloud metadata IMDS
endpoint, etc.).

The check is best-effort — DNS can be re-bound after resolution in
principle — but combined with HTTPS-only enforcement and the fact that
the backend never follows redirects on these calls, it closes the
realistic exploitation paths.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when the URL points at a non-public destination."""


_DEFAULT_BLOCKED_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + AWS IMDS
    ipaddress.ip_network("100.64.0.0/10"),   # CGNAT
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),     # multicast
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),         # unique-local
    ipaddress.ip_network("fe80::/10"),        # link-local v6
    ipaddress.ip_network("ff00::/8"),         # multicast v6
]


def _is_private(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # not a parseable IP — treat as unsafe
    return any(ip in net for net in _DEFAULT_BLOCKED_NETS) or ip.is_unspecified


def assert_safe_public_url(url: str, *, require_https: bool = True) -> None:
    """Validate that ``url`` points at a public host over HTTP(S).

    Raises :class:`UnsafeUrlError` on any of:
      - missing/unsupported scheme;
      - ``require_https`` and scheme is not ``https``;
      - hostname is an IP literal or resolves to a private/loopback/
        link-local/multicast/CGNAT address.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UnsafeUrlError("URL must use http or https.")
    if require_https and scheme != "https":
        raise UnsafeUrlError("URL must use https.")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("URL is missing a hostname.")
    # Reject IP literals outright — legitimate Jira sites are DNS names.
    try:
        ipaddress.ip_address(host)
        raise UnsafeUrlError("URL must use a hostname, not an IP literal.")
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"Could not resolve host '{host}'.") from e
    if not infos:
        raise UnsafeUrlError(f"Could not resolve host '{host}'.")
    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        if _is_private(addr):
            raise UnsafeUrlError(
                f"Host '{host}' resolves to a non-public address."
            )
