"""Integration tests requiring a running RouterOS instance (Docker CHR)."""

from __future__ import annotations

import pytest

from mikrotik_mcp.client import RouterOSClient
from mikrotik_mcp.config import RouterOSSettings
from mikrotik_mcp.types import SystemResource


@pytest.fixture
def integration_settings() -> RouterOSSettings:
    """Settings for Docker CHR at localhost:8443."""
    return RouterOSSettings(
        url="https://localhost:8443/rest",
        user="admin",
        password="",  # type: ignore[arg-type]
        verify_ssl=False,
    )


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
