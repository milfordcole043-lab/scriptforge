from __future__ import annotations

import sqlite3

from scriptforge import db
from scriptforge.engine import build_write_context, build_rewrite_context, analyze_feedback_patterns
from scriptforge.models import Scene


def _seed_data(conn: sqlite3.Connection) -> None:
    """Seed a few scripts, rules, and hooks for testing."""
    scenes = [Scene(voiceover="V", visual="V", duration_seconds=10)]
    s1 = db.add_script(conn, topic="AI Tools", hook="What if AI replaced your job?",
                        scenes=scenes, full_script="AI is changing everything.",
                        style="educational", hook_style="question", tags=["ai"])
    db.rate_script(conn, s1.id, "hit", "Strong hook, good pacing")

    s2 = db.add_script(conn, topic="Sleep hacks", hook="You're sleeping wrong.",
                        scenes=scenes, full_script="Here are five sleep tricks.",
                        style="viral", hook_style="shock")
    db.rate_script(conn, s2.id, "miss", "Hook too clickbaity, weak ending")

    s3 = db.add_script(conn, topic="History of coffee", hook="Coffee wasn't always legal.",
                        scenes=scenes, full_script="The history of coffee is wild.",
                        style="story", hook_style="stat")
    db.rate_script(conn, s3.id, "hit", "Great storytelling, visual pacing was perfect")

    db.add_rule(conn, rule="Open with a question or surprising fact", category="hook")
    db.add_rule(conn, rule="Change visuals every 5-8 seconds", category="visual")
    db.add_rule(conn, rule="End with a clear call to action", category="structure")


# --- Write context ---


def test_build_write_context_has_rules(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=60)
    assert "rules" in ctx
    assert len(ctx["rules"]) == 3


def test_build_write_context_has_top_hooks(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=60)
    assert "top_hooks" in ctx
    assert len(ctx["top_hooks"]) > 0


def test_build_write_context_has_feedback_patterns(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=60)
    assert "feedback_patterns" in ctx


def test_build_write_context_has_prompt(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=60)
    assert "prompt" in ctx
    assert "New topic" in ctx["prompt"]
    assert "educational" in ctx["prompt"]


def test_build_write_context_empty_db(conn: sqlite3.Connection) -> None:
    ctx = build_write_context(conn, topic="Fresh start", style="cinematic", duration_target=90)
    assert ctx["rules"] == []
    assert ctx["top_hooks"] == []
    assert "Fresh start" in ctx["prompt"]


# --- Rewrite context ---


def test_build_rewrite_context(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    scripts = db.list_scripts(conn)
    rated_miss = [s for s in scripts if s.rating == "miss"][0]
    ctx = build_rewrite_context(conn, rated_miss.id)
    assert "original_script" in ctx
    assert "feedback" in ctx
    assert "rules" in ctx
    assert "prompt" in ctx
    assert rated_miss.topic in ctx["prompt"]


def test_build_rewrite_context_not_found(conn: sqlite3.Connection) -> None:
    ctx = build_rewrite_context(conn, 999)
    assert ctx is None


# --- Feedback analysis ---


def test_analyze_feedback_patterns(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    patterns = analyze_feedback_patterns(conn)
    assert "hit_notes" in patterns
    assert "miss_notes" in patterns
    assert len(patterns["hit_notes"]) == 2
    assert len(patterns["miss_notes"]) == 1


def test_analyze_feedback_patterns_empty(conn: sqlite3.Connection) -> None:
    patterns = analyze_feedback_patterns(conn)
    assert patterns["hit_notes"] == []
    assert patterns["miss_notes"] == []
