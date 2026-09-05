"""
Centralized application configuration.

Everything that varies between environments (dev/staging/prod) or that is
sensitive (secrets, connection strings) is read from environment variables
here — never hard-coded. See .env.example for the full list of variables.
"""
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    APP_ENV: str = "development"
    APP_SECRET_KEY: str
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    # Where the Next.js frontend lives — /auth/callback redirects here after
    # a successful login, since the backend has no UI routes of its own.
    FRONTEND_URL: str = "http://localhost:3000"

    # Database
    DATABASE_URL: str
    DATABASE_URL_SYNC: str

    # Microsoft Entra ID
    ENTRA_TENANT_ID: str = ""
    ENTRA_CLIENT_ID: str = ""
    ENTRA_CLIENT_SECRET: str = ""
    ENTRA_REDIRECT_URI: str = "http://localhost:8000/auth/callback"
    ENTRA_SCOPES: str = "User.Read"

    # SharePoint / Graph — populated in Phase 2
    GRAPH_SITE_ID: str = ""
    GRAPH_DRIVE_ID: str = ""

    # OCR (Phase 4) — pytesseract shells out to the `tesseract` binary via
    # PATH by default, which is all that's needed on Linux (apt install
    # puts it in /usr/bin, already on PATH). On Windows, an installer like
    # winget's UB-Mannheim build doesn't reliably land on PATH for
    # already-running processes, so this lets it be pointed at an absolute
    # path explicitly. Leave blank to keep relying on PATH (the Linux/prod
    # default).
    TESSERACT_CMD: str = ""

    # Session
    SESSION_COOKIE_NAME: str = "puma_dms_session"
    SESSION_EXPIRE_MINUTES: int = 480

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str) and not v.startswith("["):
            return [origin.strip() for origin in v.split(",")]
        return v

    @property
    def ENTRA_AUTHORITY(self) -> str:
        return f"https://login.microsoftonline.com/{self.ENTRA_TENANT_ID}"


@lru_cache
def get_settings() -> "Settings":
    """Settings are cached — env is read once per process, not per request."""
    return Settings()
