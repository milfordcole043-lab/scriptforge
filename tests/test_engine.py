from __future__ import annotations

import sqlite3

from scriptforge import db
from scriptforge.engine import build_write_context, build_rewrite_context, analyze_feedback_patterns, build_video_prompt
from scriptforge.models import Character, Scene


def _scene(beat: str = "hook", dur: int = 10) -> Scene:
    return Scene(beat=beat, voiceover="V", character_action="stares at phone",
                 location="dark bedroom, messy sheets", character_emotion="loneliness",
                 camera="dolly-in", lighting="cold blue phone screen on face",
                 motion="thumb trembles over screen", sound="muffled heartbeat",
                 caption="HEARTBREAK", duration_seconds=dur)


def _seed_data(conn: sqlite3.Connection) -> None:
    scenes = [_scene("hook", 3), _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7)]
    s1 = db.add_script(conn, topic="AI Tools", hook="What if AI replaced your job?",
                        scenes=scenes, full_script="AI is changing everything.",
                        style="educational", tags=["ai"])
    db.rate_script(conn, s1.id, "hit", "Strong hook, good pacing")

    s2 = db.add_script(conn, topic="Sleep hacks", hook="You're sleeping wrong.",
                        scenes=scenes, full_script="Here are five sleep tricks.",
                        style="viral")
    db.rate_script(conn, s2.id, "miss", "Hook too clickbaity, weak ending")

    s3 = db.add_script(conn, topic="History of coffee", hook="Coffee wasn't always legal.",
                        scenes=scenes, full_script="The history of coffee is wild.",
                        style="story")
    db.rate_script(conn, s3.id, "hit", "Great storytelling")

    db.add_rule(conn, rule="Open with a question", category="hook")
    db.add_rule(conn, rule="Change visuals every 5-8 seconds", category="visual")
    db.add_rule(conn, rule="End with a clear call to action", category="structure")


# --- Video prompt builder ---


def test_build_video_prompt_with_character() -> None:
    char = Character(id=1, name="Maya", age="late 20s", gender="female",
                     appearance="dark wavy hair, brown skin",
                     clothing="oversized grey hoodie", created_at=None)
    scene = _scene()
    prompt = build_video_prompt(scene, char)
    assert "female" in prompt
    assert "dark wavy hair" in prompt
    assert "dark bedroom" in prompt
    assert "Consistent lighting" in prompt


def test_build_video_prompt_without_character() -> None:
    scene = _scene()
    prompt = build_video_prompt(scene)
    assert "dark bedroom" in prompt
    assert "stares at phone" in prompt


# --- Write context ---


def test_build_write_context_has_rules(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=45)
    assert len(ctx["rules"]) == 3


def test_build_write_context_has_top_hooks(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=45)
    assert len(ctx["top_hooks"]) > 0


def test_build_write_context_has_feedback_patterns(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=45)
    assert "feedback_patterns" in ctx


def test_build_write_context_has_prompt(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=45)
    assert "New topic" in ctx["prompt"]
    assert "NARRATIVE ARC" in ctx["prompt"]
    assert "character_action" in ctx["prompt"]
    assert "location" in ctx["prompt"]
    assert "lighting" in ctx["prompt"]


def test_build_write_context_has_voice_profile(conn: sqlite3.Connection) -> None:
    db.seed_defaults(conn)
    ctx = build_write_context(conn, topic="Test", style="cinematic", duration_target=45)
    assert len(ctx["voice_profile"]) == 5
    assert "VOICE PROFILE" in ctx["prompt"]


def test_build_write_context_empty_db(conn: sqlite3.Connection) -> None:
    ctx = build_write_context(conn, topic="Fresh start", style="cinematic", duration_target=35)
    assert ctx["rules"] == []
    assert "Fresh start" in ctx["prompt"]


# --- Rewrite context ---


def test_build_rewrite_context(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    scripts = db.list_scripts(conn)
    rated_miss = [s for s in scripts if s.rating == "miss"][0]
    ctx = build_rewrite_context(conn, rated_miss.id)
    assert rated_miss.topic in ctx["prompt"]


def test_build_rewrite_context_not_found(conn: sqlite3.Connection) -> None:
    assert build_rewrite_context(conn, 999) is None


# --- Feedback analysis ---


def test_analyze_feedback_patterns(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    patterns = analyze_feedback_patterns(conn)
    assert len(patterns["hit_notes"]) == 2
    assert len(patterns["miss_notes"]) == 1


def test_analyze_feedback_patterns_empty(conn: sqlite3.Connection) -> None:
    patterns = analyze_feedback_patterns(conn)
    assert patterns["hit_notes"] == []
