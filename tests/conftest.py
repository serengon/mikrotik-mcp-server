"""Shared test fixtures."""

from __future__ import annotations

import pytest

from mikrotik_mcp.config import RouterOSSettings


@pytest.fixture
def mock_settings() -> RouterOSSettings:
    """Settings pointing to a fake router."""
    return RouterOSSettings(
        url="https://router.test/rest",
        user="admin",
        password="",  # type: ignore[arg-type]
        verify_ssl=False,
    )


SAMPLE_SYSTEM_RESOURCE_RAW: dict = {
    "uptime": "3d12h30m15s",
    "version": "7.16 (stable)",
    "cpu-count": "4",
    "cpu-load": "12",
    "cpu-frequency": "1800",
    "free-memory": "805306368",
    "total-memory": "1073741824",
    "free-hdd-space": "134217728",
    "total-hdd-space": "268435456",
    "architecture-name": "arm64",
    "board-name": "hAP ax2",
    "platform": "MikroTik",
}


@pytest.fixture
def sample_system_resource_raw() -> dict:
    """Raw JSON dict as returned by /rest/system/resource."""
    return dict(SAMPLE_SYSTEM_RESOURCE_RAW)


@pytest.fixture
def sample_system_resource() -> dict:
    """Same data, used for model validation tests."""
    return dict(SAMPLE_SYSTEM_RESOURCE_RAW)
