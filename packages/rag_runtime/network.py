"""Resolve once, validate every address and pin the chosen destination for a connection."""

import asyncio
import ipaddress
import socket

from .errors import Problem


async def resolve_host(host, port, allowed):
    if (
        not isinstance(host, str)
        or host.casefold() not in {h.casefold() for h in allowed}
        or any(c in host for c in "/\\,@ \t\r\n")
    ):
        raise Problem("DESTINATION_DENIED", "The destination is not in the owner-configured host allowlist.")
    try:
        async with asyncio.timeout(5):
            addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, TimeoutError):
        raise Problem("DESTINATION_UNAVAILABLE", "The approved host could not be resolved.") from None
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if (
            ip.is_link_local
            or ip.is_unspecified
            or ip.is_multicast
            or str(ip) in {"100.100.100.200", "fd00:ec2::254"}
        ):
            raise Problem(
                "DESTINATION_DENIED", "Metadata, link-local and non-unicast destinations are not permitted."
            )
    if not addresses:
        raise Problem("DESTINATION_UNAVAILABLE", "The approved host has no usable address.")
    return addresses[0][4][0]
