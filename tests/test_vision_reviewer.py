from __future__ import annotations

from pathlib import Path

from scriptforge.models import Character, Scene, SceneReview, VideoReview
from scriptforge.vision_reviewer import auto_flag_rerender_from_reviews, extract_scene_frames


def _scene(beat: str = "hook", dur: int = 10) -> Scene:
    return Scene(beat=beat, voiceover="V", character_action="stares at phone",
                 location="dark bedroom", character_emotion="loneliness",
                 camera="static", lighting="cold blue phone screen",
                 motion="thumb trembles", sound="silence", caption="CAP",
                 duration_seconds=dur)


# --- Auto-flag re-render ---


def test_auto_flag_low_score() -> None:
    reviews = [
        SceneReview(scene_index=0, score=8, issues=[]),
        SceneReview(scene_index=1, score=4, issues=["bad lighting"]),
        SceneReview(scene_index=2, score=7, issues=[]),
    ]
    flagged = auto_flag_rerender_from_reviews(reviews)
    assert flagged == [1]


def test_auto_flag_critical_issues() -> None:
    reviews = [
        SceneReview(scene_index=0, score=7, issues=["morphing face detected"]),
        SceneReview(scene_index=1, score=8, issues=["slight blur"]),
    ]
    flagged = auto_flag_rerender_from_reviews(reviews)
    assert flagged == [0]


def test_auto_flag_extra_fingers() -> None:
    reviews = [
        SceneReview(scene_index=0, score=7, issues=["extra finger on left hand"]),
    ]
    flagged = auto_flag_rerender_from_reviews(reviews)
    assert flagged == [0]


def test_auto_flag_none_needed() -> None:
    reviews = [
        SceneReview(scene_index=0, score=8, issues=[]),
        SceneReview(scene_index=1, score=9, issues=["minor color shift"]),
    ]
    flagged = auto_flag_rerender_from_reviews(reviews)
    assert flagged == []


def test_auto_flag_multiple() -> None:
    reviews = [
        SceneReview(scene_index=0, score=3, issues=["distorted face"]),
        SceneReview(scene_index=1, score=9, issues=[]),
        SceneReview(scene_index=2, score=5, issues=[]),
        SceneReview(scene_index=3, score=2, issues=["garbled text in background"]),
    ]
    flagged = auto_flag_rerender_from_reviews(reviews)
    assert 0 in flagged
    assert 2 in flagged
    assert 3 in flagged
    assert 1 not in flagged


# --- VideoReview dataclass ---


def test_video_review_creation() -> None:
    sr = [SceneReview(scene_index=0, score=8), SceneReview(scene_index=1, score=6)]
    review = VideoReview(script_id=1, scene_reviews=sr, overall_score=7.0,
                          sync_issues=["word cut at transition"], rerender_needed=[1])
    assert review.overall_score == 7.0
    assert len(review.rerender_needed) == 1
    assert review.sync_issues[0] == "word cut at transition"
