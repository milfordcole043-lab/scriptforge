from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from scriptforge import db
from scriptforge.cli import cli
from scriptforge.engine import build_write_context, match_template
from scriptforge.models import (
    Scene, Script, StoryTemplate, get_valid_beats, validate_script, VALID_BEATS,
)


def _invoke(tmp_path: Path, args: list[str] | None = None) -> object:
    runner = CliRunner()
    return runner.invoke(cli, ["--db-path", str(tmp_path / "test.db")] + (args or []))


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "test.db")
    db.seed_defaults(connection)
    yield connection
    connection.close()


def _scene(beat: str, dur: int = 5) -> Scene:
    return Scene(beat=beat, voiceover="test", character_action="sits", location="bedroom",
                 character_emotion="loneliness", camera="static", lighting="cold blue phone screen",
                 motion="barely any", sound="silence", caption="TEST", duration_seconds=dur)


# --- Template matching: keywords ---


def test_match_template_mirror_keywords(conn: sqlite3.Connection) -> None:
    t, reason = match_template("heartbreak after rejection", conn)
    assert t is not None
    assert t.name == "THE MIRROR"
    assert "matched keywords" in reason


def test_match_template_mystery_keywords(conn: sqlite3.Connection) -> None:
    t, reason = match_template("why do I always repeat this pattern", conn)
    assert t is not None
    assert t.name == "THE MYSTERY"


def test_match_template_contradiction_keywords(conn: sqlite3.Connection) -> None:
    t, reason = match_template("two opposite truths that both contradict each other", conn)
    assert t is not None
    assert t.name == "THE CONTRADICTION"


def test_match_template_timeline_keywords(conn: sqlite3.Connection) -> None:
    t, reason = match_template("what happens in the first 30 seconds after you wake up", conn)
    assert t is not None
    assert t.name == "THE TIMELINE"


def test_match_template_confession_keywords(conn: sqlite3.Connection) -> None:
    t, reason = match_template("I thought something was wrong with me and I was ashamed", conn)
    assert t is not None
    assert t.name == "THE CONFESSION"


def test_match_template_zoom_out_keywords(conn: sqlite3.Connection) -> None:
    t, reason = match_template("that tingling feeling when you get goosebumps", conn)
    assert t is not None
    assert t.name == "THE ZOOM OUT"


# --- Default fallback ---


def test_match_template_default_fallback(conn: sqlite3.Connection) -> None:
    t, reason = match_template("quantum chromodynamics in particle physics", conn)
    assert t is not None
    assert t.name == "THE MIRROR"
    assert "default" in reason


# --- Manual override ---


def test_match_template_manual_override(conn: sqlite3.Connection) -> None:
    t, reason = match_template("anything", conn, override_name="mystery")
    assert t is not None
    assert t.name == "THE MYSTERY"
    assert reason == "manually selected"


def test_match_template_invalid_override_falls_through(conn: sqlite3.Connection) -> None:
    t, reason = match_template("heartbreak", conn, override_name="nonexistent")
    # Falls through to auto-match
    assert t is not None
    assert t.name == "THE MIRROR"


# --- Success rate weighting ---


def test_match_template_success_rate_weighting(conn: sqlite3.Connection) -> None:
    # Boost THE ZOOM OUT's success rate to make it win on a neutral topic
    conn.execute("UPDATE story_templates SET success_rate = 4.5 WHERE name = 'THE ZOOM OUT'")
    conn.commit()
    # Use a topic with no keyword matches for any template
    t, _ = match_template("a completely neutral topic xyz", conn)
    assert t is not None
    assert t.name == "THE ZOOM OUT"


# --- Recency avoidance ---


def test_match_template_recency_avoidance(conn: sqlite3.Connection) -> None:
    mirror = db.get_template_by_name(conn, "mirror")
    assert mirror is not None
    # Create 3 recent scripts using THE MIRROR
    scenes = [_scene("hook", 3), _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7)]
    for _ in range(3):
        db.add_script(conn, topic="test", hook="test hook", scenes=scenes,
                      full_script="test script.", template_id=mirror.id)
    # Now "heartbreak" normally matches MIRROR, but recency penalty should push it away
    t, _ = match_template("heartbreak", conn)
    assert t is not None
    assert t.name != "THE MIRROR"


# --- Beat validation with templates ---


def test_validate_script_with_mystery_template(conn: sqlite3.Connection) -> None:
    mystery = db.get_template_by_name(conn, "mystery")
    assert mystery is not None
    scenes = [_scene("question", 3), _scene("clues", 10), _scene("reveal", 10), _scene("reframe", 5)]
    errors = validate_script(scenes, "test script.", template=mystery)
    assert errors == []


def test_validate_script_wrong_beats_for_template(conn: sqlite3.Connection) -> None:
    mystery = db.get_template_by_name(conn, "mystery")
    assert mystery is not None
    # Standard beats don't match mystery template
    scenes = [_scene("hook", 3), _scene("tension", 10), _scene("revelation", 10), _scene("resolution", 5)]
    errors = validate_script(scenes, "test script.", template=mystery)
    assert len(errors) > 0
    assert "Missing beats" in errors[0]


def test_validate_script_default_beats_no_template() -> None:
    scenes = [_scene("hook", 3), _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7)]
    errors = validate_script(scenes, "test script.")
    assert errors == []


# --- get_valid_beats ---


def test_get_valid_beats_default() -> None:
    assert get_valid_beats() == VALID_BEATS


def test_get_valid_beats_with_template() -> None:
    t = StoryTemplate(id=1, name="test", description="", beat_structure=[
        {"beat": "alpha", "description": "", "duration_min": 3, "duration_max": 5, "rule_categories": []},
        {"beat": "beta", "description": "", "duration_min": 5, "duration_max": 8, "rule_categories": []},
    ], matching_keywords=[], visual_style="")
    assert get_valid_beats(t) == {"alpha", "beta"}


# --- DB template operations ---


def test_seed_templates(conn: sqlite3.Connection) -> None:
    templates = db.get_all_templates(conn)
    assert len(templates) == 6


def test_get_template_by_name_case_insensitive(conn: sqlite3.Connection) -> None:
    t = db.get_template_by_name(conn, "mystery")
    assert t is not None
    assert t.name == "THE MYSTERY"

    t2 = db.get_template_by_name(conn, "CONTRADICTION")
    assert t2 is not None
    assert t2.name == "THE CONTRADICTION"


def test_increment_template_usage(conn: sqlite3.Connection) -> None:
    mirror = db.get_template_by_name(conn, "mirror")
    assert mirror is not None
    assert mirror.times_used == 0
    db.increment_template_usage(conn, mirror.id)
    updated = db.get_template(conn, mirror.id)
    assert updated is not None
    assert updated.times_used == 1


def test_update_template_success_rate(conn: sqlite3.Connection) -> None:
    mirror = db.get_template_by_name(conn, "mirror")
    assert mirror is not None
    scenes = [_scene("hook", 3), _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7)]
    s = db.add_script(conn, topic="test", hook="test", scenes=scenes,
                      full_script="test script.", template_id=mirror.id)
    # Add scene feedback
    db.save_scene_feedback(conn, s.id, 0, visual_quality=4, emotional_impact=5, pacing=3)
    db.save_scene_feedback(conn, s.id, 1, visual_quality=3, emotional_impact=4, pacing=5)
    rate = db.update_template_success_rate(conn, mirror.id)
    assert rate > 0
    updated = db.get_template(conn, mirror.id)
    assert updated.success_rate == rate


def test_get_recent_template_ids(conn: sqlite3.Connection) -> None:
    mirror = db.get_template_by_name(conn, "mirror")
    mystery = db.get_template_by_name(conn, "mystery")
    scenes = [_scene("hook", 3), _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7)]
    db.add_script(conn, topic="t1", hook="h1", scenes=scenes,
                  full_script="test.", template_id=mirror.id)
    mystery_scenes = [_scene("question", 3), _scene("clues", 10), _scene("reveal", 10), _scene("reframe", 5)]
    db.add_script(conn, topic="t2", hook="h2", scenes=mystery_scenes,
                  full_script="test.", template_id=mystery.id)
    recent = db.get_recent_template_ids(conn, limit=2)
    assert len(recent) == 2
    assert recent[0] == mystery.id  # most recent first


# --- Write prompt uses template ---


def test_write_prompt_uses_template_beats(conn: sqlite3.Connection) -> None:
    ctx = build_write_context(conn, topic="why do I always repeat", style="educational",
                               duration_target=45, template_name="mystery")
    assert "QUESTION" in ctx["prompt"]
    assert "CLUES" in ctx["prompt"]
    assert "REVEAL" in ctx["prompt"]
    assert "REFRAME" in ctx["prompt"]
    assert "THE MYSTERY" in ctx["prompt"]


def test_write_prompt_includes_visual_style(conn: sqlite3.Connection) -> None:
    ctx = build_write_context(conn, topic="test", style="educational",
                               duration_target=45, template_name="mystery")
    assert "progressive reveal" in ctx["prompt"].lower()


def test_contextual_rules_use_template_categories(conn: sqlite3.Connection) -> None:
    ctx = build_write_context(conn, topic="test", style="educational",
                               duration_target=45, template_name="contradiction")
    prompt = ctx["prompt"]
    assert "PARADOX" in prompt
    assert "SIDE A" in prompt
    assert "SIDE B" in prompt
    assert "SYNTHESIS" in prompt


# --- CLI ---


def test_cli_templates_command(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["templates"])
    assert result.exit_code == 0
    assert "THE MIRROR" in result.output
    assert "THE MYSTERY" in result.output


def test_cli_write_with_template_override(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["write", "test topic", "--template", "mystery", "--no-generate"])
    assert result.exit_code == 0
    assert "THE MYSTERY" in result.output


def test_cli_write_shows_template(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["write", "heartbreak story", "--no-generate"])
    assert result.exit_code == 0
    assert "Template" in result.output
