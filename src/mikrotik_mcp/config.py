"""Configuration management via environment variables."""

from __future__ import annotations

import ssl
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RouterOSSettings(BaseSettings):
    """Settings loaded from environment variables.

    Env vars: ROUTEROS_URL, ROUTEROS_USER, ROUTEROS_PASS,
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
