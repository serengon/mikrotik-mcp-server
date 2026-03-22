"""RouterOS REST API client with quirks handling."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from types import TracebackType
from typing import Any

import httpx

from mikrotik_mcp.config import RouterOSSettings
from mikrotik_mcp.types import (
    RouterOSConnectionError,
    RouterOSError,
    RouterOSPermissionError,
    RouterOSTimeoutError,
    RouterOSUnavailableError,
    SystemResource,
)

logger = logging.getLogger("mikrotik_mcp.client")

# Patterns that look numeric but must stay as strings.
_PRESERVE_PATTERNS = re.compile(
    r"^("
    r"\d+\.\d+\.\d+\.\d+"  # IPv4
    r"|[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}"  # MAC
    r"|\d+[dhms]"  # uptime fragments like "3d12h"
    r"|\d+/\d+"  # CIDR or slot/port
    r")$"
)

# Circuit breaker states.
_CB_CLOSED = "closed"
_CB_OPEN = "open"
_CB_HALF_OPEN = "half-open"

_MAX_RETRIES = 2
_RETRY_BACKOFFS = (1.0, 3.0)
_CB_FAILURE_THRESHOLD = 5
_CB_COOLDOWN = 15.0
_RATE_LIMIT_GAP = 0.05  # 50ms between requests


class RouterOSClient:
    """Async HTTP client for the RouterOS v7 REST API.

    Encapsulates quirks: Content-Type handling, string→native conversion,
    error reclassification, rate limiting, retry, and circuit breaker.

    Usage::

        async with RouterOSClient(settings) as client:
            data = await client.get("/interface")
    """

    def __init__(self, settings: RouterOSSettings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

        # Rate limiting.
        self._semaphore = asyncio.Semaphore(4)
        self._last_request_time: float = 0.0

        # Circuit breaker.
        self._cb_state = _CB_CLOSED
        self._cb_failure_count = 0
        self._cb_last_failure_time: float = 0.0

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> RouterOSClient:
        verify = self._settings.get_ssl_context()
        self._client = httpx.AsyncClient(
            base_url=self._settings.url,
            auth=httpx.BasicAuth(
                self._settings.user,
                self._settings.password.get_secret_value(),
            ),
            verify=verify,
            timeout=httpx.Timeout(55.0),
            headers={"Content-Type": "application/json"},
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(
        self, path: str, params: dict[str, str] | None = None
    ) -> Any:
        """GET with retry (max 2 retries, backoff 1s/3s)."""
        return await self._request_with_retry("GET", path, params=params)

    async def post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        """POST — never retried."""
        return await self._request("POST", path, data=data)

    async def put(self, path: str, data: dict[str, Any] | None = None) -> Any:
        """PUT — never retried. Used to create resources in RouterOS REST API."""
        return await self._request("PUT", path, data=data)

    async def patch(self, path: str, data: dict[str, Any] | None = None) -> Any:
        """PATCH — never retried."""
        return await self._request("PATCH", path, data=data)

    async def delete(self, path: str) -> Any:
        """DELETE — never retried."""
        return await self._request("DELETE", path)

    async def health_check(self) -> SystemResource:
        """Probe the router and return parsed system resource info."""
        data = await self.get("/rest/system/resource")
        return SystemResource.model_validate(data)

    # ------------------------------------------------------------------
    # String conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_values(data: Any) -> Any:
        """Recursively convert RouterOS string values to native Python types.

        Rules:
        - "true"/"false" → bool
        - Numeric strings → int (unless they match IP/MAC/uptime/CIDR patterns)
        - Everything else stays as-is
        """
        if isinstance(data, dict):
            return {k: RouterOSClient._convert_values(v) for k, v in data.items()}
        if isinstance(data, list):
            return [RouterOSClient._convert_values(item) for item in data]
        if isinstance(data, str):
            lower = data.lower()
            if lower == "true":
                return True
            if lower == "false":
                return False
            if _PRESERVE_PATTERNS.match(data):
                return data
            try:
                return int(data)
            except ValueError:
                return data
        return data

    # ------------------------------------------------------------------
    # Error reclassification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_error(response: httpx.Response) -> RouterOSError:
        """Turn an HTTP error response into the appropriate exception."""
        status = response.status_code
        try:
            body = response.json()
        except Exception:
            body = {}

        detail = body.get("detail", body.get("message", response.text))
        msg = f"RouterOS error {status}: {detail}"

        # RouterOS returns 500 for permission errors.
        if status == 500:
            detail_lower = str(detail).lower()
            if "no permissions" in detail_lower or "permission" in detail_lower:
                return RouterOSPermissionError(msg, detail=detail, status_code=status)

        if status == 401:
            return RouterOSPermissionError(msg, detail=detail, status_code=status)

        return RouterOSError(msg, detail=detail, status_code=status)

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def _cb_check(self) -> None:
        """Raise if the circuit breaker is open (unless cooldown elapsed)."""
        if self._cb_state == _CB_OPEN:
            elapsed = time.monotonic() - self._cb_last_failure_time
            if elapsed < _CB_COOLDOWN:
                raise RouterOSUnavailableError(
                    "Circuit breaker open — device unavailable",
                    detail=f"Cooldown remaining: {_CB_COOLDOWN - elapsed:.0f}s",
                )
            # Cooldown elapsed → allow a probe.
            self._cb_state = _CB_HALF_OPEN
            logger.info("Circuit breaker half-open, allowing probe request")

    def _cb_record_success(self) -> None:
        if self._cb_state != _CB_CLOSED:
            logger.info("Circuit breaker reset to closed")
        self._cb_state = _CB_CLOSED
        self._cb_failure_count = 0

    def _cb_record_failure(self) -> None:
        self._cb_failure_count += 1
        self._cb_last_failure_time = time.monotonic()
        if self._cb_failure_count >= _CB_FAILURE_THRESHOLD:
            self._cb_state = _CB_OPEN
            logger.error(
                "Circuit breaker opened after %d consecutive failures",
                self._cb_failure_count,
            )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _rate_limit(self) -> None:
        """Ensure at least 100ms between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < _RATE_LIMIT_GAP:
            await asyncio.sleep(_RATE_LIMIT_GAP - elapsed)
        self._last_request_time = time.monotonic()

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """Send a single request through the rate limiter and circuit breaker."""
        assert self._client is not None, "Client not initialized — use async with"

        self._cb_check()

        async with self._semaphore:
            await self._rate_limit()

            kwargs: dict[str, Any] = {"params": params}

            # Quirk: use raw bytes to avoid httpx adding charset to Content-Type.
            if data is not None:
                kwargs["content"] = json.dumps(data).encode()

            logger.debug("%s %s params=%s data=%s", method, path, params, data)

            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as exc:
                self._cb_record_failure()
                raise RouterOSTimeoutError(
                    f"Request timed out: {method} {path}",
                    detail=str(exc),
                ) from exc
            except httpx.ConnectError as exc:
                self._cb_record_failure()
                raise RouterOSConnectionError(
                    f"Connection failed: {method} {path}",
                    detail=str(exc),
                ) from exc

        logger.debug("Response %d (%d bytes)", response.status_code, len(response.content))

        if response.status_code >= 400:
            self._cb_record_failure()
            raise self._classify_error(response)

        self._cb_record_success()

        if not response.content:
            return None

        result = response.json()
        return self._convert_values(result)

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        """GET with retries — backoff 1s, 3s. Only for read operations."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return await self._request(method, path, params=params)
            except RouterOSUnavailableError:
                raise
            except (RouterOSTimeoutError, RouterOSConnectionError, RouterOSError) as exc:
                last_exc = exc
                # Don't retry permission errors.
                if isinstance(exc, RouterOSPermissionError):
                    raise
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_BACKOFFS[attempt]
                    logger.warning(
                        "Retry %d/%d for %s %s after %.1fs: %s",
                        attempt + 1,
                        _MAX_RETRIES,
                        method,
                        path,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]
