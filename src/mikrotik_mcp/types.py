"""Error hierarchy and Pydantic models for RouterOS responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class RouterOSError(Exception):
    """Base exception for RouterOS API errors."""

    def __init__(
        self,
        message: str,
        *,
        detail: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(message)


class RouterOSPermissionError(RouterOSError):
    """Permission denied — reclassified from HTTP 500 or 401."""


class RouterOSTimeoutError(RouterOSError):
    """Request timed out."""


class RouterOSConnectionError(RouterOSError):
    """Could not connect to the RouterOS device."""


class RouterOSUnavailableError(RouterOSError):
    """Circuit breaker is open — device considered unavailable."""


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SystemResource(BaseModel):
    """Parsed response from GET /rest/system/resource.

    RouterOS returns hyphenated keys; Field aliases handle the mapping.
    """

    uptime: str = Field(alias="uptime")
    version: str = Field(alias="version")
    cpu_count: str = Field(alias="cpu-count")
    cpu_load: str = Field(alias="cpu-load")
    cpu_frequency: str = Field(alias="cpu-frequency")
    free_memory: str = Field(alias="free-memory")
    total_memory: str = Field(alias="total-memory")
    free_hdd_space: str = Field(alias="free-hdd-space")
    total_hdd_space: str = Field(alias="total-hdd-space")
    architecture_name: str = Field(alias="architecture-name")
    board_name: str = Field(alias="board-name")
    platform: str = Field(alias="platform")

    model_config = {"populate_by_name": True}
