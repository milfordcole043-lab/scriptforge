from __future__ import annotations

import sqlite3

from scriptforge import db
from scriptforge.models import Scene


# --- Script CRUD ---


def test_add_script(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="Hello world", visual="Title card", duration_seconds=5)]
    script = db.add_script(
        conn,
        topic="AI basics",
        hook="What if AI could think?",
        scenes=scenes,
        full_script="Hello world. This is a test.",
        style="educational",
        duration_target=60,
        hook_style="question",
        angle="beginner intro",
        tags=["ai", "intro"],
    )
    assert script.id is not None
    assert script.topic == "AI basics"
    assert script.word_count == 6
    assert script.hook_style == "question"
    assert sorted(script.tags) == ["ai", "intro"]


def test_get_script(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="Test", visual="Visual", duration_seconds=5)]
    added = db.add_script(conn, topic="Test", hook="Hook", scenes=scenes, full_script="Test script")
    fetched = db.get_script(conn, added.id)
    assert fetched is not None
    assert fetched.topic == "Test"
    assert len(fetched.scenes) == 1
    assert fetched.scenes[0].voiceover == "Test"


def test_get_script_not_found(conn: sqlite3.Connection) -> None:
    assert db.get_script(conn, 999) is None


def test_list_scripts(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="V", visual="V", duration_seconds=5)]
    db.add_script(conn, topic="Script 1", hook="H1", scenes=scenes, full_script="One")
    db.add_script(conn, topic="Script 2", hook="H2", scenes=scenes, full_script="Two")
    scripts = db.list_scripts(conn)
    assert len(scripts) == 2


def test_list_scripts_empty(conn: sqlite3.Connection) -> None:
    assert db.list_scripts(conn) == []


# --- Rating & feedback ---


def test_rate_script(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="V", visual="V", duration_seconds=5)]
    script = db.add_script(conn, topic="Rate me", hook="H", scenes=scenes, full_script="Test")
    result = db.rate_script(conn, script.id, "hit", "Great pacing")
    assert result is True
    updated = db.get_script(conn, script.id)
    assert updated.rating == "hit"
    assert updated.feedback == "Great pacing"


def test_rate_script_not_found(conn: sqlite3.Connection) -> None:
    assert db.rate_script(conn, 999, "hit", "notes") is False


def test_get_feedback_log(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="V", visual="V", duration_seconds=5)]
    script = db.add_script(conn, topic="FB", hook="H", scenes=scenes, full_script="Test")
    db.rate_script(conn, script.id, "hit", "Good hook")
    db.rate_script(conn, script.id, "miss", "Weak ending")
    entries = db.get_feedback_log(conn, script.id)
    assert len(entries) == 2


# --- Rewrites ---


def test_add_rewrite(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="V1", visual="V", duration_seconds=5)]
    original = db.add_script(conn, topic="Original", hook="H", scenes=scenes, full_script="First version")
    new_scenes = [Scene(voiceover="V2", visual="V", duration_seconds=5)]
    rewrite = db.add_script(
        conn, topic="Original", hook="Better hook", scenes=new_scenes,
        full_script="Second version", parent_id=original.id, version=2,
    )
    assert rewrite.parent_id == original.id
    assert rewrite.version == 2


# --- Hooks ---


def test_add_hook(conn: sqlite3.Connection) -> None:
    hook = db.add_hook(conn, text="Did you know?", style="question")
    assert hook.id is not None
    assert hook.style == "question"


def test_get_top_hooks(conn: sqlite3.Connection) -> None:
    db.add_hook(conn, text="Hook 1", style="question")
    h2 = db.add_hook(conn, text="Hook 2", style="shock")
    db.rate_hook(conn, h2.id, "good")
    top = db.get_top_hooks(conn, limit=5)
    # Rated hooks first
    assert top[0].text == "Hook 2"


def test_rate_hook(conn: sqlite3.Connection) -> None:
    hook = db.add_hook(conn, text="Rate me", style="stat")
    assert db.rate_hook(conn, hook.id, "good") is True
    hooks = db.get_top_hooks(conn, limit=5)
    assert hooks[0].rating == "good"


# --- Rules ---


def test_add_rule(conn: sqlite3.Connection) -> None:
    rule = db.add_rule(conn, rule="Always open with a question", category="hook", source="feedback #1")
    assert rule.id is not None
    assert rule.category == "hook"
    assert rule.active is True


def test_get_active_rules(conn: sqlite3.Connection) -> None:
    db.add_rule(conn, rule="Rule 1", category="hook")
    db.add_rule(conn, rule="Rule 2", category="pacing")
    r3 = db.add_rule(conn, rule="Rule 3", category="visual")
    db.deactivate_rule(conn, r3.id)
    active = db.get_active_rules(conn)
    assert len(active) == 2


def test_deactivate_rule(conn: sqlite3.Connection) -> None:
    rule = db.add_rule(conn, rule="Temp rule")
    assert db.deactivate_rule(conn, rule.id) is True
    active = db.get_active_rules(conn)
    assert len(active) == 0


# --- Search ---


def test_search_scripts(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="V", visual="V", duration_seconds=5)]
    db.add_script(conn, topic="AI revolution", hook="H", scenes=scenes, full_script="AI is changing the world")
    db.add_script(conn, topic="Cooking tips", hook="H", scenes=scenes, full_script="How to cook pasta")
    results = db.search_scripts(conn, "AI")
    assert len(results) == 1
    assert results[0].topic == "AI revolution"


def test_search_scripts_empty(conn: sqlite3.Connection) -> None:
    assert db.search_scripts(conn, "nonexistent") == []


# --- Stats ---


def test_get_stats(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="V", visual="V", duration_seconds=5)]
    db.add_script(conn, topic="S1", hook="H", scenes=scenes, full_script="Test", style="educational")
    db.add_script(conn, topic="S2", hook="H", scenes=scenes, full_script="Test", style="cinematic")
    db.rate_script(conn, 1, "hit", "Good")
    db.add_rule(conn, rule="Rule 1")
    stats = db.get_stats(conn)
    assert stats["total_scripts"] == 2
    assert stats["rated_scripts"] == 1
    assert stats["total_rules"] == 1
    assert "educational" in stats["style_counts"]


# --- Tags ---


def test_script_tags(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="V", visual="V", duration_seconds=5)]
    db.add_script(conn, topic="Tagged", hook="H", scenes=scenes, full_script="Test", tags=["ai", "tech"])
    script = db.get_script(conn, 1)
    assert sorted(script.tags) == ["ai", "tech"]


def test_script_no_tags(conn: sqlite3.Connection) -> None:
    scenes = [Scene(voiceover="V", visual="V", duration_seconds=5)]
    db.add_script(conn, topic="No tags", hook="H", scenes=scenes, full_script="Test")
    script = db.get_script(conn, 1)
    assert script.tags == []
