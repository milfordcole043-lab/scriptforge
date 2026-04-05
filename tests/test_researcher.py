from __future__ import annotations

import sqlite3
from unittest.mock import patch

from pathlib import Path

from scriptforge import db
from scriptforge.models import Character, PromptRule, Scene
from scriptforge.researcher import grade_prompt, extract_findings_from_text, _enhance_prompt, review_image


def _seed_rules(conn: sqlite3.Connection) -> list[PromptRule]:
    db.seed_defaults(conn)
    return db.get_prompt_rules(conn)


_TEST_CHAR = Character(id=1, name="Maya", age="late 20s", gender="female",
                       appearance="dark wavy hair", clothing="grey hoodie", created_at=None)


def _test_scene(emotion: str = "desperate longing, eyes heavy", camera: str = "static close-up",
                lighting: str = "cold blue phone screen on face",
                action: str = "fingers gripping phone edge") -> Scene:
    return Scene(beat="hook", voiceover="V", character_action=action,
                 location="dark bedroom, messy sheets", character_emotion=emotion,
                 camera=camera, lighting=lighting, motion="thumb trembles",
                 sound="silence", caption="CAP", duration_seconds=5)


# --- Prompt Grading ---


def test_grade_good_prompt(conn: sqlite3.Connection) -> None:
    rules = _seed_rules(conn)
    prompt = (
        "A shattered glass heart falling through dark water, fragments glowing like embers. "
        "Slow dolly-in, moody underwater lighting. Particles drifting outward, trails of red light. "
        "Ambient muffled heartbeat fading. Cinematic, warm amber tones."
    )
    score, missing, enhanced = grade_prompt(prompt, rules)
    assert score >= 70
    assert len(missing) <= 2


def test_grade_bad_prompt(conn: sqlite3.Connection) -> None:
    rules = _seed_rules(conn)
    prompt = "Something happening somewhere."
    score, missing, enhanced = grade_prompt(prompt, rules)
    assert score < 70
    assert len(missing) >= 3
    assert len(enhanced) > len(prompt)


def test_grade_auto_enhance(conn: sqlite3.Connection) -> None:
    rules = _seed_rules(conn)
    prompt = "A heart in dark water."
    score, missing, enhanced = grade_prompt(prompt, rules)
    assert score < 70
    # Enhanced should add missing elements
    assert "dolly" in enhanced.lower() or "cinematic" in enhanced.lower() or "lighting" in enhanced.lower()


def test_grade_perfect_prompt(conn: sqlite3.Connection) -> None:
    rules = _seed_rules(conn)
    prompt = (
        "A silhouette of a person standing in rain, lit by neon light from behind. "
        "Slow tracking shot. Raindrops falling in slow motion, pooling on dark ground. "
        "Ambient rain and distant thunder. Cinematic noir, cold blue desaturated tones."
    )
    score, missing, enhanced = grade_prompt(prompt, rules)
    assert score >= 80


def test_grade_text_in_prompt_penalized(conn: sqlite3.Connection) -> None:
    rules = _seed_rules(conn)
    prompt = (
        "A title card with text reading 'HEARTBREAK' in bold letters. "
        "Static camera. Light fading. Ambient silence. Cinematic, warm amber."
    )
    score, missing, _ = grade_prompt(prompt, rules)
    assert any("avoid" in m for m in missing)


def test_grade_too_long_prompt(conn: sqlite3.Connection) -> None:
    rules = _seed_rules(conn)
    words = " ".join(["word"] * 160)
    prompt = f"A person in a room. Tracking shot. Light fading. Rain ambient. Cinematic noir. Cold blue. {words}"
    score, missing, _ = grade_prompt(prompt, rules)
    assert any("structure" in m for m in missing)


def test_grade_empty_rules() -> None:
    score, missing, enhanced = grade_prompt("Any prompt", [])
    assert score == 100
    assert missing == []


# --- Finding Extraction ---


def test_extract_findings() -> None:
    text = (
        "Always start your hook with a question to grab attention. "
        "Never use more than 15 words in your opening line. "
        "Use tracking shots to create visual momentum in your videos. "
        "This is just some filler text that should not be extracted."
    )
    findings = extract_findings_from_text(text, topic="Video tips", source_url="https://example.com")
    assert len(findings) >= 2
    assert all(f["topic"] == "Video tips" for f in findings)
    assert all(f["source_url"] == "https://example.com" for f in findings)


def test_extract_findings_empty() -> None:
    findings = extract_findings_from_text("This is plain boring text.", topic="Nothing")
    assert findings == []


def test_extract_findings_categories() -> None:
    text = "Always use tracking camera movements for cinematic feel. Never start with a generic hook."
    findings = extract_findings_from_text(text, topic="Tips")
    categories = {f["category"] for f in findings}
    assert len(categories) >= 1


# --- Finding Storage ---


def test_add_and_get_finding(conn: sqlite3.Connection) -> None:
    f = db.add_finding(conn, topic="Test", finding="Use dolly shots", category="camera",
                       source_url="https://example.com", confidence="high")
    assert f.id is not None
    all_f = db.get_findings(conn)
    assert len(all_f) == 1
    assert all_f[0].finding == "Use dolly shots"


def test_get_findings_by_category(conn: sqlite3.Connection) -> None:
    db.add_finding(conn, topic="T", finding="F1", category="camera")
    db.add_finding(conn, topic="T", finding="F2", category="hook")
    camera_findings = db.get_findings(conn, category="camera")
    assert len(camera_findings) == 1


def test_unapplied_findings(conn: sqlite3.Connection) -> None:
    db.add_finding(conn, topic="T", finding="F1", category="hook")
    db.add_finding(conn, topic="T", finding="F2", category="camera")
    unapplied = db.get_unapplied_findings(conn)
    assert len(unapplied) == 2
    db.mark_finding_applied(conn, unapplied[0].id)
    unapplied = db.get_unapplied_findings(conn)
    assert len(unapplied) == 1


# --- Prompt Rules ---


def test_seed_prompt_rules(conn: sqlite3.Connection) -> None:
    db.seed_defaults(conn)
    rules = db.get_prompt_rules(conn)
    assert len(rules) == 20


def test_add_prompt_rule(conn: sqlite3.Connection) -> None:
    rule = db.add_prompt_rule(conn, element="custom", rule="My custom rule", weight=7)
    assert rule.id is not None
    assert rule.weight == 7


# --- YouTube Transcript ---


def test_pull_transcript_bad_url() -> None:
    from scriptforge.researcher import pull_youtube_transcript
    result = pull_youtube_transcript("not-a-url")
    assert result is None


# --- Image Quality Review ---


def test_review_good_scene() -> None:
    scene = _test_scene()
    score, issues, adj = review_image(Path("fake.png"), _TEST_CHAR, scene)
    assert score >= 7
    assert len(issues) == 0


def test_review_generic_emotion() -> None:
    scene = _test_scene(emotion="sad")
    score, issues, adj = review_image(Path("fake.png"), _TEST_CHAR, scene)
    assert score < 10
    assert any("generic" in i.lower() for i in issues)


def test_review_unanchored_hands() -> None:
    scene = _test_scene(action="hands moving in empty space")
    score, issues, adj = review_image(Path("fake.png"), _TEST_CHAR, scene)
    assert any("anchor" in i.lower() for i in issues)


def test_review_missing_camera() -> None:
    scene = _test_scene(camera="")
    score, issues, adj = review_image(Path("fake.png"), _TEST_CHAR, scene)
    assert any("camera" in i.lower() for i in issues)


def test_review_vague_lighting() -> None:
    scene = _test_scene(lighting="light")
    score, issues, adj = review_image(Path("fake.png"), _TEST_CHAR, scene)
    assert any("lighting" in i.lower() for i in issues)


def test_review_returns_adjustment() -> None:
    scene = _test_scene(emotion="sad", camera="", lighting="dim")
    score, issues, adj = review_image(Path("fake.png"), _TEST_CHAR, scene)
    assert len(adj) > 0
    assert adj != "No adjustments needed"
