from __future__ import annotations

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from scriptforge import db
from scriptforge.cli import cli
from scriptforge.engine import build_pov_video_prompt, build_pov_reference_prompt
from scriptforge.models import Character, Scene, Script


def _invoke(tmp_path: Path, args: list[str] | None = None) -> object:
    runner = CliRunner()
    return runner.invoke(cli, ["--db-path", str(tmp_path / "test.db")] + (args or []))


def _pov_scene(beat: str = "hook", dur: int = 5, dialogue: str = "I can't sleep.") -> Scene:
    return Scene(beat=beat, voiceover="", character_action="stares at phone camera",
                 location="dark bedroom", character_emotion="loneliness",
                 camera="static close-up", lighting="cold blue phone screen on face",
                 motion="barely any movement", sound="silence",
                 caption="CAN'T SLEEP", duration_seconds=dur, dialogue=dialogue)


def _seed_pov_script(tmp_path: Path) -> int:
    conn = db.connect(tmp_path / "test.db")
    char = db.add_character(conn, name="Maya", age="late 20s", gender="female",
                            appearance="dark wavy hair, brown skin",
                            clothing="oversized grey hoodie")
    scenes = [
        _pov_scene("hook", 3, "It's 3 AM again."),
        _pov_scene("tension", 10, "My chest hurts. I can't eat. I can't sleep."),
        _pov_scene("revelation", 10, "Same brain pattern as withdrawal. That's what this is."),
        _pov_scene("resolution", 7, "It's just chemistry. Chemistry changes."),
    ]
    script = db.add_script(
        conn, topic="Heartbreak POV", hook="It's 3 AM.",
        scenes=scenes, full_script=" ".join(s.dialogue for s in scenes),
        style="cinematic", duration_target=30, character_id=char.id, mode="pov",
    )
    conn.close()
    return script.id


# --- Mode detection ---


def _valid_pov_scenes() -> list[Scene]:
    return [
        _pov_scene("hook", 3, "It's 3 AM."),
        _pov_scene("tension", 10, "My chest hurts."),
        _pov_scene("revelation", 10, "It's cocaine withdrawal."),
        _pov_scene("resolution", 7, "Chemistry changes."),
    ]


def test_pov_mode_detection(conn: sqlite3.Connection) -> None:
    scenes = _valid_pov_scenes()
    script = db.add_script(conn, topic="POV test", hook="H", scenes=scenes,
                           full_script="Test", mode="pov")
    assert script.mode == "pov"
    fetched = db.get_script(conn, script.id)
    assert fetched.mode == "pov"


def test_narrator_mode_default(conn: sqlite3.Connection) -> None:
    scenes = _valid_pov_scenes()
    script = db.add_script(conn, topic="Narrator test", hook="H", scenes=scenes,
                           full_script="Test")
    assert script.mode == "narrator"


# --- Dialogue field ---


def test_dialogue_field_in_scene(conn: sqlite3.Connection) -> None:
    scenes = [
        _pov_scene("hook", 3, "I can't believe this is happening."),
        _pov_scene("tension", 10, "Tension."),
        _pov_scene("revelation", 10, "Revelation."),
        _pov_scene("resolution", 7, "Resolution."),
    ]
    script = db.add_script(conn, topic="Dialogue test", hook="H", scenes=scenes,
                           full_script="Test", mode="pov")
    fetched = db.get_script(conn, script.id)
    assert fetched.scenes[0].dialogue == "I can't believe this is happening."


def test_dialogue_empty_for_narrator(conn: sqlite3.Connection) -> None:
    scenes = [
        _pov_scene("hook", 3, ""),
        _pov_scene("tension", 10, ""),
        _pov_scene("revelation", 10, ""),
        _pov_scene("resolution", 7, ""),
    ]
    script = db.add_script(conn, topic="No dialogue", hook="H", scenes=scenes,
                           full_script="Test")
    fetched = db.get_script(conn, script.id)
    assert fetched.scenes[0].dialogue == ""


# --- POV prompt builders ---


def test_pov_video_prompt() -> None:
    char = Character(id=1, name="Maya", age="late 20s", gender="female",
                     appearance="dark wavy hair, brown skin",
                     clothing="oversized grey hoodie", created_at=None)
    scene = _pov_scene()
    prompt = build_pov_video_prompt(scene, char)
    assert "Talking directly to camera" in prompt
    assert "eyes locked on camera lens" in prompt
    assert "lip movement" in prompt
    assert "phone camera" in prompt.lower()
    assert "dark wavy hair" in prompt
    assert "Consistent lighting" in prompt


def test_pov_reference_prompt_with_emotion() -> None:
    char = Character(id=1, name="Maya", age="late 20s", gender="female",
                     appearance="dark wavy hair, brown skin",
                     clothing="grey hoodie", created_at=None)
    prompt = build_pov_reference_prompt(char, "cold blue phone screen",
                                        "exhausted, eyes heavy, like she has been crying")
    assert "teeth" in prompt.lower()
    assert "selfie" in prompt.lower()
    assert "exhausted" in prompt.lower()
    assert "dark wavy hair" in prompt
    assert "eye contact" in prompt.lower() or "looking directly into camera" in prompt.lower()


def test_pov_reference_prompt_default_emotion() -> None:
    char = Character(id=1, name="Maya", age="late 20s", gender="female",
                     appearance="dark hair", clothing="hoodie", created_at=None)
    prompt = build_pov_reference_prompt(char)
    # No hook_emotion provided — should use empowering tone default
    assert "confident" in prompt.lower()
    assert "Soft warm lighting" in prompt


def test_pov_reference_prompt_default_lighting() -> None:
    char = Character(id=1, name="Maya", age="late 20s", gender="female",
                     appearance="dark hair", clothing="hoodie", created_at=None)
    prompt = build_pov_reference_prompt(char, hook_emotion="tired and drained")
    assert "Soft warm lighting" in prompt
    assert "tired" in prompt.lower()


# --- ASS subtitle formatting ---


def test_ass_time_format() -> None:
    from scriptforge.pov_pipeline import _format_ass_time
    assert _format_ass_time(0.0) == "0:00:00.00"
    assert _format_ass_time(1.5) == "0:00:01.50"
    assert _format_ass_time(65.25) == "0:01:05.25"
    assert _format_ass_time(3661.0) == "1:01:01.00"


# --- Dry run ---


def test_pov_dry_run(tmp_path: Path) -> None:
    script_id = _seed_pov_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert result.exit_code == 0
    assert "POV" in result.output
    assert "lip-sync" in result.output.lower() or "Fabric" in result.output
    assert "Maya" in result.output


def test_pov_dry_run_shows_dialogue(tmp_path: Path) -> None:
    script_id = _seed_pov_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "3 AM" in result.output
    assert "chest" in result.output or "phone" in result.output


def test_pov_dry_run_shows_cost(tmp_path: Path) -> None:
    script_id = _seed_pov_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "$" in result.output


def test_pov_dry_run_shows_steps(tmp_path: Path) -> None:
    script_id = _seed_pov_script(tmp_path)
    result = _invoke(tmp_path, ["render", str(script_id), "--dry-run"])
    assert "voiceover" in result.output.lower()
    assert "chunk" in result.output.lower()
    assert "Whisper" in result.output
    assert "reference portrait" in result.output.lower()


# --- Narrator routing still works ---


def test_narrator_mode_routing(tmp_path: Path) -> None:
    """Narrator mode scripts should NOT trigger POV pipeline."""
    conn = db.connect(tmp_path / "test.db")
    char = db.add_character(conn, name="Test", age="30s", gender="male",
                            appearance="short hair", clothing="t-shirt")
    def _ns(beat, dur):
        return Scene(beat=beat, voiceover="V", character_action="walks",
                     location="street", character_emotion="calm", camera="tracking",
                     lighting="golden hour sunlight", motion="walking forward",
                     sound="traffic", caption="CAP", duration_seconds=dur)
    scenes = [_ns("hook", 3), _ns("tension", 10), _ns("revelation", 12), _ns("resolution", 7)]
    db.add_script(conn, topic="Narrator test", hook="H",
                  scenes=scenes, full_script="Test narrator",
                  character_id=char.id, mode="narrator")
    conn.close()
    result = _invoke(tmp_path, ["render", "1", "--dry-run"])
    assert "POV" not in result.output
    assert "DRY RUN" in result.output


# --- Seed defaults ---


def test_pov_rules_seeded(conn: sqlite3.Connection) -> None:
    db.seed_defaults(conn)
    rules = db.get_active_rules(conn)
    pov_rules = [r for r in rules if r.category == "pov"]
    assert len(pov_rules) == 7


def test_pov_voice_profile_seeded(conn: sqlite3.Connection) -> None:
    db.seed_defaults(conn)
    profile = db.get_voice_profile(conn)
    attrs = {vp.attribute for vp in profile}
    assert "pov_person" in attrs
    assert "pov_style" in attrs
    assert "pov_pacing" in attrs


# --- Gaze direction in continuity ---


def test_pov_video_prompt_continuity_has_gaze() -> None:
    char = Character(id=1, name="Maya", age="late 20s", gender="female",
                     appearance="dark wavy hair", clothing="hoodie", created_at=None)
    prev = _pov_scene(beat="hook", dur=3)
    scene = _pov_scene(beat="tension", dur=8)
    prompt = build_pov_video_prompt(scene, char, prev_scene=prev, scene_index=1)
    assert "Eyes remain focused on camera" in prompt


# --- Sub-chunk splitting ---


def test_split_long_chunk(tmp_path: Path) -> None:
    from pydub import AudioSegment
    from pydub.generators import Sine
    from scriptforge.pov_pipeline import _split_long_chunk

    # Create a 10-second sine wave audio
    audio = Sine(440).to_audio_segment(duration=10000)
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    chunk_path = chunk_dir / "chunk_01.mp3"
    audio.export(str(chunk_path), format="mp3")

    # Should split into 2 sub-chunks (10s / 7s max = 2 parts)
    result = _split_long_chunk(chunk_path, 7.0, tmp_path, 1)
    assert len(result) == 2
    assert all(p.exists() for p in result)


def test_split_short_chunk_not_split(tmp_path: Path) -> None:
    from pydub import AudioSegment
    from pydub.generators import Sine
    from scriptforge.pov_pipeline import _split_long_chunk

    # Create a 5-second audio — under threshold
    audio = Sine(440).to_audio_segment(duration=5000)
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    chunk_path = chunk_dir / "chunk_01.mp3"
    audio.export(str(chunk_path), format="mp3")

    result = _split_long_chunk(chunk_path, 7.0, tmp_path, 1)
    assert len(result) == 1
    assert result[0] == chunk_path


def test_gaze_prompt_rule_seeded(conn: sqlite3.Connection) -> None:
    db.seed_defaults(conn)
    rules = db.get_prompt_rules(conn)
    gaze_rules = [r for r in rules if r.element == "lipsync_gaze"]
    assert len(gaze_rules) == 1
    assert "eye contact" in gaze_rules[0].rule.lower()
