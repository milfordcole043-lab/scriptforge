from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

VALID_BEATS = {"hook", "tension", "revelation", "resolution"}
VALID_CAMERAS = {"dolly-in", "tracking", "crane", "handheld", "whip pan", "static", "orbital"}


@dataclass
class Scene:
    beat: str
    voiceover: str
    visual: str
    camera: str
    motion: str
    sound: str
    emotion: str
    duration_seconds: int
    caption: str


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
    tags: list[str] = field(default_factory=list)

    @property
    def scenes_json(self) -> str:
        return json.dumps(
            [{"beat": s.beat, "voiceover": s.voiceover, "visual": s.visual,
              "camera": s.camera, "motion": s.motion, "sound": s.sound,
              "emotion": s.emotion, "duration_seconds": s.duration_seconds,
              "caption": s.caption}
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

    return errors
