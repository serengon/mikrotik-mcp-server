"""FastMCP server entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from mikrotik_mcp.client import RouterOSClient
from mikrotik_mcp.config import get_settings

logger = logging.getLogger("mikrotik_mcp.server")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Create and destroy the RouterOS client on server start/stop."""
    settings = get_settings()
    async with RouterOSClient(settings) as client:
        info = await client.health_check()
        logger.info(
            "Connected to %s running RouterOS %s",
            info.board_name,
            info.version,
        )
        yield {"client": client}


mcp = FastMCP(
    "MikroTik MCP Server",
    lifespan=lifespan,
)
