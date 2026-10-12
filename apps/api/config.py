"""Application configuration.

Everything environment-specific lives here and is read from environment variables
(optionally populated from apps/api/.env). Nothing in the code base hard-codes a port,
an allowed origin or a debug flag.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent

# Populate os.environ from apps/api/.env. Variables that are already set win, so real
# environment variables and tests can override the file.
load_dotenv(BASE_DIR / ".env")


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    # Auto-reload on code changes. Safe locally, never enable on a shared host.
    debug: bool = False
    port: int = 5000
    # Comma-separated list of browser origins allowed to call the API (CORS) and to make
    # state-changing requests (see security.py). Both spellings of localhost are listed
    # because a browser treats http://localhost:5173 and http://127.0.0.1:5173 as different origins.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Host names the server answers to. Anything else is rejected, which blocks DNS rebinding.
    allowed_hosts: str = "localhost,127.0.0.1"
    # Interactive docs at /docs. Convenient locally; turn off on a shared host.
    docs_enabled: bool = True
    # Limits on an uploaded export. Real Studio exports are tens of kilobytes; the row cap also
    # bounds the number of YouTube API calls one upload can trigger.
    max_upload_mb: int = 5
    max_rows: int = 5000

    @property
    def cors_origin_list(self) -> list[str]:
        return _split(self.cors_origins)

    @property
    def allowed_host_list(self) -> list[str]:
        return _split(self.allowed_hosts)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()


def get_api_key() -> str:
    """The YouTube Data API key, read on every call.

    It is read from the environment each time (not cached at import) because the Settings
    page can replace it at runtime.
    """
    return os.environ.get("YOUTUBE_API_KEY", "")
