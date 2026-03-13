"""Tests for RouterRegistry multi-router management."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mikrotik_mcp.config import RouterOSSettings
from mikrotik_mcp.router_registry import RouterRegistry
from mikrotik_mcp.types import SystemResource

from .conftest import SAMPLE_SYSTEM_RESOURCE_RAW


def _make_settings(url: str = "http://router.test") -> RouterOSSettings:
    return RouterOSSettings(
        url=url, user="admin", password="", verify_ssl=False  # type: ignore[arg-type]
    )


def _make_system_resource() -> SystemResource:
    return SystemResource.model_validate(SAMPLE_SYSTEM_RESOURCE_RAW)


class TestRouterRegistrySingleRouter:
    async def test_is_single_router(self) -> None:
        configs = {"default": _make_settings()}
        with patch("mikrotik_mcp.router_registry.RouterOSClient") as MockClient:
            instance = AsyncMock()
            instance.health_check.return_value = _make_system_resource()
            MockClient.return_value = instance

            async with RouterRegistry(configs) as registry:
                assert registry.is_single_router is True

    async def test_default_client(self) -> None:
        configs = {"default": _make_settings()}
        with patch("mikrotik_mcp.router_registry.RouterOSClient") as MockClient:
            instance = AsyncMock()
            instance.health_check.return_value = _make_system_resource()
            MockClient.return_value = instance

            async with RouterRegistry(configs) as registry:
                client = registry.default_client
                assert client is instance


class TestRouterRegistryMultiRouter:
    async def test_get_client_by_name(self) -> None:
        configs = {
            "edge-gw": _make_settings("http://172.16.0.1"),
            "core-sw": _make_settings("http://172.16.0.2"),
        }
        with patch("mikrotik_mcp.router_registry.RouterOSClient") as MockClient:
            instances = {}
            def make_client(settings):
                inst = AsyncMock()
                inst.health_check.return_value = _make_system_resource()
                instances[settings.url] = inst
                return inst
            MockClient.side_effect = make_client

            async with RouterRegistry(configs) as registry:
                assert registry.is_single_router is False
                client1 = registry.get_client("edge-gw")
                client2 = registry.get_client("core-sw")
                assert client1 is instances["http://172.16.0.1"]
                assert client2 is instances["http://172.16.0.2"]

    async def test_unknown_router_raises_with_available_list(self) -> None:
        configs = {
            "edge-gw": _make_settings("http://172.16.0.1"),
            "fw-01": _make_settings("http://172.16.0.3"),
        }
        with patch("mikrotik_mcp.router_registry.RouterOSClient") as MockClient:
            instance = AsyncMock()
            instance.health_check.return_value = _make_system_resource()
            MockClient.return_value = instance

            async with RouterRegistry(configs) as registry:
                with pytest.raises(ValueError, match="Unknown router 'bogus'"):
                    registry.get_client("bogus")
                with pytest.raises(ValueError, match="edge-gw"):
                    registry.get_client("bogus")

    async def test_default_client_raises_for_multi(self) -> None:
        configs = {
            "edge-gw": _make_settings("http://172.16.0.1"),
            "core-sw": _make_settings("http://172.16.0.2"),
        }
        with patch("mikrotik_mcp.router_registry.RouterOSClient") as MockClient:
            instance = AsyncMock()
            instance.health_check.return_value = _make_system_resource()
            MockClient.return_value = instance

            async with RouterRegistry(configs) as registry:
                with pytest.raises(ValueError, match="Multiple routers"):
                    _ = registry.default_client

    async def test_list_routers(self) -> None:
        configs = {
            "edge-gw": _make_settings("http://172.16.0.1"),
            "core-sw": _make_settings("http://172.16.0.2"),
        }
        with patch("mikrotik_mcp.router_registry.RouterOSClient") as MockClient:
            instance = AsyncMock()
            instance.health_check.return_value = _make_system_resource()
            MockClient.return_value = instance

            async with RouterRegistry(configs) as registry:
                routers = registry.list_routers()
                assert len(routers) == 2
                names = {r.name for r in routers}
                assert names == {"edge-gw", "core-sw"}
                for r in routers:
                    assert r.version == "7.16 (stable)"

    async def test_router_names_sorted(self) -> None:
        configs = {
            "wifi-ctrl": _make_settings(),
            "edge-gw": _make_settings(),
            "core-sw": _make_settings(),
        }
        with patch("mikrotik_mcp.router_registry.RouterOSClient") as MockClient:
            instance = AsyncMock()
            instance.health_check.return_value = _make_system_resource()
            MockClient.return_value = instance

            async with RouterRegistry(configs) as registry:
                assert registry.router_names == ["core-sw", "edge-gw", "wifi-ctrl"]


class TestRouterRegistryEdgeCases:
    def test_empty_configs_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            RouterRegistry({})

    async def test_health_check_failure_still_registers(self) -> None:
        configs = {"broken": _make_settings()}
        with patch("mikrotik_mcp.router_registry.RouterOSClient") as MockClient:
            instance = AsyncMock()
            instance.health_check.side_effect = Exception("connection refused")
            MockClient.return_value = instance

            async with RouterRegistry(configs) as registry:
                assert len(registry.list_routers()) == 1
                info = registry.list_routers()[0]
                assert info.name == "broken"
                assert info.version is None
