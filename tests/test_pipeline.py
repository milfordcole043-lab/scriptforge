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


def _seed_script_with_character(tmp_path: Path) -> int:
    conn = db.connect(tmp_path / "test.db")
    char = db.add_character(conn, name="Maya", age="late 20s", gender="female",
                            appearance="dark wavy hair, brown skin",
                            clothing="oversized grey hoodie")
    scenes = [
        Scene(beat="hook", voiceover="Opening line", character_action="stares at phone",
              location="dark bedroom, messy sheets", character_emotion="loneliness",
              camera="static", lighting="cold blue phone screen on face",
              motion="thumb trembles", sound="silence", caption="THE HOOK",
              duration_seconds=3),
        Scene(beat="tension", voiceover="Building tension", character_action="drops head into hands",
              location="same bedroom, darker now", character_emotion="confusion",
              camera="dolly-in", lighting="cold blue phone screen fading",
              motion="shoulders tremble", sound="low hum", caption="WHAT IF",
              duration_seconds=10),
        Scene(beat="revelation", voiceover="The twist", character_action="looks up slowly",
              location="same bedroom, first light at window", character_emotion="recognition",
              camera="crane", lighting="cold blue mixing with warm dawn through window",
              motion="light creeping across floor", sound="heartbeat slowing", caption="THE TRUTH",
              duration_seconds=12),
        Scene(beat="resolution", voiceover="Closing", character_action="puts phone face-down on nightstand",
              location="same bedroom, dawn light filling the room", character_emotion="quiet strength",
              camera="static", lighting="warm amber dawn through window",
              motion="light spreading, dust particles floating", sound="distant birdsong",
              caption="YOU DECIDE", duration_seconds=7),
    ]
    script = db.add_script(
        conn, topic="Test topic", hook="It's 3 AM.",
        scenes=scenes, full_script="Opening line. Building tension. The twist. Closing.",
        style="cinematic", duration_target=32, character_id=char.id,
    )
    conn.close()
    return script.id


# --- Dry run tests ---


def test_render_dry_run(tmp_path: Path) -> None:
    script_id = _seed_script_with_character(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "Test topic" in result.output
    assert "Maya" in result.output


def test_render_dry_run_shows_beats(tmp_path: Path) -> None:
    script_id = _seed_script_with_character(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "hook" in result.output
    assert "tension" in result.output
    assert "revelation" in result.output
    assert "resolution" in result.output


def test_render_dry_run_shows_captions(tmp_path: Path) -> None:
    script_id = _seed_script_with_character(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "THE HOOK" in result.output
    assert "THE TRUTH" in result.output


def test_render_dry_run_shows_steps(tmp_path: Path) -> None:
    script_id = _seed_script_with_character(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "Flux Pro" in result.output
    assert "Kling" in result.output
    assert "ElevenLabs" in result.output
    assert "caption" in result.output.lower()
    assert "$" in result.output  # cost estimate


def test_render_dry_run_shows_character_actions(tmp_path: Path) -> None:
    script_id = _seed_script_with_character(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    # Actions appear truncated in the Rich table but the key words should be visible
    assert "stares at" in result.output or "phone" in result.output
    assert "drops head" in result.output or "hands" in result.output


def test_render_dry_run_shows_locations(tmp_path: Path) -> None:
    script_id = _seed_script_with_character(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "bedroom" in result.output


def test_render_not_found(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["render", "999", "--dry-run"])
    assert "not found" in result.output.lower()


def test_render_no_character(tmp_path: Path) -> None:
    """Script without character should fail."""
    conn = db.connect(tmp_path / "test.db")
    def _ns(beat, dur):
        return Scene(beat=beat, voiceover="V", character_action="a", location="room",
                     character_emotion="e", camera="static", lighting="lamp light",
                     motion="m", sound="s", caption="C", duration_seconds=dur)
    scenes = [_ns("hook", 3), _ns("tension", 10), _ns("revelation", 12), _ns("resolution", 7)]
    db.add_script(conn, topic="No char", hook="H", scenes=scenes, full_script="T")
    conn.close()
    result = _invoke(tmp_path, ["render", "1", "--dry-run"])
    assert "no character" in result.output.lower()


# --- Config tests ---


def test_config_check_keys() -> None:
    from scriptforge.config import check_keys
    missing = check_keys()
    assert isinstance(missing, list)
