"""Tests for MCP API tools (search_api and routeros_request)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mikrotik_mcp.api_index import EndpointInfo
from mikrotik_mcp.tools.api_tools import routeros_request, search_api
from mikrotik_mcp.types import (
    RouterOSError,
    RouterOSPermissionError,
    RouterOSTimeoutError,
)


def _make_ctx(
    api_index: Any = None,
    client: Any = None,
) -> MagicMock:
    """Build a mock FastMCP Context with lifespan_context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "api_index": api_index,
        "client": client,
    }
    return ctx


# ------------------------------------------------------------------
# search_api
# ------------------------------------------------------------------


class TestSearchApiTool:
    async def test_returns_formatted_results(self) -> None:
        mock_index = MagicMock()
        mock_index.search.return_value = [
            EndpointInfo(
                path="/ip/address",
                methods=["GET", "PUT"],
                params=["address", "interface", "network"],
                group="ip",
                subgroup="address",
                has_id=True,
                actions=["add", "remove", "set"],
            ),
        ]
        ctx = _make_ctx(api_index=mock_index)

        result = await search_api("ip address", ctx=ctx)

        assert "/ip/address" in result
        assert "GET, PUT" in result
        assert "/{id}" in result
        assert "address" in result
        assert "add, remove, set" in result
        mock_index.search.assert_called_once_with("ip address", 10)

    async def test_no_results_message(self) -> None:
        mock_index = MagicMock()
        mock_index.search.return_value = []
        ctx = _make_ctx(api_index=mock_index)

        result = await search_api("xyznotexist", ctx=ctx)

        assert "No endpoints found" in result

    async def test_passes_limit(self) -> None:
        mock_index = MagicMock()
        mock_index.search.return_value = []
        ctx = _make_ctx(api_index=mock_index)

        await search_api("test", limit=5, ctx=ctx)

        mock_index.search.assert_called_once_with("test", 5)


# ------------------------------------------------------------------
# routeros_request
# ------------------------------------------------------------------


class TestRouterosRequestTool:
    async def test_get_request(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = [{"name": "ether1"}]
        ctx = _make_ctx(client=mock_client)

        result = await routeros_request("GET", "/interface", ctx=ctx)

        mock_client.get.assert_called_once_with("/rest/interface", params=None)
        assert "ether1" in result

    async def test_post_with_body(self) -> None:
        mock_client = AsyncMock()
        mock_client.post.return_value = {"ret": "*1"}
        ctx = _make_ctx(client=mock_client)

        body = {"address": "192.168.1.1/24", "interface": "ether1"}
        result = await routeros_request("POST", "/ip/address", body=body, ctx=ctx)

        mock_client.post.assert_called_once_with("/rest/ip/address", data=body)
        assert "*1" in result

    async def test_patch_request(self) -> None:
        mock_client = AsyncMock()
        mock_client.patch.return_value = {"ret": "ok"}
        ctx = _make_ctx(client=mock_client)

        body = {"comment": "updated"}
        result = await routeros_request("PATCH", "/ip/address/1", body=body, ctx=ctx)

        mock_client.patch.assert_called_once_with("/rest/ip/address/1", data=body)
        assert "ok" in result

    async def test_delete_warning(self) -> None:
        mock_client = AsyncMock()
        mock_client.delete.return_value = None
        ctx = _make_ctx(client=mock_client)

        result = await routeros_request("DELETE", "/ip/address/1", ctx=ctx)

        mock_client.delete.assert_called_once_with("/rest/ip/address/1")
        assert "DELETE" in result
        assert "deleted" in result.lower()

    async def test_path_adds_rest_prefix(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = []
        ctx = _make_ctx(client=mock_client)

        await routeros_request("GET", "/ip/address", ctx=ctx)

        mock_client.get.assert_called_once_with("/rest/ip/address", params=None)

    async def test_path_keeps_rest_prefix(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = []
        ctx = _make_ctx(client=mock_client)

        await routeros_request("GET", "/rest/ip/address", ctx=ctx)

        mock_client.get.assert_called_once_with("/rest/ip/address", params=None)

    async def test_invalid_method(self) -> None:
        ctx = _make_ctx()

        result = await routeros_request("TRACE", "/ip/address", ctx=ctx)

        assert "Invalid method" in result
        assert "TRACE" in result

    async def test_method_case_insensitive(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.return_value = []
        ctx = _make_ctx(client=mock_client)

        await routeros_request("get", "/ip/address", ctx=ctx)

        mock_client.get.assert_called_once()

    async def test_routeros_error_handled(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = RouterOSError(
            "RouterOS error 400: bad request",
            detail="invalid property",
        )
        ctx = _make_ctx(client=mock_client)

        result = await routeros_request("GET", "/ip/address", ctx=ctx)

        assert "RouterOS error" in result
        assert "invalid property" in result

    async def test_permission_error_handled(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = RouterOSPermissionError(
            "Permission denied",
            detail="no permissions for /ip/address",
        )
        ctx = _make_ctx(client=mock_client)

        result = await routeros_request("GET", "/ip/address", ctx=ctx)

        assert "Permission denied" in result

    async def test_timeout_error_handled(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = RouterOSTimeoutError(
            "Request timed out",
            detail="55s timeout exceeded",
        )
        ctx = _make_ctx(client=mock_client)

        result = await routeros_request("GET", "/system/resource", ctx=ctx)

        assert "timed out" in result
