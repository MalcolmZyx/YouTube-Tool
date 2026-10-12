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


class Settings(BaseSettings):
    # Auto-reload on code changes. Safe locally, never enable on a shared host.
    debug: bool = False
    port: int = 5000
    # Comma-separated list of browser origins allowed to call the API directly.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()


def get_api_key() -> str:
    """The YouTube Data API key, read on every call.

    It is read from the environment each time (not cached at import) because the Settings
    page can replace it at runtime.
    """
    return os.environ.get("YOUTUBE_API_KEY", "")
