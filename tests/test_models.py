from __future__ import annotations

from scriptforge.models import Scene, validate_script


def _make_scene(beat: str = "hook", duration: int = 10, caption: str = "CAPTION") -> Scene:
    return Scene(
        beat=beat, voiceover="Test voiceover", visual="Test visual",
        camera="static", motion="particles drift", sound="low hum",
        emotion="wonder", duration_seconds=duration, caption=caption,
    )


def _valid_scenes() -> list[Scene]:
    return [
        _make_scene(beat="hook", duration=3),
        _make_scene(beat="tension", duration=10),
        _make_scene(beat="revelation", duration=12),
        _make_scene(beat="resolution", duration=7),
    ]


def test_validate_valid_script() -> None:
    scenes = _valid_scenes()
    errors = validate_script(scenes, "Full script text here.")
    assert errors == []


def test_validate_missing_beat() -> None:
    scenes = [
        _make_scene(beat="hook", duration=3),
        _make_scene(beat="tension", duration=10),
        _make_scene(beat="resolution", duration=12),
    ]
    errors = validate_script(scenes, "Text")
    assert len(errors) == 1
    assert "revelation" in errors[0]


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
