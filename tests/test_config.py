"""Tests for config module."""

from __future__ import annotations

import pytest

from mikrotik_mcp.config import RouterOSSettings


class TestRouterOSSettings:
    def test_load_from_kwargs(self) -> None:
        s = RouterOSSettings(
            url="https://10.0.0.1/rest",
            user="admin",
            password="secret",  # type: ignore[arg-type]
        )
        assert s.url == "https://10.0.0.1/rest"
        assert s.user == "admin"
        assert s.password.get_secret_value() == "secret"
        assert s.verify_ssl is True
        assert s.ca_cert is None

    def test_required_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ROUTEROS_URL", raising=False)
        monkeypatch.delenv("ROUTEROS_USER", raising=False)
        with pytest.raises(ValueError):
            RouterOSSettings()  # type: ignore[call-arg]

    def test_ssl_context_disabled(self) -> None:
        s = RouterOSSettings(
            url="https://r/rest", user="a", password="b", verify_ssl=False  # type: ignore[arg-type]
        )
        assert s.get_ssl_context() is False

    def test_ssl_context_default(self) -> None:
        s = RouterOSSettings(
            url="https://r/rest", user="a", password="b"  # type: ignore[arg-type]
        )
        assert s.get_ssl_context() is True

    def test_ssl_context_custom_ca(self, tmp_path: object) -> None:
        # Create a dummy CA cert file — ssl.create_default_context will fail
        # on invalid content, so we just verify the code path.
        s = RouterOSSettings(
            url="https://r/rest", user="a", password="b",  # type: ignore[arg-type]
            ca_cert="/nonexistent/ca.pem",
        )
        with pytest.raises(OSError):
            s.get_ssl_context()

    def test_load_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROUTEROS_URL", "https://env.test/rest")
        monkeypatch.setenv("ROUTEROS_USER", "envuser")
        monkeypatch.setenv("ROUTEROS_PASSWORD", "envpass")
        monkeypatch.setenv("ROUTEROS_VERIFY_SSL", "false")
        s = RouterOSSettings()  # type: ignore[call-arg]
        assert s.url == "https://env.test/rest"
        assert s.user == "envuser"
        assert s.verify_ssl is False
