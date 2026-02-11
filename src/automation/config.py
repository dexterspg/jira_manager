"""Configuration for web UI automation, loaded from .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (two levels up from src/automation/)
load_dotenv(Path(__file__).parent.parent.parent / ".env")

WEB_UI_BASE_URL = os.getenv("WEB_UI_BASE_URL", "")
WEB_UI_TIMEOUT = int(os.getenv("WEB_UI_TIMEOUT", "30"))
WEB_UI_HEADLESS = os.getenv("WEB_UI_HEADLESS", "true").lower() in ("true", "1", "yes")


def validate_config() -> str | None:
    """Return an error string if configuration is incomplete, or None if valid."""
    if not WEB_UI_BASE_URL:
        return "Error: WEB_UI_BASE_URL is not set. Add it to your .env file."
    return None
