"""Environment configuration. No credentials are required for the demo API.

Local development may use the repository-root .env file. Environment variables
take precedence. In production, inject secrets as environment variables from
Google Cloud Secret Manager and use the Cloud Run service identity for Google
authentication; do not ship credential files.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


LOCAL_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: str = "development"
    port: int = Field(default=8080, ge=1, le=65535)
    anymize_api_key: SecretStr = Field(default=SecretStr(""), repr=False, exclude=True)
    google_cloud_project: str = "aiwomen26ham-4410"
    google_cloud_location: str = "europe-west3"
    gemini_model: str = ""
    model_provider: Literal["vertex", "anymize"] = "vertex"
    anymize_model: str = ""
    allowed_origins: str = ""

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: str) -> str:
        origins = []
        for item in value.split(","):
            origin = item.strip()
            if not origin:
                continue
            try:
                parsed = urlsplit(origin)
                valid = (parsed.scheme in ("http", "https") and parsed.hostname
                         and not parsed.username and not parsed.password
                         and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                         and not any(c.isspace() for c in origin) and "*" not in origin)
                _ = parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("ALLOWED_ORIGINS must contain explicit HTTP(S) origins without credentials, paths or wildcards.")
            origins.append(origin.rstrip("/"))
        return ",".join(dict.fromkeys(origins))

    @property
    def cors_origins(self) -> list[str]:
        origins = [origin for origin in self.allowed_origins.split(",") if origin]
        if self.app_env == "development":
            origins.extend(("http://localhost:3000", "http://localhost:5173"))
        return list(dict.fromkeys(origins))


@lru_cache
def get_settings() -> Settings:
    # Determine the environment without consulting any local file first.
    environment_settings = Settings()
    if environment_settings.app_env == "development":
        return Settings(_env_file=LOCAL_ENV_FILE, _env_file_encoding="utf-8")
    return environment_settings
