"""MCP tools for RAG-based API discovery and generic REST execution."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import Context

from mikrotik_mcp.api_index import ApiIndex, EndpointInfo
from mikrotik_mcp.types import (
    RouterOSError,
    RouterOSPermissionError,
    RouterOSTimeoutError,
)

_VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


async def search_api(query: str, limit: int = 10, ctx: Context = None) -> str:  # type: ignore[assignment]
    """Search the RouterOS API for endpoints matching a query.

    Use this to discover which REST endpoint to call. Searches by keyword
    across path segments and parameter names. Returns up to `limit` results
    with path, methods, parameters, and available actions.

    Examples:
      - "firewall filter" → finds /ip/firewall/filter
      - "dhcp lease" → finds /ip/dhcp-server/lease
      - "vlan" → finds /interface/vlan
    """
    api_index: ApiIndex = ctx.request_context.lifespan_context["api_index"]
    results = api_index.search(query, limit)

    if not results:
        return f"No endpoints found for '{query}'. Try broader terms or different keywords."

    return _format_results(results)


def _format_results(results: list[EndpointInfo]) -> str:
    """Format search results for LLM consumption."""
    lines: list[str] = []
    for entry in results:
        methods = ", ".join(entry.methods) if entry.methods else "none"
        header = f"{entry.path} [{methods}]"
        if entry.has_id:
            header += " (has /{id})"
        lines.append(header)

        if entry.params:
            display_params = entry.params[:15]
            suffix = f", ... ({len(entry.params)} total)" if len(entry.params) > 15 else ""
            lines.append(f"  Params: {', '.join(display_params)}{suffix}")

        if entry.actions:
            lines.append(f"  Actions: {', '.join(entry.actions)}")

        group_parts = [entry.group] if entry.group else []
        if entry.subgroup:
            group_parts.append(entry.subgroup)
        if group_parts:
            lines.append(f"  Group: {' > '.join(group_parts)}")

        lines.append("")

    return "\n".join(lines).rstrip()


async def routeros_request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Execute a REST API call against the RouterOS device.

    Use search_api first to find the correct endpoint, then call this
    to execute the request.

    Args:
        method: HTTP method (GET, POST, PUT, PATCH, DELETE)
        path: API path (e.g. "/ip/address" or "/rest/ip/address")
        params: Query parameters for GET requests
        body: JSON body for POST/PUT/PATCH requests
    """
    method = method.upper()
    if method not in _VALID_METHODS:
        return f"Error: Invalid method '{method}'. Must be one of: {', '.join(sorted(_VALID_METHODS))}"

    # Normalize path: ensure /rest/ prefix.
    if not path.startswith("/rest"):
        path = "/rest" + (path if path.startswith("/") else f"/{path}")

    client = ctx.request_context.lifespan_context["client"]

    try:
        if method == "GET":
            result = await client.get(path, params=params)
        elif method == "POST":
            result = await client.post(path, data=body)
        elif method == "PUT":
            result = await client.post(path, data=body)
        elif method == "PATCH":
            result = await client.patch(path, data=body)
        elif method == "DELETE":
            result = await client.delete(path)
            warning = "⚠ DELETE executed. "
            if result is None:
                return warning + "Resource deleted successfully (no response body)."
            return warning + json.dumps(result, indent=2, default=str)
    except RouterOSPermissionError as exc:
        return f"Permission denied: {exc.message}\nDetail: {exc.detail or 'none'}"
    except RouterOSTimeoutError as exc:
        return f"Request timed out: {exc.message}\nDetail: {exc.detail or 'none'}"
    except RouterOSError as exc:
        return f"RouterOS error: {exc.message}\nDetail: {exc.detail or 'none'}"

    if result is None:
        return "OK (empty response)"

    return json.dumps(result, indent=2, default=str)
