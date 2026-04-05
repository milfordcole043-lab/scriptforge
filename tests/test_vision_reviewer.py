from __future__ import annotations

from pathlib import Path

from scriptforge.models import Character, Scene, SceneReview, TransitionReview, VideoReview
from scriptforge.vision_reviewer import (
    auto_flag_rerender_from_reviews,
    _build_summary,
)


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


# --- SceneReview extended fields ---


def test_scene_review_dimensions() -> None:
    sr = SceneReview(
        scene_index=0, score=7,
        face_consistency=8, outfit_accuracy=6,
        background_aliveness=7, body_language=5, lip_sync_quality=8,
    )
    assert sr.face_consistency == 8
    assert sr.outfit_accuracy == 6
    assert sr.body_language == 5


def test_scene_review_defaults() -> None:
    sr = SceneReview(scene_index=0, score=5)
    assert sr.face_consistency == 0
    assert sr.outfit_accuracy == 0
    assert sr.body_language == 0


# --- TransitionReview ---


def test_transition_review_clean() -> None:
    tr = TransitionReview(from_scene=0, to_scene=1,
                          same_person=True, same_outfit=True, jarring_jump=False)
    assert tr.same_person is True
    assert tr.jarring_jump is False


def test_transition_review_identity_break() -> None:
    tr = TransitionReview(from_scene=1, to_scene=2,
                          same_person=False, same_outfit=True, jarring_jump=True,
                          notes="Face shape changed between scenes")
    assert tr.same_person is False
    assert "Face shape" in tr.notes


# --- Summary builder ---


def test_build_summary_basic() -> None:
    reviews = [
        SceneReview(scene_index=0, score=8, issues=["minor blur"],
                    face_consistency=9, outfit_accuracy=8, background_aliveness=7,
                    body_language=6, lip_sync_quality=8),
        SceneReview(scene_index=1, score=5, issues=["face morphing", "frozen body"],
                    face_consistency=4, outfit_accuracy=7, background_aliveness=5,
                    body_language=3, lip_sync_quality=6),
    ]
    transitions = [
        TransitionReview(from_scene=0, to_scene=1, same_person=True, same_outfit=True),
    ]
    summary = _build_summary(reviews, transitions)
    assert summary["weakest_scene"] == 2
    assert summary["strongest_scene"] == 1
    assert summary["weakest_score"] == 5
    assert summary["strongest_score"] == 8
    assert "dimension_averages" in summary
    assert summary["dimension_averages"]["body_language"] == 4.5


def test_build_summary_with_transition_issues() -> None:
    reviews = [
        SceneReview(scene_index=0, score=7, face_consistency=7, outfit_accuracy=7,
                    background_aliveness=7, body_language=7, lip_sync_quality=7),
        SceneReview(scene_index=1, score=7, face_consistency=7, outfit_accuracy=7,
                    background_aliveness=7, body_language=7, lip_sync_quality=7),
    ]
    transitions = [
        TransitionReview(from_scene=0, to_scene=1, same_person=False, jarring_jump=True),
    ]
    summary = _build_summary(reviews, transitions)
    assert len(summary["transition_issues"]) >= 1
    assert "identity changed" in summary["transition_issues"][0]


def test_build_summary_empty() -> None:
    assert _build_summary([], []) == {}


# --- VideoReview with new fields ---


def test_video_review_with_transitions() -> None:
    sr = [SceneReview(scene_index=0, score=7)]
    tr = [TransitionReview(from_scene=0, to_scene=1)]
    review = VideoReview(script_id=1, scene_reviews=sr, overall_score=7.0,
                          transition_reviews=tr,
                          summary={"weakest_scene": 1, "strongest_scene": 1})
    assert len(review.transition_reviews) == 1
    assert review.summary["weakest_scene"] == 1
