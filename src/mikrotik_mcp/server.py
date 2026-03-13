"""FastMCP server entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Context, FastMCP

from mikrotik_mcp.api_index import ApiIndex
from mikrotik_mcp.client import RouterOSClient
from mikrotik_mcp.config import get_settings
from mikrotik_mcp.tools.api_tools import routeros_request, search_api

logger = logging.getLogger("mikrotik_mcp.server")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Build API index and connect to the RouterOS device."""
    api_index = ApiIndex()
    logger.info("Loaded API index: %d resources from OAS2 spec", api_index.endpoint_count)

    settings = get_settings()
    async with RouterOSClient(settings) as client:
        info = await client.health_check()
        logger.info(
            "Connected to %s running RouterOS %s",
            info.board_name,
            info.version,
        )
        yield {"client": client, "api_index": api_index}


mcp = FastMCP(
    "MikroTik MCP Server",
    lifespan=lifespan,
)

# -- Tools -----------------------------------------------------------------
mcp.tool(search_api)
mcp.tool(routeros_request)


# -- Resources -------------------------------------------------------------
@mcp.resource("router://api-groups")
def api_groups_resource(ctx: Context) -> str:
    """Compact map of all RouterOS API groups and resource counts."""
    return ctx.request_context.lifespan_context["api_index"].get_groups_summary()
