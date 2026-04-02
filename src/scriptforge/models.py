from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Scene:
    voiceover: str
    visual: str
    duration_seconds: int
    transition: str = "cut"


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
    duration_target: int = 60
    word_count: int = 0
    hook_style: str | None = None
    rating: str | None = None
    feedback: str | None = None
    version: int = 1
    parent_id: int | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def scenes_json(self) -> str:
        return json.dumps(
            [{"voiceover": s.voiceover, "visual": s.visual,
              "duration_seconds": s.duration_seconds, "transition": s.transition}
             for s in self.scenes]
        )

    @staticmethod
    def parse_scenes(raw: str) -> list[Scene]:
        data = json.loads(raw)
        return [Scene(**s) for s in data]


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
