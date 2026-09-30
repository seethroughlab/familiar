"""Advertise this server on the local network as `_familiar._tcp` (ADR-0134 point 4).

A phone's setup screen lists what it finds here, and a paired phone finds its server again here when
the address it stored has changed. The TXT record carries the `server_id` the phone remembers, a name
to show, and the API contract version (ADR-0113), so an incompatible server can be labelled before it
is chosen. **It never carries the token.** Anything on the network can read an mDNS record.

Only runs when `settings.advertise_port` is set, which `python -m app.serve` does when it binds
beyond loopback. In Docker's bridge network the announcement would not reach the LAN, and the port
would be the container's rather than the host's.
"""

from __future__ import annotations

import logging
import socket
from typing import TYPE_CHECKING

from app.config import API_CONTRACT_VERSION

if TYPE_CHECKING:
    from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_familiar._tcp.local."


def txt_record(server_id: str, server_name: str) -> dict[str, str]:
    """The properties a client can read before connecting. Never add the token here."""
    return {"id": server_id, "name": server_name, "contract": str(API_CONTRACT_VERSION)}


class Advertiser:
    """Registers one `_familiar._tcp` service for the lifetime of the app."""

    def __init__(self) -> None:
        self._zeroconf: AsyncZeroconf | None = None
        self._info: AsyncServiceInfo | None = None

    async def start(self, port: int) -> None:
        from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

        from app.services.server_identity import get_server_identity, lan_addresses

        identity = get_server_identity()
        addresses = lan_addresses()
        if not addresses:
            logger.warning("Not advertising _familiar._tcp: no LAN address found")
            return
        # The instance name is what Bonjour browsers display, and it must be unique on the network;
        # zeroconf renames on a collision, so two Macs called "Studio" still both appear.
        info = AsyncServiceInfo(
            SERVICE_TYPE,
            f"{identity.server_name}.{SERVICE_TYPE}",
            port=port,
            addresses=[socket.inet_aton(a) for a in addresses],
            properties=txt_record(identity.server_id, identity.server_name),
            server=f"{socket.gethostname().split('.')[0]}.local.",
        )
        zc = AsyncZeroconf()
        await zc.async_register_service(info, allow_name_change=True)
        self._zeroconf, self._info = zc, info
        logger.info("Advertising %s on %s port %d", info.name, ", ".join(addresses), port)

    async def stop(self) -> None:
        if self._zeroconf is None:
            return
        try:
            if self._info is not None:
                await self._zeroconf.async_unregister_service(self._info)
        finally:
            await self._zeroconf.async_close()
            self._zeroconf = None
            self._info = None
