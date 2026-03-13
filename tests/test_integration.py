"""Integration tests requiring a running RouterOS instance (Docker CHR)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mikrotik_mcp.api_index import ApiIndex
from mikrotik_mcp.client import RouterOSClient
from mikrotik_mcp.config import RouterOSSettings
from mikrotik_mcp.tools.api_tools import routeros_request, search_api
from mikrotik_mcp.types import SystemResource


@pytest.fixture
def integration_settings() -> RouterOSSettings:
    """Settings for Docker CHR at localhost:8080."""
    return RouterOSSettings(
        url="http://localhost:8080",
        user="admin",
        password="",  # type: ignore[arg-type]
        verify_ssl=False,
    )


def _integration_ctx(client: RouterOSClient, api_index: ApiIndex) -> MagicMock:
    """Build a mock Context backed by real client and index."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "client": client,
        "api_index": api_index,
    }
    return ctx


@pytest.mark.integration
class TestDockerCHR:
    async def test_health_check(self, integration_settings: RouterOSSettings) -> None:
        async with RouterOSClient(integration_settings) as client:
            result = await client.health_check()
            assert isinstance(result, SystemResource)
            assert "7." in result.version

    async def test_get_interfaces(self, integration_settings: RouterOSSettings) -> None:
        async with RouterOSClient(integration_settings) as client:
            interfaces = await client.get("/rest/interface")
            assert isinstance(interfaces, list)
            assert len(interfaces) > 0


@pytest.mark.integration
class TestToolIntegration:
    async def test_search_and_execute(self, integration_settings: RouterOSSettings) -> None:
        api_index = ApiIndex()
        async with RouterOSClient(integration_settings) as client:
            ctx = _integration_ctx(client, api_index)

            # Search for the endpoint.
            search_result = await search_api("system resource", ctx=ctx)
            assert "/system/resource" in search_result

            # Execute the request.
            response = await routeros_request("GET", "/system/resource", ctx=ctx)
            assert "version" in response
            assert "uptime" in response

    async def test_get_interfaces_via_generic(
        self, integration_settings: RouterOSSettings
    ) -> None:
        api_index = ApiIndex()
        async with RouterOSClient(integration_settings) as client:
            ctx = _integration_ctx(client, api_index)
            response = await routeros_request("GET", "/rest/interface", ctx=ctx)
            assert "name" in response
