"""Configuration management via environment variables."""

from __future__ import annotations

import json
import logging
import os
import ssl
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from mikrotik_mcp.keyring_store import get_password

logger = logging.getLogger("mikrotik_mcp.config")


class RouterOSSettings(BaseSettings):
    """Settings loaded from environment variables.

    Env vars: ROUTEROS_URL, ROUTEROS_USER, ROUTEROS_PASSWORD,
    ROUTEROS_CA_CERT, ROUTEROS_VERIFY_SSL.
    """

    model_config = SettingsConfigDict(env_prefix="ROUTEROS_")

    url: str
    user: str
    password: SecretStr = SecretStr("")
    ca_cert: str | None = None
    verify_ssl: bool = True

    def get_ssl_context(self) -> ssl.SSLContext | bool:
        """Build SSL verification config for httpx.

        Returns:
            - ssl.SSLContext with custom CA if ca_cert is set
            - False if verify_ssl is disabled
            - True for default system verification
        """
        if not self.verify_ssl:
            return False
        if self.ca_cert:
            ctx = ssl.create_default_context(cafile=self.ca_cert)
            return ctx
        return True


@lru_cache(maxsize=1)
def get_settings() -> RouterOSSettings:
    """Return cached singleton settings instance."""
    return RouterOSSettings()  # type: ignore[call-arg]


def load_router_configs() -> dict[str, RouterOSSettings]:
    """Load router configurations from JSON file or env vars.

    Resolution order:
    1. ROUTEROS_CONFIG env var → path to JSON file
    2. routers.json in CWD
    3. Fallback to single-router env vars with key "default"
    """
    # Try ROUTEROS_CONFIG env var
    config_path = os.environ.get("ROUTEROS_CONFIG")
    if config_path:
        return _load_from_json(Path(config_path))

    # Try routers.json in CWD
    cwd_config = Path("routers.json")
    if cwd_config.exists():
        return _load_from_json(cwd_config)

    # Fallback to single router from env vars
    logger.debug("No multi-router config found, using single-router env vars")
    settings = get_settings()
    if not settings.password.get_secret_value():
        keyring_password = get_password("default")
        if keyring_password:
            settings = RouterOSSettings(
                url=settings.url,
                user=settings.user,
                password=keyring_password,  # type: ignore[arg-type]
                ca_cert=settings.ca_cert,
                verify_ssl=settings.verify_ssl,
            )
    return {"default": settings}


def _load_from_json(path: Path) -> dict[str, RouterOSSettings]:
    """Parse a routers JSON file into a dict of settings."""
    logger.info("Loading router configs from %s", path)
    with open(path) as f:
        data = json.load(f)

    routers_data = data.get("routers", data)
    if not isinstance(routers_data, dict) or not routers_data:
        raise ValueError(f"Invalid routers config in {path}: expected non-empty 'routers' dict")

    configs: dict[str, RouterOSSettings] = {}
    for name, router_cfg in routers_data.items():
        json_password = router_cfg.get("password", "")
        keyring_password = get_password(name)
        password = keyring_password or json_password or ""

        configs[name] = RouterOSSettings(
            url=router_cfg["url"],
            user=router_cfg.get("user", "admin"),
            password=password,  # type: ignore[arg-type]
            ca_cert=router_cfg.get("ca_cert"),
            verify_ssl=router_cfg.get("verify_ssl", True),
        )

    logger.info("Loaded %d router configs: %s", len(configs), ", ".join(sorted(configs)))
    return configs
