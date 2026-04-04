from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from scriptforge import db
from scriptforge.cli import cli
from scriptforge.models import Scene


def _invoke(tmp_path: Path, args: list[str] | None = None, input_text: str = "") -> object:
    runner = CliRunner()
    return runner.invoke(cli, ["--db-path", str(tmp_path / "test.db")] + (args or []),
                          input=input_text)


def _scene(beat: str = "hook", dur: int = 10) -> Scene:
    return Scene(beat=beat, voiceover="V", character_action="stares at phone",
                 location="dark bedroom", character_emotion="loneliness",
                 camera="static close-up", lighting="cold blue phone screen",
                 motion="thumb trembles", sound="silence", caption="CAP",
                 duration_seconds=dur)


def _valid_scenes() -> list[Scene]:
    return [_scene("hook", 3), _scene("tension", 10), _scene("revelation", 12), _scene("resolution", 7)]


# --- Scene feedback storage ---


def test_save_and_get_scene_feedback(conn: sqlite3.Connection) -> None:
    scenes = _valid_scenes()
    script = db.add_script(conn, topic="Test", hook="H", scenes=scenes, full_script="Test")
    sf = db.save_scene_feedback(conn, script.id, 0, visual_quality=4, emotional_impact=5,
                                 pacing=3, lip_sync=None, notes="Good hook")
    assert sf.id is not None
    assert sf.visual_quality == 4

    entries = db.get_scene_feedback(conn, script.id)
    assert len(entries) == 1
    assert entries[0].notes == "Good hook"


def test_multiple_scene_feedback(conn: sqlite3.Connection) -> None:
    scenes = _valid_scenes()
    script = db.add_script(conn, topic="Test", hook="H", scenes=scenes, full_script="Test")
    for i in range(4):
        db.save_scene_feedback(conn, script.id, i, visual_quality=3 + i % 2,
                                emotional_impact=4, pacing=3)
    entries = db.get_scene_feedback(conn, script.id)
    assert len(entries) == 4


def test_scene_feedback_with_lip_sync(conn: sqlite3.Connection) -> None:
    scenes = _valid_scenes()
    script = db.add_script(conn, topic="POV", hook="H", scenes=scenes, full_script="T", mode="pov")
    db.save_scene_feedback(conn, script.id, 0, visual_quality=4, emotional_impact=5,
                            pacing=3, lip_sync=4, notes="Good sync")
    entries = db.get_scene_feedback(conn, script.id)
    assert entries[0].lip_sync == 4


# --- Video review storage ---


def test_save_and_get_video_review(conn: sqlite3.Connection) -> None:
    from scriptforge.models import SceneReview, VideoReview
    scenes = _valid_scenes()
    script = db.add_script(conn, topic="Review test", hook="H", scenes=scenes, full_script="T")
    review = VideoReview(
        script_id=script.id,
        scene_reviews=[
            SceneReview(scene_index=0, score=8, issues=["minor blur"], suggestions=["add sharpening"]),
            SceneReview(scene_index=1, score=6, issues=["face morph"], suggestions=["re-render"]),
        ],
        overall_score=7.0,
    )
    db.save_video_review(conn, review)
    reviews = db.get_video_reviews(conn, script.id)
    assert len(reviews) == 2
    assert reviews[0]["score"] == 8
    assert "minor blur" in reviews[0]["issues"]


# --- Analyze scene feedback ---


def test_analyze_insufficient_data(conn: sqlite3.Connection) -> None:
    result = db.analyze_scene_feedback(conn)
    assert result["patterns"] == []
    assert result["total_feedback"] < 5


def test_analyze_with_data(conn: sqlite3.Connection) -> None:
    scenes = _valid_scenes()
    # Create 5 scripts with feedback for sufficient data
    for i in range(5):
        script = db.add_script(conn, topic=f"Test {i}", hook="H", scenes=scenes, full_script="T")
        for j in range(4):
            db.save_scene_feedback(conn, script.id, j,
                                    visual_quality=3 + j % 2, emotional_impact=4,
                                    pacing=3 + i % 2)
    result = db.analyze_scene_feedback(conn)
    assert result["total_feedback"] >= 5
    assert len(result["patterns"]) > 0


# --- CLI feedback command ---


def test_feedback_empty(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["feedback", "999"])
    assert "No scene feedback" in result.output


def test_reviews_empty(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["reviews"])
    assert "No video reviews" in result.output
