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
    conn = db.connect(tmp_path / "test.db")
    scenes = [
        Scene(beat="hook", voiceover="Opening line", visual="Title card with bold text",
              camera="dolly-in", motion="text fades in", sound="silence",
              emotion="curiosity", duration_seconds=3, caption="THE HOOK"),
        Scene(beat="tension", voiceover="Building tension here", visual="Dark corridor",
              camera="tracking", motion="shadows creep", sound="low hum",
              emotion="unease", duration_seconds=10, caption="WHAT IF"),
        Scene(beat="revelation", voiceover="The twist revealed", visual="Brain scan animation",
              camera="crane", motion="neurons fire", sound="heartbeat",
              emotion="recognition", duration_seconds=12, caption="THE TRUTH"),
        Scene(beat="resolution", voiceover="Closing statement", visual="Sunset timelapse",
              camera="static", motion="light spreads", sound="birds",
              emotion="hope", duration_seconds=7, caption="YOU DECIDE"),
    ]
    script = db.add_script(
        conn, topic="Test topic", hook="Did you know?",
        scenes=scenes, full_script="Opening line. Building tension here. The twist revealed. Closing statement.",
        style="educational", duration_target=32,
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
    assert "4" in result.output  # 4 scenes


def test_render_dry_run_shows_beats(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "hook" in result.output
    assert "tension" in result.output
    assert "revelation" in result.output
    assert "resolution" in result.output


def test_render_dry_run_shows_captions(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "THE HOOK" in result.output
    assert "THE TRUTH" in result.output


def test_render_dry_run_shows_steps(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "Flux Pro" in result.output
    assert "Kling" in result.output
    assert "ElevenLabs" in result.output
    assert "FFmpeg" in result.output
    assert "caption" in result.output.lower()


def test_render_not_found(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["render", "999", "--dry-run"])
    assert "not found" in result.output.lower()


def test_render_dry_run_shows_camera(tmp_path: Path) -> None:
    script_id = _seed_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "dolly-in" in result.output
    assert "tracking" in result.output


# --- Config tests ---


def test_config_check_keys() -> None:
    from scriptforge.config import check_keys
    missing = check_keys()
    assert isinstance(missing, list)
