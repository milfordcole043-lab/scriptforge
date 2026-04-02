from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load from project .env first, fall back to environment
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ENV_PATH)

ELEVENLABS_API_KEY: str = os.environ.get("ELEVENLABS_API_KEY", "")
FAL_KEY: str = os.environ.get("FAL_KEY", "")
OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent.parent / "output"


def check_keys() -> list[str]:
    """Return list of missing API key names."""
    missing = []
    if not ELEVENLABS_API_KEY:
        missing.append("ELEVENLABS_API_KEY")
    if not FAL_KEY:
        missing.append("FAL_KEY")
    return missing
