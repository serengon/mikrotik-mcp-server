"""Tests for keyring_store module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestGetPassword:
    def test_returns_password_from_keyring(self) -> None:
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "secret123"
        mock_errors = MagicMock()

        with patch.dict("sys.modules", {"keyring": mock_keyring, "keyring.errors": mock_errors}):
            # Re-import to pick up the mock
            import importlib

            import mikrotik_mcp.keyring_store as ks

            importlib.reload(ks)

            result = ks.get_password("edge-gw")
            assert result == "secret123"
            mock_keyring.get_password.assert_called_once_with("mikrotik-mcp", "edge-gw")

    def test_returns_none_when_no_entry(self) -> None:
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        mock_errors = MagicMock()

        with patch.dict("sys.modules", {"keyring": mock_keyring, "keyring.errors": mock_errors}):
            import importlib

            import mikrotik_mcp.keyring_store as ks

            importlib.reload(ks)

            result = ks.get_password("nonexistent")
            assert result is None

    def test_returns_none_on_keyring_error(self) -> None:
        mock_errors = MagicMock()
        error_class = type("KeyringError", (Exception,), {})
        mock_errors.KeyringError = error_class

        mock_keyring = MagicMock()
        mock_keyring.errors = mock_errors
        mock_keyring.get_password.side_effect = error_class("backend locked")

        with patch.dict("sys.modules", {"keyring": mock_keyring, "keyring.errors": mock_errors}):
            import importlib

            import mikrotik_mcp.keyring_store as ks

            importlib.reload(ks)

            result = ks.get_password("edge-gw")
            assert result is None


class TestSetPassword:
    def test_stores_password(self) -> None:
        mock_keyring = MagicMock()
        mock_errors = MagicMock()

        with patch.dict("sys.modules", {"keyring": mock_keyring, "keyring.errors": mock_errors}):
            import importlib

            import mikrotik_mcp.keyring_store as ks

            importlib.reload(ks)

            ks.set_password("edge-gw", "newpass")
            mock_keyring.set_password.assert_called_once_with(
                "mikrotik-mcp", "edge-gw", "newpass"
            )

    def test_warns_on_keyring_error(self) -> None:
        mock_errors = MagicMock()
        error_class = type("KeyringError", (Exception,), {})
        mock_errors.KeyringError = error_class

        mock_keyring = MagicMock()
        mock_keyring.errors = mock_errors
        mock_keyring.set_password.side_effect = error_class("read-only")

        with patch.dict("sys.modules", {"keyring": mock_keyring, "keyring.errors": mock_errors}):
            import importlib

            import mikrotik_mcp.keyring_store as ks

            importlib.reload(ks)

            # Should not raise
            ks.set_password("edge-gw", "pass")


class TestDeletePassword:
    def test_deletes_password(self) -> None:
        mock_keyring = MagicMock()
        mock_errors = MagicMock()

        with patch.dict("sys.modules", {"keyring": mock_keyring, "keyring.errors": mock_errors}):
            import importlib

            import mikrotik_mcp.keyring_store as ks

            importlib.reload(ks)

            ks.delete_password("edge-gw")
            mock_keyring.delete_password.assert_called_once_with("mikrotik-mcp", "edge-gw")

    def test_warns_on_keyring_error(self) -> None:
        mock_errors = MagicMock()
        error_class = type("KeyringError", (Exception,), {})
        mock_errors.KeyringError = error_class

        mock_keyring = MagicMock()
        mock_keyring.errors = mock_errors
        mock_keyring.delete_password.side_effect = error_class("not found")

        with patch.dict("sys.modules", {"keyring": mock_keyring, "keyring.errors": mock_errors}):
            import importlib

            import mikrotik_mcp.keyring_store as ks

            importlib.reload(ks)

            # Should not raise
            ks.delete_password("edge-gw")


class TestKeyringUnavailable:
    def test_all_functions_graceful_without_keyring(self) -> None:
        """When keyring import fails, all functions degrade gracefully."""
        with patch.dict("sys.modules", {"keyring": None, "keyring.errors": None}):
            import importlib

            import mikrotik_mcp.keyring_store as ks

            importlib.reload(ks)

            assert ks.KEYRING_AVAILABLE is False
            assert ks.get_password("any") is None
            ks.set_password("any", "pass")  # should not raise
            ks.delete_password("any")  # should not raise
