from __future__ import annotations

from scriptforge.models import Scene, validate_script


def _make_scene(beat: str = "hook", duration: int = 10, caption: str = "CAPTION",
                character_action: str = "stares at phone", location: str = "dark bedroom",
                lighting: str = "cold blue phone screen") -> Scene:
    return Scene(
        beat=beat, voiceover="Test voiceover", character_action=character_action,
        location=location, character_emotion="wonder", camera="static",
        lighting=lighting, motion="particles drift", sound="low hum",
        caption=caption, duration_seconds=duration,
    )


def _valid_scenes() -> list[Scene]:
    return [
        _make_scene(beat="hook", duration=3),
        _make_scene(beat="tension", duration=10),
        _make_scene(beat="revelation", duration=12),
        _make_scene(beat="resolution", duration=7),
    ]


def test_validate_valid_script() -> None:
    errors = validate_script(_valid_scenes(), "Full script text here.")
    assert errors == []


def test_validate_missing_beat() -> None:
    scenes = [
        _make_scene(beat="hook", duration=3),
        _make_scene(beat="tension", duration=10),
        _make_scene(beat="resolution", duration=12),
    ]
    errors = validate_script(scenes, "Text")
    assert any("revelation" in e for e in errors)


def test_validate_missing_multiple_beats() -> None:
    scenes = [
        _make_scene(beat="hook", duration=10),
        _make_scene(beat="tension", duration=20),
    ]
    errors = validate_script(scenes, "Text")
    assert any("revelation" in e for e in errors)
    assert any("resolution" in e for e in errors)


def test_validate_duration_under_25() -> None:
    scenes = [
        _make_scene(beat="hook", duration=2),
        _make_scene(beat="tension", duration=5),
        _make_scene(beat="revelation", duration=5),
        _make_scene(beat="resolution", duration=3),
    ]
    errors = validate_script(scenes, "Text")
    assert any("under 25s" in e for e in errors)


def test_validate_duration_over_50() -> None:
    scenes = [
        _make_scene(beat="hook", duration=10),
        _make_scene(beat="tension", duration=15),
        _make_scene(beat="revelation", duration=15),
        _make_scene(beat="resolution", duration=15),
    ]
    errors = validate_script(scenes, "Text")
    assert any("exceeds 50s" in e for e in errors)


def test_validate_missing_caption() -> None:
    scenes = _valid_scenes()
    scenes[1] = _make_scene(beat="tension", duration=10, caption="")
    errors = validate_script(scenes, "Text")
    assert any("missing a caption" in e for e in errors)


def test_validate_whitespace_caption() -> None:
    scenes = _valid_scenes()
    scenes[0] = _make_scene(beat="hook", duration=3, caption="   ")
    errors = validate_script(scenes, "Text")
    assert any("missing a caption" in e for e in errors)


def test_validate_exact_boundaries() -> None:
    # 25s total — should pass
    scenes = [
        _make_scene(beat="hook", duration=3),
        _make_scene(beat="tension", duration=8),
        _make_scene(beat="revelation", duration=8),
        _make_scene(beat="resolution", duration=6),
    ]
    assert validate_script(scenes, "Text") == []

    # 50s total — should pass
    scenes = [
        _make_scene(beat="hook", duration=3),
        _make_scene(beat="tension", duration=12),
        _make_scene(beat="revelation", duration=15),
        _make_scene(beat="resolution", duration=20),
    ]
    assert validate_script(scenes, "Text") == []


def test_validate_missing_character_action() -> None:
    scenes = _valid_scenes()
    scenes[0] = _make_scene(beat="hook", duration=3, character_action="")
    errors = validate_script(scenes, "Text")
    assert any("character_action" in e for e in errors)


def test_validate_missing_location() -> None:
    scenes = _valid_scenes()
    scenes[0] = _make_scene(beat="hook", duration=3, location="")
    errors = validate_script(scenes, "Text")
    assert any("location" in e for e in errors)


def test_validate_lighting_no_real_source() -> None:
    scenes = _valid_scenes()
    scenes[0] = _make_scene(beat="hook", duration=3, lighting="dramatic lighting")
    errors = validate_script(scenes, "Text")
    assert any("real light source" in e for e in errors)


def test_validate_lighting_with_real_source() -> None:
    scenes = _valid_scenes()
    errors = validate_script(scenes, "Text")
    assert not any("real light source" in e for e in errors)
