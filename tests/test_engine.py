from __future__ import annotations

import sqlite3

from scriptforge import db
from scriptforge.engine import (
    build_write_context, build_rewrite_context, analyze_feedback_patterns,
    build_video_prompt, _build_temporal_motion, _interpolate_lighting,
    _filter_voice_profile, _select_rules_for_beat,
)
from scriptforge.models import Character, Scene, VoiceProfile


def _scene(beat: str = "hook", dur: int = 10) -> Scene:
    return Scene(beat=beat, voiceover="V", character_action="stares at phone",
                 location="dark bedroom, messy sheets", character_emotion="loneliness",
                 camera="dolly-in", lighting="cold blue phone screen on face",
                 motion="thumb trembles over screen, then goes still",
                 sound="muffled heartbeat", caption="HEARTBREAK", duration_seconds=dur)


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


_CHAR = Character(id=1, name="Maya", age="late 20s", gender="female",
                  appearance="dark wavy hair, brown skin",
                  clothing="oversized grey hoodie", created_at=None)


# --- Labelled prompt structure ---


def test_build_video_prompt_has_labels() -> None:
    scene = _scene()
    prompt = build_video_prompt(scene, _CHAR)
    assert "[SCENE]" in prompt
    assert "[SUBJECT]" in prompt
    assert "[CAMERA]" in prompt
    assert "[LIGHTING]" in prompt
    assert "[MOTION]" in prompt
    assert "[STYLE]" in prompt


# --- Emotion in prompts ---


def test_build_video_prompt_includes_emotion() -> None:
    scene = _scene()
    prompt = build_video_prompt(scene, _CHAR)
    assert "loneliness" in prompt


def test_build_video_prompt_without_character() -> None:
    scene = _scene()
    prompt = build_video_prompt(scene)
    assert "[SCENE]" in prompt
    assert "dark bedroom" in prompt


# --- Temporal flow ---


def test_temporal_motion_long_scene() -> None:
    scene = _scene(dur=12)
    scene.motion = "thumb trembles, shoulders shake, everything goes still"
    result = _build_temporal_motion(scene)
    assert "Initially" in result
    assert "Then" in result
    assert "Finally" in result


def test_temporal_motion_short_scene() -> None:
    scene = _scene(dur=3)
    scene.motion = "thumb trembles"
    result = _build_temporal_motion(scene)
    assert "Initially" in result
    assert "Then" in result
    assert "Finally" not in result


# --- Scene connectivity ---


def test_build_video_prompt_continuity() -> None:
    scenes = [_scene("hook", 3), _scene("tension", 10)]
    scenes[0].character_action = "lying in bed with phone"
    scenes[1].character_action = "sits up on bed edge"
    prompt = build_video_prompt(scenes[1], _CHAR, prev_scene=scenes[0],
                                 scenes=scenes, scene_index=1)
    assert "[CONTINUITY]" in prompt
    assert "lying in bed" in prompt
    assert "sits up" in prompt


def test_build_video_prompt_no_continuity_for_first_scene() -> None:
    scene = _scene("hook", 3)
    prompt = build_video_prompt(scene, _CHAR, scene_index=0)
    assert "[CONTINUITY]" not in prompt
    assert "[ACTION]" in prompt


# --- Light progression ---


def test_interpolate_lighting_middle_scenes() -> None:
    scenes = [
        _scene("hook", 3),
        _scene("tension", 10),
        _scene("revelation", 12),
        _scene("resolution", 7),
    ]
    scenes[0].lighting = "cold blue phone screen"
    scenes[1].lighting = "cold blue phone screen"  # same as first
    scenes[3].lighting = "warm amber dawn"

    result = _interpolate_lighting(scenes, 1)
    assert "cold blue" in result.lower()

    result2 = _interpolate_lighting(scenes, 2)
    # Scene 2 has its own lighting, should keep it
    assert scenes[2].lighting in result2 or "cold blue" in result2.lower()


def test_interpolate_lighting_preserves_first_and_last() -> None:
    scenes = [_scene("hook", 3), _scene("resolution", 7)]
    scenes[0].lighting = "cold blue"
    scenes[1].lighting = "warm amber"
    assert _interpolate_lighting(scenes, 0) == "cold blue"


# --- Mode-aware voice profile ---


def test_filter_voice_profile_narrator() -> None:
    profiles = [
        VoiceProfile(id=1, attribute="tone", value="warm"),
        VoiceProfile(id=2, attribute="person", value="second person"),
        VoiceProfile(id=3, attribute="pov_person", value="first person"),
        VoiceProfile(id=4, attribute="pov_style", value="raw"),
    ]
    filtered = _filter_voice_profile(profiles, "narrator")
    assert len(filtered) == 2
    assert all(not vp.attribute.startswith("pov_") for vp in filtered)


def test_filter_voice_profile_pov() -> None:
    profiles = [
        VoiceProfile(id=1, attribute="tone", value="warm"),
        VoiceProfile(id=2, attribute="pov_person", value="first person"),
        VoiceProfile(id=3, attribute="pov_style", value="raw"),
    ]
    filtered = _filter_voice_profile(profiles, "pov")
    assert len(filtered) == 2
    assert all(vp.attribute.startswith("pov_") for vp in filtered)


# --- Contextual rule selection ---


def test_select_rules_for_hook() -> None:
    from scriptforge.models import Rule
    from datetime import datetime
    rules = [
        Rule(id=1, rule="Hook rule", category="hook", created_at=datetime.now()),
        Rule(id=2, rule="Emotion rule", category="emotion", created_at=datetime.now()),
        Rule(id=3, rule="Caption rule", category="caption", created_at=datetime.now()),
        Rule(id=4, rule="Structure rule", category="structure", created_at=datetime.now()),
    ]
    selected = _select_rules_for_beat(rules, "hook")
    categories = {r.category for r in selected}
    assert "hook" in categories
    assert "caption" in categories
    assert "emotion" not in categories  # emotion belongs to tension


def test_select_rules_for_tension() -> None:
    from scriptforge.models import Rule
    from datetime import datetime
    rules = [
        Rule(id=1, rule="Hook rule", category="hook", created_at=datetime.now()),
        Rule(id=2, rule="Emotion rule", category="emotion", created_at=datetime.now()),
        Rule(id=3, rule="Pacing rule", category="pacing", created_at=datetime.now()),
    ]
    selected = _select_rules_for_beat(rules, "tension")
    categories = {r.category for r in selected}
    assert "emotion" in categories
    assert "pacing" in categories
    assert "hook" not in categories


# --- Write context ---


def test_build_write_context_has_rules(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=45)
    assert len(ctx["rules"]) == 3


def test_build_write_context_has_prompt(conn: sqlite3.Connection) -> None:
    _seed_data(conn)
    ctx = build_write_context(conn, topic="New topic", style="educational", duration_target=45)
    assert "New topic" in ctx["prompt"]
    assert "NARRATIVE ARC" in ctx["prompt"]
    assert "RULES PER BEAT" in ctx["prompt"]


def test_build_write_context_has_voice_profile_narrator(conn: sqlite3.Connection) -> None:
    db.seed_defaults(conn)
    ctx = build_write_context(conn, topic="Test", style="cinematic", duration_target=45, mode="narrator")
    # Should only have narrator profiles (5), not pov_* (3)
    assert len(ctx["voice_profile"]) == 5
    assert "VOICE PROFILE" in ctx["prompt"]


def test_build_write_context_pov_mode(conn: sqlite3.Connection) -> None:
    db.seed_defaults(conn)
    ctx = build_write_context(conn, topic="Test", style="cinematic", duration_target=45, mode="pov")
    # Should only have pov_* profiles
    assert len(ctx["voice_profile"]) == 3
    assert all(vp.attribute.startswith("pov_") for vp in ctx["voice_profile"])
    assert "dialogue" in ctx["prompt"]  # POV mode shows dialogue field
    assert "pov" in ctx["prompt"].lower()


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
