from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from rich.console import Console

_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ENV_PATH)

ELEVENLABS_API_KEY: str = os.environ.get("ELEVENLABS_API_KEY", "")
FAL_KEY: str = os.environ.get("FAL_KEY", "")
OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent.parent / "output"

console = Console()


def check_keys() -> list[str]:
    missing = []
    if not ELEVENLABS_API_KEY:
        missing.append("ELEVENLABS_API_KEY")
    if not FAL_KEY:
        missing.append("FAL_KEY")
    return missing


def retry_api_call(fn: Callable[..., Any], *args: Any, retries: int = 3,
                   label: str = "API call", **kwargs: Any) -> Any:
    """Call fn with retries and exponential backoff. Raises on final failure."""
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == retries:
                console.print(f"[red]{label} failed after {retries} attempts: {e}[/red]")
                raise
            wait = 2 ** attempt
            console.print(f"  [yellow]{label} attempt {attempt}/{retries} failed: {e}. Retrying in {wait}s...[/yellow]")
            time.sleep(wait)


def safe_download(url: str, dest: str, label: str = "download") -> None:
    """Download a URL to a file with retry logic."""
    def _download() -> None:
        urllib.request.urlretrieve(url, dest)
    retry_api_call(_download, label=label)


def escape_ffmpeg_text(text: str) -> str:
    """Properly escape text for FFmpeg drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\u2019")  # replace with curly apostrophe
    text = text.replace(":", "\\:")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    text = text.replace("[", "\\[")
    text = text.replace("]", "\\]")
    text = text.replace(";", "\\;")
    return text
