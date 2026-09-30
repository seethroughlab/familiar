"""Who this server is, and where on the local network it can be found (ADR-0134 point 4).

A client pairs with a *server*, not an address. A laptop's address changes with every DHCP lease,
so a client that remembered only `192.168.1.20` would lose its server within days. It remembers
`server_id` instead, and finds the current address again through Bonjour.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import uuid
from dataclasses import dataclass

from app.services.app_settings import get_app_settings_service

_mint_lock = threading.Lock()


@dataclass(frozen=True)
class ServerIdentity:
    server_id: str
    server_name: str


def _host_name() -> str:
    name = socket.gethostname().strip()
    # macOS reports "Studio-MacBook.local". The suffix is mDNS plumbing, not part of the name.
    for suffix in (".local", ".localdomain", ".lan"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    return name or "Familiar"


def get_server_identity() -> ServerIdentity:
    """This server's id, minted and persisted on first call, and its display name."""
    service = get_app_settings_service()
    settings = service.get()
    server_id = settings.server_id
    if not server_id:
        with _mint_lock:
            server_id = service.get().server_id
            if not server_id:
                server_id = str(uuid.uuid4())
                service.update(server_id=server_id)
    return ServerIdentity(server_id=server_id, server_name=settings.server_name or _host_name())


def lan_addresses() -> list[str]:
    """This machine's IPv4 addresses a phone on the same network could reach.

    Loopback and link-local (169.254/16) are left out: neither is reachable from another device. In
    a Docker bridge network these are the container's own addresses, which is why the web admin
    prefers the host it was itself loaded from.
    """
    import psutil

    found: list[str] = []
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family != socket.AF_INET:
                continue
            ip = ipaddress.ip_address(addr.address)
            if ip.is_loopback or ip.is_link_local:
                continue
            if addr.address not in found:
                found.append(addr.address)
    # Private ranges first: a home or office LAN address is the one a phone will reach.
    return sorted(found, key=lambda a: (not ipaddress.ip_address(a).is_private, a))
