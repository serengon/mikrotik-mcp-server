"""FastMCP server entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Context, FastMCP

from mikrotik_mcp.api_index import ApiIndex
from mikrotik_mcp.config import load_router_configs
from mikrotik_mcp.router_registry import RouterRegistry
from mikrotik_mcp.tools.api_tools import list_routers, routeros_request, search_api

logger = logging.getLogger("mikrotik_mcp.server")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Build API index and connect to all configured RouterOS devices."""
    api_index = ApiIndex()
    logger.info("Loaded API index: %d resources from OAS2 spec", api_index.endpoint_count)

    configs = load_router_configs()
    async with RouterRegistry(configs) as registry:
        for info in registry.list_routers():
            logger.info(
                "Router '%s': %s (RouterOS %s)",
                info.name,
                info.board_name or "unknown",
                info.version or "unknown",
            )
        yield {"registry": registry, "api_index": api_index}


mcp = FastMCP(
    "MikroTik MCP Server",
    lifespan=lifespan,
)

# -- Tools -----------------------------------------------------------------
mcp.tool(search_api)
mcp.tool(routeros_request)
mcp.tool(list_routers)


# -- Resources -------------------------------------------------------------
@mcp.resource("router://api-groups")
def api_groups_resource(ctx: Context) -> str:
    """Compact map of all RouterOS API groups and resource counts."""
    return ctx.request_context.lifespan_context["api_index"].get_groups_summary()
