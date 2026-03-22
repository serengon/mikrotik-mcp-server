"""Tests for RouterOSClient."""

from __future__ import annotations

import time

import httpx
import pytest

from mikrotik_mcp.client import _CB_COOLDOWN, _CB_FAILURE_THRESHOLD, RouterOSClient
from mikrotik_mcp.config import RouterOSSettings
from mikrotik_mcp.types import (
    RouterOSConnectionError,
    RouterOSError,
    RouterOSPermissionError,
    RouterOSTimeoutError,
    RouterOSUnavailableError,
    SystemResource,
)


@pytest.fixture
def settings() -> RouterOSSettings:
    return RouterOSSettings(
        url="https://router.test/rest",
        user="admin",
        password="",  # type: ignore[arg-type]
        verify_ssl=False,
    )


def _make_response(
    status_code: int = 200,
    json_data: dict | list | None = None,
    text: str = "",
) -> httpx.Response:
    """Build a fake httpx.Response."""
    if json_data is not None:
        content = httpx.Response(
            status_code=status_code,
            json=json_data,
        )
        return content
    return httpx.Response(status_code=status_code, text=text)


# ======================================================================
# String conversion
# ======================================================================


class TestStringConversion:
    def test_true_false(self) -> None:
        assert RouterOSClient._convert_values("true") is True
        assert RouterOSClient._convert_values("True") is True
        assert RouterOSClient._convert_values("false") is False
        assert RouterOSClient._convert_values("FALSE") is False

    def test_integers(self) -> None:
        assert RouterOSClient._convert_values("123") == 123
        assert RouterOSClient._convert_values("0") == 0
        assert RouterOSClient._convert_values("-5") == -5

    def test_preserves_ipv4(self) -> None:
        assert RouterOSClient._convert_values("192.168.1.1") == "192.168.1.1"
        assert RouterOSClient._convert_values("10.0.0.1") == "10.0.0.1"

    def test_preserves_mac(self) -> None:
        assert RouterOSClient._convert_values("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"
        assert RouterOSClient._convert_values("00:11:22:33:44:55") == "00:11:22:33:44:55"

    def test_preserves_uptime(self) -> None:
        assert RouterOSClient._convert_values("3d") == "3d"
        assert RouterOSClient._convert_values("12h") == "12h"
        assert RouterOSClient._convert_values("30m") == "30m"
        assert RouterOSClient._convert_values("15s") == "15s"

    def test_preserves_cidr(self) -> None:
        assert RouterOSClient._convert_values("24/32") == "24/32"

    def test_dict_recursive(self) -> None:
        result = RouterOSClient._convert_values({"enabled": "true", "mtu": "1500"})
        assert result == {"enabled": True, "mtu": 1500}

    def test_list_recursive(self) -> None:
        result = RouterOSClient._convert_values(["true", "42", "hello"])
        assert result == [True, 42, "hello"]

    def test_non_string_passthrough(self) -> None:
        assert RouterOSClient._convert_values(42) == 42
        assert RouterOSClient._convert_values(None) is None


# ======================================================================
# Error reclassification
# ======================================================================


class TestErrorReclassification:
    def test_500_with_permission_message(self) -> None:
        resp = _make_response(500, json_data={"detail": "no permissions"})
        err = RouterOSClient._classify_error(resp)
        assert isinstance(err, RouterOSPermissionError)
        assert err.status_code == 500

    def test_500_generic(self) -> None:
        resp = _make_response(500, json_data={"detail": "internal failure"})
        err = RouterOSClient._classify_error(resp)
        assert isinstance(err, RouterOSError)
        assert not isinstance(err, RouterOSPermissionError)

    def test_401_is_permission_error(self) -> None:
        resp = _make_response(401, json_data={"detail": "unauthorized"})
        err = RouterOSClient._classify_error(resp)
        assert isinstance(err, RouterOSPermissionError)
        assert err.status_code == 401

    def test_404_is_generic_error(self) -> None:
        resp = _make_response(404, json_data={"detail": "not found"})
        err = RouterOSClient._classify_error(resp)
        assert isinstance(err, RouterOSError)
        assert err.status_code == 404


# ======================================================================
# Retry logic
# ======================================================================


class TestRetry:
    async def test_get_retries_on_failure(self, settings: RouterOSSettings) -> None:
        responses = [
            httpx.TimeoutException("timeout 1"),
            httpx.TimeoutException("timeout 2"),
            _make_response(200, json_data={"status": "ok"}),
        ]
        call_count = 0

        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            if isinstance(resp, Exception):
                raise resp
            return resp

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            result = await client.get("/test")
            assert result == {"status": "ok"}
            assert call_count == 3

    async def test_post_does_not_retry(self, settings: RouterOSSettings) -> None:
        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            raise httpx.TimeoutException("timeout")

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            with pytest.raises(RouterOSTimeoutError):
                await client.post("/test", data={"key": "val"})

    async def test_max_retries_exceeded(self, settings: RouterOSSettings) -> None:
        call_count = 0

        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timeout")

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            with pytest.raises(RouterOSTimeoutError):
                await client.get("/test")
            assert call_count == 3  # initial + 2 retries

    async def test_permission_error_not_retried(self, settings: RouterOSSettings) -> None:
        call_count = 0

        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _make_response(401, json_data={"detail": "unauthorized"})

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            with pytest.raises(RouterOSPermissionError):
                await client.get("/test")
            assert call_count == 1


# ======================================================================
# Circuit breaker
# ======================================================================


class TestCircuitBreaker:
    async def test_opens_after_5_failures(self, settings: RouterOSSettings) -> None:
        call_count = 0

        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("refused")

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            # Each GET retries 3 times (1 + 2 retries), each attempt records a failure.
            # After 5 failures the CB opens. First get() records 3 failures
            # (1 + 2 retries), CB stays closed.
            with pytest.raises(RouterOSConnectionError):
                await client.get("/test")
            assert client._cb_state == "closed"
            # Second call: attempt 1 → failure 4, attempt 2 → failure 5 (CB opens),
            # attempt 3 → _cb_check raises Unavailable immediately.
            with pytest.raises(RouterOSUnavailableError):
                await client.get("/test2")
            assert client._cb_state == "open"

    async def test_resets_on_success(self, settings: RouterOSSettings) -> None:
        call_count = 0

        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.ConnectError("refused")
            return _make_response(200, json_data={"ok": "true"})

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            result = await client.get("/test")
            assert result == {"ok": True}
            assert client._cb_state == "closed"
            assert client._cb_failure_count == 0

    async def test_probe_after_cooldown(self, settings: RouterOSSettings) -> None:
        async def failing_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("refused")

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = failing_request  # type: ignore[assignment]

            # Force CB open to isolate probe behavior.
            client._cb_state = "open"
            client._cb_failure_count = _CB_FAILURE_THRESHOLD
            client._cb_last_failure_time = time.monotonic()

            # Simulate cooldown elapsed.
            client._cb_last_failure_time = time.monotonic() - _CB_COOLDOWN - 1

            # Use post (no retry) so the probe behavior is isolated.
            with pytest.raises(RouterOSConnectionError):
                await client.post("/probe")
            # Failed probe → back to open.
            assert client._cb_state == "open"


# ======================================================================
# Rate limiting
# ======================================================================


class TestRateLimiting:
    async def test_serializes_requests(self, settings: RouterOSSettings) -> None:
        timestamps: list[float] = []

        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            timestamps.append(time.monotonic())
            return _make_response(200, json_data={})

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            await client.get("/a")
            await client.get("/b")
            await client.get("/c")

        assert len(timestamps) == 3
        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i - 1]
            assert gap >= 0.04, f"Gap {gap:.3f}s too short between requests {i - 1} and {i}"


# ======================================================================
# Health check
# ======================================================================


class TestHealthCheck:
    async def test_returns_model(
        self, settings: RouterOSSettings, sample_system_resource_raw: dict
    ) -> None:
        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            return _make_response(200, json_data=sample_system_resource_raw)

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            result = await client.health_check()
            assert isinstance(result, SystemResource)
            assert result.version == "7.16 (stable)"
            assert result.board_name == "hAP ax2"

    async def test_fails_on_disconnect(self, settings: RouterOSSettings) -> None:
        async def mock_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("refused")

        async with RouterOSClient(settings) as client:
            assert client._client is not None
            client._client.request = mock_request  # type: ignore[assignment]
            with pytest.raises(RouterOSConnectionError):
                await client.health_check()
