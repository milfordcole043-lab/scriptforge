from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

VALID_BEATS = {"hook", "tension", "revelation", "resolution"}
VALID_CAMERAS = {"dolly-in", "tracking", "crane", "handheld", "whip pan", "static", "orbital"}
REAL_LIGHT_SOURCES = {
    "phone", "screen", "neon", "candle", "candlelight", "lamp", "dawn", "sunset",
    "streetlight", "street lamp", "moonlight", "window", "fluorescent", "fire",
    "golden hour", "god rays", "backlit", "sun", "led", "lantern",
}


@dataclass
class Character:
    id: int
    name: str
    age: str
    gender: str
    appearance: str
    clothing: str
    created_at: datetime | None = None
    reference_image_path: str | None = None


@dataclass
class Scene:
    beat: str
    voiceover: str
    character_action: str
    location: str
    character_emotion: str
    camera: str
    lighting: str
    motion: str
    sound: str
    caption: str
    duration_seconds: int
    dialogue: str = ""


@dataclass
class Script:
    id: int
    topic: str
    hook: str
    scenes: list[Scene]
    full_script: str
    created_at: datetime
    angle: str | None = None
    style: str = "educational"
    duration_target: int = 45
    word_count: int = 0
    rating: str | None = None
    feedback: str | None = None
    version: int = 1
    parent_id: int | None = None
    character_id: int | None = None
    mode: str = "narrator"
    tags: list[str] = field(default_factory=list)

    @property
    def scenes_json(self) -> str:
        return json.dumps(
            [{"beat": s.beat, "voiceover": s.voiceover,
              "character_action": s.character_action, "location": s.location,
              "character_emotion": s.character_emotion, "camera": s.camera,
              "lighting": s.lighting, "motion": s.motion, "sound": s.sound,
              "caption": s.caption, "duration_seconds": s.duration_seconds,
              "dialogue": s.dialogue}
             for s in self.scenes]
        )

    @staticmethod
    def parse_scenes(raw: str) -> list[Scene]:
        data = json.loads(raw)
        return [Scene(**s) for s in data]

    @property
    def total_duration(self) -> int:
        return sum(s.duration_seconds for s in self.scenes)


@dataclass
class Hook:
    id: int
    text: str
    created_at: datetime
    script_id: int | None = None
    rating: str | None = None
    style: str | None = None


@dataclass
class Rule:
    id: int
    rule: str
    created_at: datetime
    source: str | None = None
    category: str | None = None
    active: bool = True


@dataclass
class FeedbackEntry:
    id: int
    script_id: int
    rating: str
    notes: str
    created_at: datetime


@dataclass
class VoiceProfile:
    id: int
    attribute: str
    value: str
    active: bool = True


@dataclass
class Finding:
    id: int
    topic: str
    finding: str
    category: str
    created_at: datetime
    source_url: str | None = None
    source_title: str | None = None
    confidence: str = "medium"
    applied: bool = False


@dataclass
class PromptRule:
    id: int
    element: str
    rule: str
    weight: int
    created_at: datetime
    source: str | None = None
    active: bool = True


@dataclass
class SceneReview:
    scene_index: int
    score: int
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class VideoReview:
    script_id: int
    scene_reviews: list[SceneReview]
    overall_score: float
    sync_issues: list[str] = field(default_factory=list)
    rerender_needed: list[int] = field(default_factory=list)
    created_at: datetime | None = None


@dataclass
class SceneFeedback:
    id: int
    script_id: int
    scene_index: int
    visual_quality: int
    emotional_impact: int
    pacing: int
    lip_sync: int | None = None
    notes: str = ""
    created_at: datetime | None = None


def validate_script(scenes: list[Scene], full_script: str) -> list[str]:
    """Validate a script against narrative arc rules. Returns list of errors."""
    errors: list[str] = []

    # Check all 4 beats present
    beats = {s.beat for s in scenes}
    missing = VALID_BEATS - beats
    if missing:
        errors.append(f"Missing beats: {', '.join(sorted(missing))}")

    # Check duration bounds
    total = sum(s.duration_seconds for s in scenes)
    if total < 25:
        errors.append(f"Total duration {total}s is under 25s minimum")
    if total > 50:
        errors.append(f"Total duration {total}s exceeds 50s maximum")

    # Check captions
    for i, s in enumerate(scenes):
        if not s.caption or not s.caption.strip():
            errors.append(f"Scene {i + 1} ({s.beat}) is missing a caption")

    # Check character_action and location
    for i, s in enumerate(scenes):
        if not s.character_action or not s.character_action.strip():
            errors.append(f"Scene {i + 1} ({s.beat}) is missing character_action")
        if not s.location or not s.location.strip():
            errors.append(f"Scene {i + 1} ({s.beat}) is missing location")

    # Check lighting has a real light source
    for i, s in enumerate(scenes):
        lighting_lower = (s.lighting or "").lower()
        if not any(source in lighting_lower for source in REAL_LIGHT_SOURCES):
            errors.append(f"Scene {i + 1} ({s.beat}) lighting must name a real light source")

    return errors
