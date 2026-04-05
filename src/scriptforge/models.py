from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

VALID_BEATS = {"hook", "tension", "revelation", "resolution"}


def get_valid_beats(template: StoryTemplate | None = None) -> set[str]:
    """Return valid beat names — from template if provided, else default 4-beat arc."""
    if template is None:
        return VALID_BEATS
    return {b["beat"] for b in template.beat_structure}
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
    wardrobe: list[dict] = field(default_factory=list)


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
    template_id: int | None = None
    mode: str = "narrator"
    tone: str = "empowering"
    outfit: str | None = None
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
        import dataclasses
        fields = {f.name: f for f in dataclasses.fields(Scene)}
        data = json.loads(raw)
        scenes = []
        for s in data:
            filtered = {k: v for k, v in s.items() if k in fields}
            # Fill missing required fields with safe defaults
            for name, f in fields.items():
                if name not in filtered and f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                    filtered[name] = 0 if f.type == "int" else ""
            scenes.append(Scene(**filtered))
        return scenes

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
    face_consistency: int = 0
    outfit_accuracy: int = 0
    background_aliveness: int = 0
    body_language: int = 0
    lip_sync_quality: int = 0


@dataclass
class TransitionReview:
    from_scene: int
    to_scene: int
    same_person: bool = True
    same_outfit: bool = True
    jarring_jump: bool = False
    notes: str = ""


@dataclass
class VideoReview:
    script_id: int
    scene_reviews: list[SceneReview]
    overall_score: float
    sync_issues: list[str] = field(default_factory=list)
    rerender_needed: list[int] = field(default_factory=list)
    transition_reviews: list[TransitionReview] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
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


@dataclass
class StoryTemplate:
    id: int
    name: str
    description: str
    beat_structure: list[dict]
    matching_keywords: list[str]
    visual_style: str
    success_rate: float = 0.0
    times_used: int = 0
    created_at: datetime | None = None


VALID_TONES = {"empowering", "vulnerable", "curious", "intense"}
BLOCKED_EMPOWERING_EMOTIONS = {"desperate", "devastated", "hopeless", "broken", "damaged"}
WPM_DEFAULT = 130


def validate_script(scenes: list[Scene], full_script: str,
                    template: StoryTemplate | None = None,
                    max_scene_duration: int | None = None,
                    tone: str | None = None,
                    wpm: int = WPM_DEFAULT) -> list[str]:
    """Validate a script against narrative arc rules. Returns list of errors."""
    errors: list[str] = []

    # Check all beats present (template-specific or default 4-beat)
    expected_beats = get_valid_beats(template)
    beats = {s.beat for s in scenes}
    missing = expected_beats - beats
    if missing:
        errors.append(f"Missing beats: {', '.join(sorted(missing))}")

    # Check per-scene duration cap (POV mode)
    if max_scene_duration:
        for i, s in enumerate(scenes):
            if s.duration_seconds > max_scene_duration:
                errors.append(f"Scene {i + 1} ({s.beat}) is {s.duration_seconds}s, max is {max_scene_duration}s")

    # Check per-scene word count fits duration (prevents voiceover bloat)
    for i, s in enumerate(scenes):
        text = s.dialogue if s.dialogue else s.voiceover
        if text:
            words = len(text.split())
            max_words = int(s.duration_seconds * wpm / 60 * 1.3)  # 30% tolerance
            if words > max_words:
                errors.append(
                    f"Scene {i + 1} ({s.beat}) has {words} words but {s.duration_seconds}s "
                    f"only fits ~{max_words} words at {wpm} WPM")

    # Check tone-emotion alignment (empowering rejects desperate/hopeless)
    if tone == "empowering":
        for i, s in enumerate(scenes):
            emotion_lower = (s.character_emotion or "").lower()
            for blocked in BLOCKED_EMPOWERING_EMOTIONS:
                if blocked in emotion_lower:
                    errors.append(
                        f"Scene {i + 1} ({s.beat}) emotion '{s.character_emotion}' "
                        f"conflicts with empowering tone (contains '{blocked}')")

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
