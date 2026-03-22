"""Tests for config module."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from mikrotik_mcp.config import RouterOSSettings, load_router_configs


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


class TestLoadRouterConfigs:
    def test_load_from_json_file(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_file = tmp_path / "routers.json"
        config_file.write_text(json.dumps({
            "routers": {
                "edge-gw": {"url": "http://172.16.0.1", "user": "admin", "password": ""},
                "core-sw": {"url": "http://172.16.0.2", "user": "admin", "verify_ssl": False},
            }
        }))
        monkeypatch.setenv("ROUTEROS_CONFIG", str(config_file))
        monkeypatch.delenv("ROUTEROS_URL", raising=False)

        configs = load_router_configs()

        assert len(configs) == 2
        assert "edge-gw" in configs
        assert "core-sw" in configs
        assert configs["edge-gw"].url == "http://172.16.0.1"
        assert configs["core-sw"].verify_ssl is False

    def test_load_from_cwd_routers_json(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_file = tmp_path / "routers.json"
        config_file.write_text(json.dumps({
            "routers": {
                "fw-01": {"url": "http://172.16.0.3", "user": "admin"},
            }
        }))
        monkeypatch.delenv("ROUTEROS_CONFIG", raising=False)
        monkeypatch.delenv("ROUTEROS_URL", raising=False)
        monkeypatch.chdir(tmp_path)

        configs = load_router_configs()

        assert len(configs) == 1
        assert "fw-01" in configs

    def test_fallback_to_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ROUTEROS_CONFIG", raising=False)
        monkeypatch.setenv("ROUTEROS_URL", "http://single.test")
        monkeypatch.setenv("ROUTEROS_USER", "admin")
        monkeypatch.setenv("ROUTEROS_PASSWORD", "pass")
        # Ensure no routers.json in CWD
        monkeypatch.chdir("/tmp")

        # Clear lru_cache to pick up new env vars
        from mikrotik_mcp.config import get_settings
        get_settings.cache_clear()

        configs = load_router_configs()

        assert len(configs) == 1
        assert "default" in configs
        assert configs["default"].url == "http://single.test"

    def test_invalid_json_raises(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_file = tmp_path / "routers.json"
        config_file.write_text(json.dumps({"routers": {}}))
        monkeypatch.setenv("ROUTEROS_CONFIG", str(config_file))

        with pytest.raises(ValueError, match="Invalid routers config"):
            load_router_configs()

    def test_keyring_overrides_json_password(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Keyring password takes priority over JSON password."""
        config_file = tmp_path / "routers.json"
        config_file.write_text(json.dumps({
            "routers": {
                "edge-gw": {"url": "http://172.16.0.1", "user": "admin", "password": "json-pass"},
            }
        }))
        monkeypatch.setenv("ROUTEROS_CONFIG", str(config_file))

        with patch("mikrotik_mcp.config.get_password", return_value="keyring-pass"):
            configs = load_router_configs()

        assert configs["edge-gw"].password.get_secret_value() == "keyring-pass"

    def test_fallback_to_json_when_keyring_empty(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Falls back to JSON password when keyring has no entry."""
        config_file = tmp_path / "routers.json"
        config_file.write_text(json.dumps({
            "routers": {
                "edge-gw": {"url": "http://172.16.0.1", "user": "admin", "password": "json-pass"},
            }
        }))
        monkeypatch.setenv("ROUTEROS_CONFIG", str(config_file))

        with patch("mikrotik_mcp.config.get_password", return_value=None):
            configs = load_router_configs()

        assert configs["edge-gw"].password.get_secret_value() == "json-pass"

    def test_single_router_keyring_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Single-router mode uses keyring when env var password is empty."""
        monkeypatch.delenv("ROUTEROS_CONFIG", raising=False)
        monkeypatch.setenv("ROUTEROS_URL", "http://single.test")
        monkeypatch.setenv("ROUTEROS_USER", "admin")
        monkeypatch.setenv("ROUTEROS_PASSWORD", "")
        monkeypatch.chdir("/tmp")

        from mikrotik_mcp.config import get_settings
        get_settings.cache_clear()

        with patch("mikrotik_mcp.config.get_password", return_value="keyring-default"):
            configs = load_router_configs()

        assert configs["default"].password.get_secret_value() == "keyring-default"

    def test_json_defaults(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """User and password default correctly when not specified."""
        config_file = tmp_path / "routers.json"
        config_file.write_text(json.dumps({
            "routers": {
                "minimal": {"url": "http://172.16.0.1"},
            }
        }))
        monkeypatch.setenv("ROUTEROS_CONFIG", str(config_file))

        configs = load_router_configs()

        assert configs["minimal"].user == "admin"
        assert configs["minimal"].password.get_secret_value() == ""
        assert configs["minimal"].verify_ssl is True
