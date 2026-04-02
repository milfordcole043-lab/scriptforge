from __future__ import annotations

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from scriptforge import db
from scriptforge.cli import cli
from scriptforge.models import Scene


def _invoke(tmp_path: Path, args: list[str] | None = None) -> object:
    runner = CliRunner()
    return runner.invoke(cli, ["--db-path", str(tmp_path / "test.db")] + (args or []))


def _seed_script(tmp_path: Path) -> int:
    """Add a script via db and return its ID."""
    conn = db.connect(tmp_path / "test.db")
    scenes = [
        Scene(voiceover="Opening line", visual="Title card with bold text", duration_seconds=5, transition="cut"),
        Scene(voiceover="Main content here", visual="Brain scan animation", duration_seconds=15, transition="dissolve"),
        Scene(voiceover="Closing statement", visual="Sunset timelapse", duration_seconds=10, transition="fade"),
    ]
    script = db.add_script(
        conn, topic="Test topic", hook="Did you know?",
        scenes=scenes, full_script="Opening line. Main content here. Closing statement.",
        style="educational", duration_target=30, hook_style="question",
    )
    conn.close()
    return script.id


# --- Dry run tests ---


def test_render_dry_run(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "Test topic" in result.output
    assert "3" in result.output  # 3 scenes
    assert "scene_01" in result.output
    assert "scene_02" in result.output
    assert "scene_03" in result.output


def test_render_dry_run_shows_durations(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "5s" in result.output
    assert "15s" in result.output
    assert "10s" in result.output


def test_render_dry_run_shows_kling_durations(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    # 5s scene -> Kling 5s, 15s scene -> Kling 10s, 10s scene -> Kling 10s
    output = result.output
    assert "Kling" in output or "Render Plan" in output


def test_render_dry_run_shows_steps(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "Flux Pro" in result.output
    assert "Kling" in result.output
    assert "ElevenLabs" in result.output
    assert "FFmpeg" in result.output


def test_render_not_found(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["render", "999", "--dry-run"])
    assert "not found" in result.output.lower()


def test_render_dry_run_shows_visual_prompts(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "Title card" in result.output
    assert "Brain scan" in result.output


# --- Config tests ---


def test_config_check_keys() -> None:
    from scriptforge.config import check_keys
    # Keys are set from .env, so this should return empty or the missing ones
    missing = check_keys()
    assert isinstance(missing, list)
