"""Keyring integration for secure credential storage.

Uses the OS keyring (GNOME Keyring / macOS Keychain / Windows Credential Store)
to store router passwords. Falls back gracefully when keyring is unavailable.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("mikrotik_mcp.keyring_store")

SERVICE_NAME = "mikrotik-mcp"

try:
    import keyring
    import keyring.errors

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    logger.debug("keyring package not installed, credential store disabled")


def get_password(router_name: str) -> str | None:
    """Retrieve a router password from the OS keyring.

    Returns None if keyring is unavailable or no entry exists.
    """
    if not KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, router_name)
    except keyring.errors.KeyringError:
        logger.warning("Failed to read from keyring for router '%s'", router_name)
        return None


def set_password(router_name: str, password: str) -> None:
    """Store a router password in the OS keyring."""
    if not KEYRING_AVAILABLE:
        logger.warning("keyring not available, cannot store password")
        return
    try:
        keyring.set_password(SERVICE_NAME, router_name, password)
    except keyring.errors.KeyringError:
        logger.warning("Failed to store password in keyring for router '%s'", router_name)


def delete_password(router_name: str) -> None:
    """Remove a router password from the OS keyring."""
    if not KEYRING_AVAILABLE:
        return
    try:
        keyring.delete_password(SERVICE_NAME, router_name)
    except keyring.errors.KeyringError:
        logger.warning("Failed to delete keyring entry for router '%s'", router_name)
