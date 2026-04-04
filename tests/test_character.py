from __future__ import annotations

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from scriptforge import db
from scriptforge.cli import cli
from scriptforge.engine import build_video_prompt
from scriptforge.models import Character, Scene, validate_script


def _invoke(tmp_path: Path, args: list[str] | None = None) -> object:
    runner = CliRunner()
    return runner.invoke(cli, ["--db-path", str(tmp_path / "test.db")] + (args or []))


def _scene(beat: str = "hook", dur: int = 10) -> Scene:
    return Scene(beat=beat, voiceover="V", character_action="stares at phone",
                 location="dark bedroom, messy sheets", character_emotion="loneliness",
                 camera="static", lighting="cold blue phone screen on face",
                 motion="thumb trembles", sound="silence", caption="CAPTION",
                 duration_seconds=dur)


# --- Character CRUD ---


def test_add_character(conn: sqlite3.Connection) -> None:
    char = db.add_character(conn, name="Maya", age="late 20s", gender="female",
                            appearance="dark wavy hair, brown skin, tired eyes",
                            clothing="oversized grey hoodie, black shorts")
    assert char.id is not None
    assert char.name == "Maya"
    assert char.appearance == "dark wavy hair, brown skin, tired eyes"


def test_get_character(conn: sqlite3.Connection) -> None:
    db.add_character(conn, name="Maya", age="late 20s", gender="female",
                     appearance="dark hair", clothing="grey hoodie")
    char = db.get_character(conn, 1)
    assert char is not None
    assert char.name == "Maya"


def test_get_character_not_found(conn: sqlite3.Connection) -> None:
    assert db.get_character(conn, 999) is None


def test_list_characters(conn: sqlite3.Connection) -> None:
    db.add_character(conn, name="Maya", age="late 20s", gender="female",
                     appearance="dark hair", clothing="hoodie")
    db.add_character(conn, name="Alex", age="early 30s", gender="male",
                     appearance="short hair", clothing="t-shirt")
    chars = db.list_characters(conn)
    assert len(chars) == 2


def test_update_character_image(conn: sqlite3.Connection) -> None:
    char = db.add_character(conn, name="Maya", age="late 20s", gender="female",
                            appearance="dark hair", clothing="hoodie")
    assert db.update_character_image(conn, char.id, "/path/to/ref.png") is True
    updated = db.get_character(conn, char.id)
    assert updated.reference_image_path == "/path/to/ref.png"


# --- Character-driven prompt ---


def test_build_video_prompt_with_character() -> None:
    char = Character(id=1, name="Maya", age="late 20s", gender="female",
                     appearance="dark wavy hair, brown skin, tired eyes",
                     clothing="oversized grey hoodie",
                     created_at=None)
    scene = _scene()
    prompt = build_video_prompt(scene, char)
    assert "female" in prompt
    assert "dark wavy hair" in prompt
    assert "grey hoodie" in prompt
    assert "dark bedroom" in prompt
    assert "stares at phone" in prompt
    assert "phone screen" in prompt
    assert "Consistent lighting" in prompt


def test_build_video_prompt_without_character() -> None:
    scene = _scene()
    prompt = build_video_prompt(scene)
    assert "dark bedroom" in prompt
    assert "stares at phone" in prompt
    assert "Consistent lighting" in prompt


# --- Script with character_id ---


def test_add_script_with_character(conn: sqlite3.Connection) -> None:
    char = db.add_character(conn, name="Maya", age="late 20s", gender="female",
                            appearance="dark hair", clothing="hoodie")
    scenes = [_scene("hook", 3), _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7)]
    script = db.add_script(conn, topic="Test", hook="H", scenes=scenes,
                           full_script="Test script", character_id=char.id)
    assert script.character_id == char.id
    fetched = db.get_script(conn, script.id)
    assert fetched.character_id == char.id


# --- Validation ---


def test_validate_missing_character_action() -> None:
    scenes = [
        Scene(beat="hook", voiceover="V", character_action="", location="bedroom",
              character_emotion="sad", camera="static", lighting="cold blue phone screen",
              motion="m", sound="s", caption="CAP", duration_seconds=3),
        _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7),
    ]
    errors = validate_script(scenes, "Text")
    assert any("character_action" in e for e in errors)


def test_validate_missing_location() -> None:
    scenes = [
        Scene(beat="hook", voiceover="V", character_action="stares", location="",
              character_emotion="sad", camera="static", lighting="cold blue phone screen",
              motion="m", sound="s", caption="CAP", duration_seconds=3),
        _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7),
    ]
    errors = validate_script(scenes, "Text")
    assert any("location" in e for e in errors)


def test_validate_lighting_no_real_source() -> None:
    scenes = [
        Scene(beat="hook", voiceover="V", character_action="stares", location="bedroom",
              character_emotion="sad", camera="static", lighting="dramatic lighting",
              motion="m", sound="s", caption="CAP", duration_seconds=3),
        _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7),
    ]
    errors = validate_script(scenes, "Text")
    assert any("real light source" in e for e in errors)


def test_validate_lighting_with_real_source() -> None:
    scenes = [
        _scene("hook", 3), _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7),
    ]
    errors = validate_script(scenes, "Text")
    # phone screen is a real light source — no lighting errors
    assert not any("real light source" in e for e in errors)


# --- CLI character command ---


def test_character_cli(tmp_path: Path) -> None:
    result = _invoke(tmp_path, [
        "character", "Maya", "--age", "late 20s", "--gender", "female",
        "--appearance", "dark wavy hair, brown skin", "--clothing", "grey hoodie",
    ])
    assert result.exit_code == 0
    assert "Character created" in result.output
    assert "Maya" in result.output


def test_characters_list_cli(tmp_path: Path) -> None:
    _invoke(tmp_path, [
        "character", "Maya", "--age", "late 20s", "--gender", "female",
        "--appearance", "dark hair", "--clothing", "hoodie",
    ])
    result = _invoke(tmp_path, ["characters"])
    assert result.exit_code == 0
    assert "Maya" in result.output


# --- Appearance update ---


def test_update_character_appearance(conn: sqlite3.Connection) -> None:
    char = db.add_character(conn, name="Maya", age="late 20s", gender="female",
                            appearance="dark hair", clothing="hoodie")
    db.update_character_appearance(conn, char.id, appearance="dark wavy hair, high cheekbones")
    updated = db.get_character(conn, char.id)
    assert "high cheekbones" in updated.appearance
    assert updated.clothing == "hoodie"  # unchanged


def test_update_character_appearance_clothing_only(conn: sqlite3.Connection) -> None:
    char = db.add_character(conn, name="Maya", age="late 20s", gender="female",
                            appearance="dark hair", clothing="hoodie")
    db.update_character_appearance(conn, char.id, clothing="leather jacket")
    updated = db.get_character(conn, char.id)
    assert updated.appearance == "dark hair"  # unchanged
    assert updated.clothing == "leather jacket"


def test_update_character_wardrobe_dicts(conn: sqlite3.Connection) -> None:
    char = db.add_character(conn, name="Maya", age="late 20s", gender="female",
                            appearance="dark hair", clothing="hoodie")
    wardrobe = [
        {"outfit": "leather jacket over silk camisole", "tones": ["empowering", "intense"]},
        {"outfit": "satin slip dress", "tones": ["empowering", "curious"]},
    ]
    db.update_character_wardrobe(conn, char.id, wardrobe)
    updated = db.get_character(conn, char.id)
    assert len(updated.wardrobe) == 2
    assert updated.wardrobe[0]["tones"] == ["empowering", "intense"]
