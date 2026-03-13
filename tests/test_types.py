"""Tests for types module."""

from __future__ import annotations

from mikrotik_mcp.types import (
    RouterOSConnectionError,
    RouterOSError,
    RouterOSPermissionError,
    RouterOSTimeoutError,
    RouterOSUnavailableError,
    SystemResource,
)


class TestErrorHierarchy:
    def test_base_error_fields(self) -> None:
        err = RouterOSError("fail", detail="d", status_code=500)
        assert err.message == "fail"
        assert err.detail == "d"
        assert err.status_code == 500
        assert str(err) == "fail"

    def test_permission_is_routeros_error(self) -> None:
        assert issubclass(RouterOSPermissionError, RouterOSError)

    def test_timeout_is_routeros_error(self) -> None:
        assert issubclass(RouterOSTimeoutError, RouterOSError)

    def test_connection_is_routeros_error(self) -> None:
        assert issubclass(RouterOSConnectionError, RouterOSError)

    def test_unavailable_is_routeros_error(self) -> None:
        assert issubclass(RouterOSUnavailableError, RouterOSError)


class TestSystemResource:
    def test_parse_with_aliases(self, sample_system_resource: dict) -> None:
        res = SystemResource.model_validate(sample_system_resource)
        assert res.version == "7.16 (stable)"
        assert res.cpu_count == 4
        assert res.board_name == "hAP ax2"
        assert res.uptime == "3d12h30m15s"

    def test_populate_by_name(self) -> None:
        res = SystemResource(
            uptime="1h",
            version="7.16",
            cpu_count="1",
            cpu_load="0",
            cpu_frequency="800",
            free_memory="100",
            total_memory="200",
            free_hdd_space="50",
            total_hdd_space="100",
            architecture_name="x86",
            board_name="CHR",
            platform="MikroTik",
        )
        assert res.board_name == "CHR"
