"""SSRF protection applied before every navigation (ADR 0004).

The external Playwright Server does no validation of its own (ADR 0001) and sits on an
internal network with reach to routers, other containers, and the cloud metadata
endpoint. Since the integration is the only thing driving it, the guard lives here: every
LLM-chosen target hostname is resolved and refused if it maps to a private range —
checked *after* resolution so a benign hostname that resolves to a private IP (DNS
rebinding) is still caught.

``_resolve`` is the DNS seam, mirroring how :mod:`render` fakes ``async_playwright``:
tests patch it to inject IPs (and simulate rebinding) so no real DNS is ever hit.

The user's configured SearXNG and Playwright endpoints are exempt as trusted config —
they are categorically different from an untrusted, LLM-chosen URL (ADR 0004).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from urllib.parse import urlsplit

_LOGGER = logging.getLogger(__name__)


def trusted_hosts(*urls: str) -> frozenset[str]:
    """Extract hostnames from configured endpoint URLs for exemption checks."""
    hosts: set[str] = set()
    for url in urls:
        if not url:
            continue
        host = urlsplit(url).hostname
        if host:
            hosts.add(host)
    return frozenset(hosts)


def _is_blocked_ip(ip_str: str) -> bool:
    """Return True if ``ip_str`` falls in a range we refuse to navigate to."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # Unparseable address: treat as blocked rather than risk navigating.
        return True

    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) so the checks below see the
    # real IPv4 address instead of a global-looking v6 wrapper.
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped

    # is_private already covers RFC1918 + IPv6 ULA; the rest are spelled out to document
    # the ADR ranges (link-local incl. 169.254.169.254, loopback, etc.).
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolve(host: str) -> list[str]:
    """Resolve ``host`` to a list of IP strings (the DNS seam; patched in tests)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None)
    # getaddrinfo entries are (family, type, proto, canonname, sockaddr); the IP is the
    # first element of sockaddr for both IPv4 and IPv6.
    return [info[4][0] for info in infos]


async def async_check_target(url: str, trusted: frozenset[str]) -> str | None:
    """Return None if ``url`` is safe to navigate to, else a short refusal reason."""
    host = urlsplit(url).hostname
    if not host:
        return f"blocked: no host in URL {url!r}"

    if host in trusted:
        # Trusted config endpoint: exempt, skip resolution (ADR 0004).
        return None

    try:
        ips = await _resolve(host)
    except OSError as err:
        return f"blocked: could not resolve {host!r}: {err}"

    if not ips:
        return f"blocked: {host!r} resolved to no addresses"

    for ip in ips:
        if _is_blocked_ip(ip):
            _LOGGER.debug("Refusing SSRF target %s (resolved %s → %s)", url, host, ip)
            return f"blocked: {host!r} resolves to non-public address {ip}"

    return None
