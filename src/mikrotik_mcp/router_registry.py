"""Registry for managing multiple named RouterOS clients."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import TracebackType

from mikrotik_mcp.client import RouterOSClient
from mikrotik_mcp.config import RouterOSSettings

logger = logging.getLogger("mikrotik_mcp.router_registry")


@dataclass
class RouterInfo:
    """Public info about a registered router."""

    name: str
    url: str
    version: str | None = None
    board_name: str | None = None


class RouterRegistry:
    """Manages multiple named RouterOSClient instances.

    Usage::

        configs = {"edge-gw": settings1, "core-sw": settings2}
        async with RouterRegistry(configs) as registry:
            client = registry.get_client("edge-gw")
            data = await client.get("/rest/system/identity")
    """

    def __init__(self, configs: dict[str, RouterOSSettings]) -> None:
        if not configs:
            raise ValueError("At least one router configuration is required")
        self._configs = configs
        self._clients: dict[str, RouterOSClient] = {}
        self._info: dict[str, RouterInfo] = {}

    async def __aenter__(self) -> RouterRegistry:
        """Connect all clients and run health checks."""
        for name, settings in self._configs.items():
            client = RouterOSClient(settings)
            await client.__aenter__()
            self._clients[name] = client

            try:
                resource = await client.health_check()
                self._info[name] = RouterInfo(
                    name=name,
                    url=settings.url,
                    version=resource.version,
                    board_name=resource.board_name,
                )
                logger.info(
                    "Connected to %s (%s) running RouterOS %s",
                    name,
                    resource.board_name,
                    resource.version,
                )
            except Exception as exc:
                logger.warning("Health check failed for %s: %s", name, exc)
                self._info[name] = RouterInfo(name=name, url=settings.url)

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close all clients."""
        for name, client in self._clients.items():
            try:
                await client.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning("Error closing client %s: %s", name, exc)
        self._clients.clear()
        self._info.clear()

    def get_client(self, name: str) -> RouterOSClient:
        """Get a client by router name. Raises ValueError if not found."""
        if name not in self._clients:
            available = ", ".join(sorted(self._clients.keys()))
            raise ValueError(
                f"Unknown router '{name}'. Available routers: {available}"
            )
        return self._clients[name]

    def list_routers(self) -> list[RouterInfo]:
        """Return info for all registered routers."""
        return list(self._info.values())

    @property
    def is_single_router(self) -> bool:
        """True if only one router is configured."""
        return len(self._clients) == 1

    @property
    def default_client(self) -> RouterOSClient:
        """Return the only client. Raises ValueError if multiple routers exist."""
        if not self.is_single_router:
            available = ", ".join(sorted(self._clients.keys()))
            raise ValueError(
                f"Multiple routers configured ({available}). "
                "Specify which router to use."
            )
        return next(iter(self._clients.values()))

    @property
    def router_names(self) -> list[str]:
        """Return sorted list of router names."""
        return sorted(self._clients.keys())
