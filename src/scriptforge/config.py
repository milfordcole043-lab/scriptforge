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

# --- API keys ---
ELEVENLABS_API_KEY: str = os.environ.get("ELEVENLABS_API_KEY", "")
FAL_KEY: str = os.environ.get("FAL_KEY", "")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# --- Paths ---
OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent.parent / "output"

# --- Voice IDs (ElevenLabs) ---
VOICE_NARRATOR: str = "nPczCjzI2devNBz1zQrb"  # Brian — warm, natural
VOICE_POV: str = "pFZP5JQG7iQjIQuC4Bku"  # Lily — young female

# --- Model IDs (fal.ai) ---
MODEL_FLUX_PRO: str = "fal-ai/flux-pro/v1.1"
MODEL_KLING_V3: str = "fal-ai/kling-video/v3/pro/image-to-video"
MODEL_FABRIC: str = "veed/fabric-1.0"

# --- Cost estimates (USD) ---
COST_FLUX_PRO: float = 0.04       # per image
COST_KLING_V3: float = 0.112      # per second, no audio
COST_ELEVENLABS: float = 0.03     # per second estimate
COST_FABRIC: float = 0.15         # per second at 720p

# --- Video generation ---
KLING_NEGATIVE: str = "blur, flickering, morphing faces, distorted hands, text, watermark, low quality, jittery motion"
COST_CLAUDE_VISION: float = 0.04  # per review call (3 frames + reference per scene)
WPM: int = 130  # words per minute for voiceover pacing

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
    text = text.replace("'", "\u2019")
    text = text.replace(":", "\\:")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    text = text.replace("[", "\\[")
    text = text.replace("]", "\\]")
    text = text.replace(";", "\\;")
    return text
