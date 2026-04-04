from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from scriptforge.models import (
    Character, FeedbackEntry, Finding, Hook, PromptRule, Rule, Scene,
    SceneFeedback, SceneReview, Script, StoryTemplate, VideoReview,
    VoiceProfile, validate_script,
)

DEFAULT_DB = Path.home() / ".scriptforge" / "scriptforge.db"

_CREATE_SCRIPTS = """
CREATE TABLE IF NOT EXISTS scripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT    NOT NULL,
    angle           TEXT,
    style           TEXT    DEFAULT 'educational',
    duration_target INTEGER DEFAULT 45,
    hook            TEXT    NOT NULL,
    hook_style      TEXT,
    scenes          TEXT    NOT NULL,
    full_script     TEXT,
    word_count      INTEGER DEFAULT 0,
    rating          TEXT,
    feedback        TEXT,
    version         INTEGER DEFAULT 1,
    parent_id       INTEGER,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES scripts(id)
);
"""

_CREATE_HOOKS = """
CREATE TABLE IF NOT EXISTS hooks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT    NOT NULL,
    script_id  INTEGER,
    rating     TEXT,
    style      TEXT,
    created_at TEXT    NOT NULL,
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);
"""

_CREATE_RULEBOOK = """
CREATE TABLE IF NOT EXISTS rulebook (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    rule       TEXT    NOT NULL,
    source     TEXT,
    category   TEXT,
    active     INTEGER DEFAULT 1,
    created_at TEXT    NOT NULL
);
"""

_CREATE_FEEDBACK_LOG = """
CREATE TABLE IF NOT EXISTS feedback_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id  INTEGER NOT NULL,
    rating     TEXT    NOT NULL,
    notes      TEXT,
    created_at TEXT    NOT NULL,
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);
"""

_CREATE_SCRIPT_TAGS = """
CREATE TABLE IF NOT EXISTS script_tags (
    script_id INTEGER NOT NULL,
    tag       TEXT    NOT NULL,
    PRIMARY KEY (script_id, tag),
    FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE
);
"""

_CREATE_VOICE_PROFILE = """
CREATE TABLE IF NOT EXISTS voice_profile (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    attribute  TEXT    NOT NULL UNIQUE,
    value      TEXT    NOT NULL,
    active     INTEGER DEFAULT 1,
    created_at TEXT    NOT NULL
);
"""

_CREATE_RESEARCH_FINDINGS = """
CREATE TABLE IF NOT EXISTS research_findings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT    NOT NULL,
    source_url   TEXT,
    source_title TEXT,
    finding      TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    confidence   TEXT    DEFAULT 'medium',
    applied      INTEGER DEFAULT 0,
    created_at   TEXT    NOT NULL
);
"""

_CREATE_PROMPT_RULES = """
CREATE TABLE IF NOT EXISTS prompt_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    element    TEXT    NOT NULL,
    rule       TEXT    NOT NULL,
    weight     INTEGER DEFAULT 5,
    source     TEXT,
    active     INTEGER DEFAULT 1,
    created_at TEXT    NOT NULL
);
"""

_CREATE_CHARACTER_PROFILES = """
CREATE TABLE IF NOT EXISTS character_profiles (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    NOT NULL,
    age                  TEXT    NOT NULL,
    gender               TEXT    NOT NULL,
    appearance           TEXT    NOT NULL,
    clothing             TEXT    NOT NULL,
    reference_image_path TEXT,
    created_at           TEXT    NOT NULL
);
"""

_CREATE_RENDER_LOG = """
CREATE TABLE IF NOT EXISTS render_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id        INTEGER NOT NULL,
    step             TEXT    NOT NULL,
    model            TEXT    NOT NULL,
    duration_seconds REAL    DEFAULT 0,
    estimated_cost   REAL    DEFAULT 0,
    status           TEXT    NOT NULL,
    created_at       TEXT    NOT NULL,
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);
"""

_CREATE_VIDEO_REVIEWS = """
CREATE TABLE IF NOT EXISTS video_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id   INTEGER NOT NULL,
    scene_index INTEGER NOT NULL,
    score       INTEGER NOT NULL,
    issues      TEXT    DEFAULT '[]',
    suggestions TEXT    DEFAULT '[]',
    created_at  TEXT    NOT NULL,
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);
"""

_CREATE_SCENE_FEEDBACK = """
CREATE TABLE IF NOT EXISTS scene_feedback (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id        INTEGER NOT NULL,
    scene_index      INTEGER NOT NULL,
    visual_quality   INTEGER NOT NULL,
    emotional_impact INTEGER NOT NULL,
    pacing           INTEGER NOT NULL,
    lip_sync         INTEGER,
    notes            TEXT    DEFAULT '',
    created_at       TEXT    NOT NULL,
    FOREIGN KEY (script_id) REFERENCES scripts(id)
);
"""

_CREATE_STORY_TEMPLATES = """
CREATE TABLE IF NOT EXISTS story_templates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL UNIQUE,
    description       TEXT    NOT NULL,
    beat_structure    TEXT    NOT NULL,
    matching_keywords TEXT    NOT NULL,
    visual_style      TEXT    NOT NULL DEFAULT '',
    success_rate      REAL    DEFAULT 0.0,
    times_used        INTEGER DEFAULT 0,
    created_at        TEXT    NOT NULL
);
"""

_CREATE_TOPICS_GENERATED = """
CREATE TABLE IF NOT EXISTS topics_generated (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    topic          TEXT    NOT NULL,
    template_name  TEXT    NOT NULL,
    angle          TEXT    NOT NULL,
    why            TEXT    NOT NULL DEFAULT '',
    generated_at   TEXT    NOT NULL,
    used           INTEGER DEFAULT 0
);
"""

_DEFAULT_PROMPT_RULES = [
    ("subject", "describe one primary subject per scene, be specific about appearance", 9),
    ("camera", "always specify camera movement -- tracking, dolly, crane, static, handheld", 8),
    ("motion", "describe what moves and add a motion endpoint -- where does the movement end?", 8),
    ("lighting", "specify light quality -- golden hour, soft key, god rays, neon, cold blue", 7),
    ("sound", "include ambient sound description -- silence, heartbeat, rain, distant birdsong", 6),
    ("style", "add a film style -- cinematic, documentary, film noir, 35mm grain", 6),
    ("atmosphere", "specify color temperature -- warm amber, cold blue, muted, high contrast", 5),
    ("structure", "one verb per shot, under 80 words per prompt", 7),
    ("avoid", "never include text, labels, or words in image prompts", 9),
    # Lip sync prompt rules
    ("lipsync", "always include 'talking directly to camera' in POV video prompts", 8),
    ("lipsync_mouth", "always include 'clear mouth articulation' and 'natural lip movement'", 8),
    ("lipsync_body", "keep body action simple during speech -- no complex movements while talking", 7),
    ("lipsync_ref", "character reference must show teeth visible and slight smile", 7),
    ("lipsync_motion", "motion intensity low to prevent face morphing during speech", 6),
    ("lipsync_duration", "shorter clips 3-7s maintain better lip sync than longer ones", 6),
    ("lipsync_chain", "extract last frame of each clip and use as reference for next clip", 5),
    ("lipsync_angle", "front-facing or 3/4 angle only for lip sync accuracy", 7),
    ("lipsync_camera", "phone camera perspective: slightly below eye level, subtle handheld wobble", 6),
    ("lipsync_gaze", "POV character must maintain direct eye contact with camera lens throughout every scene", 8),
]

_DEFAULT_RULES = [
    ("Start in a moment, not a topic. Never open with 'Did you know' or 'Scientists found'", "storytelling", "narrative arc system"),
    ("Use 'you' like a mirror -- second person, present tense, always", "voice", "narrative arc system"),
    ("One emotion per scene. Don't mix.", "emotion", "narrative arc system"),
    ("Science reveals a hidden superpower. The twist should make the viewer feel powerful, not broken.", "structure", "narrative arc system"),
    ("End with empowerment, not advice. The viewer should feel stronger, more capable, more understood.", "structure", "narrative arc system"),
    ("Short sentences for impact. Questions to pull the viewer in.", "pacing", "narrative arc system"),
    ("Every scene shows the CHARACTER experiencing the emotion. The viewer watches a person go through it, not an abstract concept.", "character", "character system"),
    ("Describe real locations the viewer recognizes -- bedrooms, kitchens, bus stops, rain-soaked streets. Never abstract voids.", "location", "character system"),
    ("Character's clothing stays identical across all scenes for consistency.", "character", "character system"),
    ("Light sources must be physically real -- phone screens, street lamps, dawn through a window. Never unnamed 'dramatic lighting'.", "lighting", "character system"),
    ("Character actions must be small and human -- a thumb hovering, a head dropping, eyes closing. Never grand gestures.", "character", "character system"),
    ("Every scene is a moment in ONE continuous night/day. Time progresses through the video.", "structure", "character system"),
    ("Every hook must work visually WITHOUT sound -- 85% of viewers watch on mute", "hook", "narrative arc system"),
    ("Bold on-screen captions on every scene -- 3-5 words that punch", "caption", "narrative arc system"),
    ("Start with the payoff or the feeling, then explain. Inverted structure beats traditional.", "structure", "narrative arc system"),
    # POV rules
    ("Write like someone who just discovered something incredible about themselves. Excited, curious, amazed.", "pov", "pov system"),
    ("Include natural speech patterns: pauses, restarts, trailing off", "pov", "pov system"),
    ("The character discovers the science in real time. She reacts to it, doesn't recite it.", "pov", "pov system"),
    ("First person always in POV mode. 'I can't sleep' not 'you can't sleep'", "pov", "pov system"),
    ("End with wonder. The viewer should feel capable, understood, and curious -- never hopeless.", "pov", "pov system"),
    ("Keep each sentence short enough to be one video chunk (3-7 seconds of speech max)", "pov", "pov system"),
    # Variety rules
    ("Never repeat the same location in consecutive scripts. Track what was used last and choose something different.", "variety", "variety system"),
    ("Never repeat the same lighting in consecutive scripts. Alternate: phone light, dawn, streetlight, neon, candlelight, overcast, fluorescent.", "variety", "variety system"),
    ("Vary the emotional starting point. Not always sadness. Use: confusion, anger, nervous energy, forced calm, fake happiness, numbness, restless energy.", "variety", "variety system"),
    ("Vary time of day. Not always 3 AM. Use: golden hour, lunch break, crowded room, walking home at night, morning after, sunset, bathroom at work.", "variety", "variety system"),
    ("Vary camera energy for POV. Not always static selfie. Use: walking and talking, sitting in car, lying on floor, pacing, leaning against wall, standing at window.", "variety", "variety system"),
    ("Each video must feel like a different moment in a different day -- not the same night replayed with different words.", "variety", "variety system"),
    # Empowerment rules
    ("The viewer should feel STRONGER after watching, never weaker. The science explains their power, not their pain.", "storytelling", "tone system"),
    ("Reframe every psychological fact as a superpower or hidden ability, not a dysfunction.", "storytelling", "tone system"),
    ("The character discovers something amazing about themselves, not something broken.", "character", "tone system"),
    ("Use words like: incredible, powerful, designed to, built for, capable of -- not: broken, damaged, withdrawal, dysfunction.", "voice", "tone system"),
    # Data-driven optimization rules
    ("POV emotions must be simple and clear -- one feeling, not contradictions. Lip-sync renders curiosity, amusement, fascination, and quiet realization well. It renders shock, desperation, and masked emotions poorly.", "pov", "data-optimization"),
    ("Revelation beats should use realization or fascination emotions, not shock or devastation. Data shows quiet realization scores 3.7/5 vs shock at 3.3/5.", "emotion", "data-optimization"),
    ("The revelation/reveal beat should be the SHORTEST content beat, not the longest. Hit the twist fast -- don't explain it. Let the viewer's brain do the work.", "structure", "data-optimization"),
]

_DEFAULT_VOICE_PROFILE = [
    ("tone", "warm, fascinated, like sharing a secret that will change how you see yourself"),
    ("person", "second person (you/your)"),
    ("tense", "present tense"),
    ("style", "storytelling, not educational. Emotion before information."),
    ("pacing", "slow, cinematic. Pauses are powerful. Silence between beats."),
    ("pov_person", "first person (I/me/my)"),
    ("pov_style", "curious, increasingly amazed, like discovering a superpower you didn't know you had"),
    ("pov_pacing", "natural speech with pauses, restarts, trailing off. NOT polished."),
]

_DEFAULT_STORY_TEMPLATES = [
    {
        "name": "THE MIRROR",
        "description": "Start with the viewer's experience, reveal the science. Best for emotional experiences everyone shares.",
        "beat_structure": [
            {"beat": "hook", "description": "personal moment", "duration_min": 2, "duration_max": 3, "rule_categories": ["hook", "caption", "visual", "prompt"]},
            {"beat": "tension", "description": "deepen the feeling", "duration_min": 8, "duration_max": 12, "rule_categories": ["emotion", "pacing", "character", "location"]},
            {"beat": "revelation", "description": "science/insight as a twist that reframes everything — hit it fast, don't over-explain", "duration_min": 8, "duration_max": 12, "rule_categories": ["structure", "storytelling", "prompt", "emotion"]},
            {"beat": "resolution", "description": "reframe, not advice — short and powerful", "duration_min": 5, "duration_max": 7, "rule_categories": ["voice", "structure", "pacing"]},
        ],
        "matching_keywords": ["heartbreak", "anxiety", "falling in love", "jealousy", "loneliness", "grief", "rejection"],
        "visual_style": "intimate, single location, time progression from dark to light",
    },
    {
        "name": "THE MYSTERY",
        "description": "Start with a question the viewer can't answer. Build clues. Reveal the answer. Best for 'why' questions about human behavior.",
        "beat_structure": [
            {"beat": "question", "description": "unanswerable hook that grabs curiosity", "duration_min": 2, "duration_max": 3, "rule_categories": ["hook", "caption", "visual", "prompt"]},
            {"beat": "clues", "description": "build evidence, deepen the mystery", "duration_min": 8, "duration_max": 10, "rule_categories": ["emotion", "pacing", "character", "location"]},
            {"beat": "reveal", "description": "the surprising answer — short and punchy, don't over-explain", "duration_min": 5, "duration_max": 8, "rule_categories": ["structure", "storytelling", "prompt", "emotion"]},
            {"beat": "reframe", "description": "new understanding that changes perspective", "duration_min": 5, "duration_max": 5, "rule_categories": ["voice", "structure", "pacing"]},
        ],
        "matching_keywords": ["why", "always", "never", "can't stop", "keep doing", "pattern", "repeat", "habit"],
        "visual_style": "progressive reveal, lighting gets brighter as answer approaches",
    },
    {
        "name": "THE CONTRADICTION",
        "description": "Open with two truths that seem impossible together. Explain how both are true. Best for counterintuitive psychology.",
        "beat_structure": [
            {"beat": "paradox", "description": "two conflicting truths presented together", "duration_min": 3, "duration_max": 4, "rule_categories": ["hook", "caption", "visual", "prompt"]},
            {"beat": "side_a", "description": "first truth explained and felt", "duration_min": 7, "duration_max": 8, "rule_categories": ["emotion", "pacing", "character", "location"]},
            {"beat": "side_b", "description": "second truth explained and felt", "duration_min": 7, "duration_max": 8, "rule_categories": ["emotion", "pacing", "character", "location"]},
            {"beat": "synthesis", "description": "how both truths coexist — the deeper insight", "duration_min": 4, "duration_max": 5, "rule_categories": ["voice", "structure", "pacing"]},
        ],
        "matching_keywords": ["but", "both", "contradicts", "opposite", "paradox", "makes no sense", "weird"],
        "visual_style": "split energy — visual contrast between the two sides, merging at resolution",
    },
    {
        "name": "THE TIMELINE",
        "description": "Walk through a process in real time. Best for body processes and biological sequences.",
        "beat_structure": [
            {"beat": "start", "description": "the first moment — ground the viewer in time", "duration_min": 2, "duration_max": 3, "rule_categories": ["hook", "caption", "visual", "prompt"]},
            {"beat": "escalation", "description": "the process builds and intensifies", "duration_min": 10, "duration_max": 12, "rule_categories": ["emotion", "pacing", "character", "location"]},
            {"beat": "peak", "description": "the climax of the process", "duration_min": 7, "duration_max": 8, "rule_categories": ["structure", "storytelling", "prompt"]},
            {"beat": "aftermath", "description": "what happens next — the comedown or consequence", "duration_min": 4, "duration_max": 5, "rule_categories": ["voice", "structure", "pacing"]},
        ],
        "matching_keywords": ["seconds", "minutes", "first", "then", "happens", "process", "stages", "when you"],
        "visual_style": "clock-like progression, same character experiencing each stage in sequence",
    },
    {
        "name": "THE CONFESSION",
        "description": "First person vulnerability. The character admits something. Best for destigmatizing mental health and human behavior.",
        "beat_structure": [
            {"beat": "admission", "description": "vulnerable opening — the thing they need to say", "duration_min": 3, "duration_max": 4, "rule_categories": ["hook", "caption", "visual", "prompt"]},
            {"beat": "backstory", "description": "what led here — the weight of carrying this", "duration_min": 8, "duration_max": 10, "rule_categories": ["emotion", "pacing", "character", "location"]},
            {"beat": "discovery", "description": "what I learned — the turning point", "duration_min": 8, "duration_max": 10, "rule_categories": ["structure", "storytelling", "prompt"]},
            {"beat": "acceptance", "description": "making peace — not fixing, accepting", "duration_min": 4, "duration_max": 5, "rule_categories": ["voice", "structure", "pacing"]},
        ],
        "matching_keywords": ["thought I was broken", "ashamed", "wrong with me", "nobody talks about", "secret", "always hid"],
        "visual_style": "extreme close-up, eye contact throughout, almost uncomfortably intimate",
    },
    {
        "name": "THE ZOOM OUT",
        "description": "Start with one tiny detail, keep zooming out until the big picture is revealed. Best for mind-blowing body facts. In POV mode: zoom is conceptual (start with face extreme close-up, reveal context through dialogue), not visual camera zoom.",
        "beat_structure": [
            {"beat": "micro", "description": "tiny detail — one sensation or body part", "duration_min": 2, "duration_max": 3, "rule_categories": ["hook", "caption", "visual", "prompt"]},
            {"beat": "expand", "description": "what it connects to — the next layer", "duration_min": 7, "duration_max": 8, "rule_categories": ["emotion", "pacing", "character", "location"]},
            {"beat": "bigger", "description": "the larger system at work", "duration_min": 8, "duration_max": 10, "rule_categories": ["structure", "storytelling", "prompt"]},
            {"beat": "macro", "description": "the mind-blow — full picture revealed", "duration_min": 4, "duration_max": 5, "rule_categories": ["voice", "structure", "pacing"]},
        ],
        "matching_keywords": ["that feeling", "knot in your stomach", "goosebumps", "chills", "shiver", "tingling", "pupils"],
        "visual_style": "literal visual zoom — start tight, end wide. Or conceptual zoom from body detail to full system",
    },
]


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(_CREATE_SCRIPTS)
    conn.execute(_CREATE_HOOKS)
    conn.execute(_CREATE_RULEBOOK)
    conn.execute(_CREATE_FEEDBACK_LOG)
    conn.execute(_CREATE_SCRIPT_TAGS)
    conn.execute(_CREATE_VOICE_PROFILE)
    conn.execute(_CREATE_RESEARCH_FINDINGS)
    conn.execute(_CREATE_PROMPT_RULES)
    conn.execute(_CREATE_CHARACTER_PROFILES)
    conn.execute(_CREATE_RENDER_LOG)
    conn.execute(_CREATE_VIDEO_REVIEWS)
    conn.execute(_CREATE_SCENE_FEEDBACK)
    conn.execute(_CREATE_STORY_TEMPLATES)
    conn.execute(_CREATE_TOPICS_GENERATED)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(scripts)").fetchall()}
    if "character_id" not in columns:
        conn.execute("ALTER TABLE scripts ADD COLUMN character_id INTEGER")
    if "mode" not in columns:
        conn.execute("ALTER TABLE scripts ADD COLUMN mode TEXT DEFAULT 'narrator'")
    if "template_id" not in columns:
        conn.execute("ALTER TABLE scripts ADD COLUMN template_id INTEGER")

    cp_cols = {row[1] for row in conn.execute("PRAGMA table_info(character_profiles)").fetchall()}
    if "wardrobe" not in cp_cols:
        conn.execute("ALTER TABLE character_profiles ADD COLUMN wardrobe TEXT DEFAULT '[]'")


def seed_defaults(conn: sqlite3.Connection) -> None:
    """Seed default rules and voice profile if tables are empty. Idempotent."""
    rule_count = conn.execute("SELECT COUNT(*) FROM rulebook").fetchone()[0]
    if rule_count == 0:
        now = datetime.now().isoformat()
        for rule, category, source in _DEFAULT_RULES:
            conn.execute(
                "INSERT INTO rulebook (rule, category, source, created_at) VALUES (?, ?, ?, ?)",
                (rule, category, source, now),
            )

    profile_count = conn.execute("SELECT COUNT(*) FROM voice_profile").fetchone()[0]
    if profile_count == 0:
        now = datetime.now().isoformat()
        for attribute, value in _DEFAULT_VOICE_PROFILE:
            conn.execute(
                "INSERT INTO voice_profile (attribute, value, created_at) VALUES (?, ?, ?)",
                (attribute, value, now),
            )

    pr_count = conn.execute("SELECT COUNT(*) FROM prompt_rules").fetchone()[0]
    if pr_count == 0:
        now = datetime.now().isoformat()
        for element, rule, weight in _DEFAULT_PROMPT_RULES:
            conn.execute(
                "INSERT INTO prompt_rules (element, rule, weight, source, created_at) VALUES (?, ?, ?, ?, ?)",
                (element, rule, weight, "default seed", now),
            )

    import json as _json
    tmpl_count = conn.execute("SELECT COUNT(*) FROM story_templates").fetchone()[0]
    if tmpl_count == 0:
        now = datetime.now().isoformat()
        for t in _DEFAULT_STORY_TEMPLATES:
            conn.execute(
                "INSERT INTO story_templates (name, description, beat_structure, "
                "matching_keywords, visual_style, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (t["name"], t["description"], _json.dumps(t["beat_structure"]),
                 _json.dumps(t["matching_keywords"]), t["visual_style"], now),
            )
    conn.commit()


# --- Scripts ---


def add_script(
    conn: sqlite3.Connection,
    topic: str,
    hook: str,
    scenes: list[Scene],
    full_script: str,
    style: str = "educational",
    duration_target: int = 45,
    angle: str | None = None,
    parent_id: int | None = None,
    version: int = 1,
    character_id: int | None = None,
    mode: str = "narrator",
    tags: list[str] | None = None,
    template_id: int | None = None,
) -> Script:
    # Fetch template for validation if provided
    template = get_template(conn, template_id) if template_id else None
    max_scene_dur = 10 if mode == "pov" else None
    errors = validate_script(scenes, full_script, template=template,
                              max_scene_duration=max_scene_dur)
    if errors:
        raise ValueError(f"Script validation failed: {'; '.join(errors)}")
    now = datetime.now().isoformat()
    word_count = len(full_script.split())
    scenes_json = Script(
        id=0, topic=topic, hook=hook, scenes=scenes,
        full_script=full_script, created_at=datetime.now(),
    ).scenes_json
    cur = conn.execute(
        "INSERT INTO scripts (topic, angle, style, duration_target, hook, "
        "scenes, full_script, word_count, version, parent_id, character_id, "
        "template_id, mode, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (topic, angle, style, duration_target, hook,
         scenes_json, full_script, word_count, version, parent_id, character_id,
         template_id, mode, now),
    )
    script_id = cur.lastrowid
    tag_list = tags or []
    for tag in tag_list:
        conn.execute("INSERT INTO script_tags (script_id, tag) VALUES (?, ?)", (script_id, tag))
    hook_beat = scenes[0].beat if scenes else "hook"
    conn.execute(
        "INSERT INTO hooks (text, script_id, style, created_at) VALUES (?, ?, ?, ?)",
        (hook, script_id, hook_beat, now),
    )
    conn.commit()
    return Script(
        id=script_id, topic=topic, hook=hook, scenes=scenes,
        full_script=full_script, style=style, duration_target=duration_target,
        angle=angle, word_count=word_count, character_id=character_id,
        template_id=template_id, mode=mode, version=version, parent_id=parent_id,
        created_at=datetime.fromisoformat(now), tags=tag_list,
    )


def get_script(conn: sqlite3.Connection, script_id: int) -> Script | None:
    row = conn.execute(
        "SELECT id, topic, angle, style, duration_target, hook, scenes, "
        "full_script, word_count, rating, feedback, version, parent_id, character_id, template_id, mode, created_at "
        "FROM scripts WHERE id = ?",
        (script_id,),
    ).fetchone()
    if not row:
        return None
    script = _row_to_script(row)
    script.tags = _get_tags(conn, script_id)
    return script


def list_scripts(conn: sqlite3.Connection) -> list[Script]:
    rows = conn.execute(
        "SELECT id, topic, angle, style, duration_target, hook, scenes, "
        "full_script, word_count, rating, feedback, version, parent_id, character_id, template_id, mode, created_at "
        "FROM scripts ORDER BY created_at DESC",
    ).fetchall()
    scripts = [_row_to_script(r) for r in rows]
    if scripts:
        _attach_tags(conn, scripts)
    return scripts


def rate_script(conn: sqlite3.Connection, script_id: int, rating: str, notes: str) -> bool:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "UPDATE scripts SET rating = ?, feedback = ? WHERE id = ?",
        (rating, notes, script_id),
    )
    if cur.rowcount == 0:
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO feedback_log (script_id, rating, notes, created_at) VALUES (?, ?, ?, ?)",
        (script_id, rating, notes, now),
    )
    conn.commit()
    return True


def search_scripts(conn: sqlite3.Connection, query: str) -> list[Script]:
    pattern = f"%{query}%"
    rows = conn.execute(
        "SELECT id, topic, angle, style, duration_target, hook, scenes, "
        "full_script, word_count, rating, feedback, version, parent_id, character_id, template_id, mode, created_at "
        "FROM scripts WHERE topic LIKE ? OR full_script LIKE ? OR hook LIKE ? "
        "ORDER BY created_at DESC",
        (pattern, pattern, pattern),
    ).fetchall()
    scripts = [_row_to_script(r) for r in rows]
    if scripts:
        _attach_tags(conn, scripts)
    return scripts


# --- Feedback ---


def get_feedback_log(conn: sqlite3.Connection, script_id: int) -> list[FeedbackEntry]:
    rows = conn.execute(
        "SELECT id, script_id, rating, notes, created_at FROM feedback_log "
        "WHERE script_id = ? ORDER BY created_at",
        (script_id,),
    ).fetchall()
    return [FeedbackEntry(id=r[0], script_id=r[1], rating=r[2], notes=r[3],
                          created_at=datetime.fromisoformat(r[4])) for r in rows]


def get_all_feedback(conn: sqlite3.Connection) -> list[FeedbackEntry]:
    rows = conn.execute(
        "SELECT id, script_id, rating, notes, created_at FROM feedback_log ORDER BY created_at",
    ).fetchall()
    return [FeedbackEntry(id=r[0], script_id=r[1], rating=r[2], notes=r[3],
                          created_at=datetime.fromisoformat(r[4])) for r in rows]


# --- Hooks ---


def add_hook(conn: sqlite3.Connection, text: str, style: str | None = None,
             script_id: int | None = None) -> Hook:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO hooks (text, script_id, style, created_at) VALUES (?, ?, ?, ?)",
        (text, script_id, style, now),
    )
    conn.commit()
    return Hook(id=cur.lastrowid, text=text, script_id=script_id, style=style,
                created_at=datetime.fromisoformat(now))


def get_top_hooks(conn: sqlite3.Connection, limit: int = 10) -> list[Hook]:
    rows = conn.execute(
        "SELECT id, text, script_id, rating, style, created_at FROM hooks "
        "ORDER BY CASE WHEN rating = 'good' THEN 0 WHEN rating IS NULL THEN 1 ELSE 2 END, "
        "created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [Hook(id=r[0], text=r[1], script_id=r[2], rating=r[3], style=r[4],
                 created_at=datetime.fromisoformat(r[5])) for r in rows]


def rate_hook(conn: sqlite3.Connection, hook_id: int, rating: str) -> bool:
    cur = conn.execute("UPDATE hooks SET rating = ? WHERE id = ?", (rating, hook_id))
    conn.commit()
    return cur.rowcount > 0


# --- Rules ---


def add_rule(conn: sqlite3.Connection, rule: str, category: str | None = None,
             source: str | None = None) -> Rule:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO rulebook (rule, source, category, created_at) VALUES (?, ?, ?, ?)",
        (rule, source, category, now),
    )
    conn.commit()
    return Rule(id=cur.lastrowid, rule=rule, source=source, category=category,
                created_at=datetime.fromisoformat(now))


def get_active_rules(conn: sqlite3.Connection) -> list[Rule]:
    rows = conn.execute(
        "SELECT id, rule, source, category, active, created_at FROM rulebook WHERE active = 1 "
        "ORDER BY category, created_at",
    ).fetchall()
    return [Rule(id=r[0], rule=r[1], source=r[2], category=r[3], active=bool(r[4]),
                 created_at=datetime.fromisoformat(r[5])) for r in rows]


def deactivate_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    cur = conn.execute("UPDATE rulebook SET active = 0 WHERE id = ?", (rule_id,))
    conn.commit()
    return cur.rowcount > 0


# --- Characters ---


def add_character(conn: sqlite3.Connection, name: str, age: str, gender: str,
                  appearance: str, clothing: str) -> Character:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO character_profiles (name, age, gender, appearance, clothing, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, age, gender, appearance, clothing, now),
    )
    conn.commit()
    return Character(id=cur.lastrowid, name=name, age=age, gender=gender,
                     appearance=appearance, clothing=clothing,
                     created_at=datetime.fromisoformat(now))


def _parse_wardrobe(raw: str | None) -> list[str]:
    import json as _json
    if not raw:
        return []
    try:
        return _json.loads(raw)
    except (ValueError, TypeError):
        return []


def get_character(conn: sqlite3.Connection, character_id: int) -> Character | None:
    row = conn.execute(
        "SELECT id, name, age, gender, appearance, clothing, reference_image_path, wardrobe, created_at "
        "FROM character_profiles WHERE id = ?",
        (character_id,),
    ).fetchone()
    if not row:
        return None
    return Character(id=row[0], name=row[1], age=row[2], gender=row[3],
                     appearance=row[4], clothing=row[5], reference_image_path=row[6],
                     wardrobe=_parse_wardrobe(row[7]),
                     created_at=datetime.fromisoformat(row[8]))


def list_characters(conn: sqlite3.Connection) -> list[Character]:
    rows = conn.execute(
        "SELECT id, name, age, gender, appearance, clothing, reference_image_path, wardrobe, created_at "
        "FROM character_profiles ORDER BY created_at DESC",
    ).fetchall()
    return [Character(id=r[0], name=r[1], age=r[2], gender=r[3], appearance=r[4],
                      clothing=r[5], reference_image_path=r[6],
                      wardrobe=_parse_wardrobe(r[7]),
                      created_at=datetime.fromisoformat(r[8])) for r in rows]


def update_character_wardrobe(conn: sqlite3.Connection, character_id: int,
                               wardrobe: list[str]) -> bool:
    """Update a character's wardrobe (list of outfit descriptions)."""
    import json as _json
    cur = conn.execute(
        "UPDATE character_profiles SET wardrobe = ? WHERE id = ?",
        (_json.dumps(wardrobe), character_id),
    )
    conn.commit()
    return cur.rowcount > 0


def update_character_image(conn: sqlite3.Connection, character_id: int, path: str) -> bool:
    cur = conn.execute(
        "UPDATE character_profiles SET reference_image_path = ? WHERE id = ?",
        (path, character_id),
    )
    conn.commit()
    return cur.rowcount > 0


# --- Voice Profile ---


def get_voice_profile(conn: sqlite3.Connection) -> list[VoiceProfile]:
    rows = conn.execute(
        "SELECT id, attribute, value, active FROM voice_profile WHERE active = 1 ORDER BY attribute",
    ).fetchall()
    return [VoiceProfile(id=r[0], attribute=r[1], value=r[2], active=bool(r[3])) for r in rows]


def set_voice_profile(conn: sqlite3.Connection, attribute: str, value: str) -> VoiceProfile:
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO voice_profile (attribute, value, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(attribute) DO UPDATE SET value = excluded.value, active = 1",
        (attribute, value, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, attribute, value, active FROM voice_profile WHERE attribute = ?",
        (attribute,),
    ).fetchone()
    return VoiceProfile(id=row[0], attribute=row[1], value=row[2], active=bool(row[3]))


# --- Research Findings ---


def add_finding(
    conn: sqlite3.Connection,
    topic: str,
    finding: str,
    category: str,
    source_url: str | None = None,
    source_title: str | None = None,
    confidence: str = "medium",
) -> Finding:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO research_findings (topic, source_url, source_title, finding, category, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (topic, source_url, source_title, finding, category, confidence, now),
    )
    conn.commit()
    return Finding(id=cur.lastrowid, topic=topic, finding=finding, category=category,
                   source_url=source_url, source_title=source_title, confidence=confidence,
                   created_at=datetime.fromisoformat(now))


def get_findings(conn: sqlite3.Connection, category: str | None = None) -> list[Finding]:
    if category:
        rows = conn.execute(
            "SELECT id, topic, finding, category, source_url, source_title, confidence, applied, created_at "
            "FROM research_findings WHERE category = ? ORDER BY created_at DESC",
            (category,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, topic, finding, category, source_url, source_title, confidence, applied, created_at "
            "FROM research_findings ORDER BY category, created_at DESC",
        ).fetchall()
    return [Finding(id=r[0], topic=r[1], finding=r[2], category=r[3], source_url=r[4],
                    source_title=r[5], confidence=r[6], applied=bool(r[7]),
                    created_at=datetime.fromisoformat(r[8])) for r in rows]


def get_unapplied_findings(conn: sqlite3.Connection) -> list[Finding]:
    rows = conn.execute(
        "SELECT id, topic, finding, category, source_url, source_title, confidence, applied, created_at "
        "FROM research_findings WHERE applied = 0 ORDER BY confidence DESC, created_at DESC",
    ).fetchall()
    return [Finding(id=r[0], topic=r[1], finding=r[2], category=r[3], source_url=r[4],
                    source_title=r[5], confidence=r[6], applied=bool(r[7]),
                    created_at=datetime.fromisoformat(r[8])) for r in rows]


def mark_finding_applied(conn: sqlite3.Connection, finding_id: int) -> bool:
    cur = conn.execute("UPDATE research_findings SET applied = 1 WHERE id = ?", (finding_id,))
    conn.commit()
    return cur.rowcount > 0


# --- Prompt Rules ---


def get_prompt_rules(conn: sqlite3.Connection) -> list[PromptRule]:
    rows = conn.execute(
        "SELECT id, element, rule, weight, source, active, created_at FROM prompt_rules "
        "WHERE active = 1 ORDER BY weight DESC",
    ).fetchall()
    return [PromptRule(id=r[0], element=r[1], rule=r[2], weight=r[3], source=r[4],
                       active=bool(r[5]), created_at=datetime.fromisoformat(r[6])) for r in rows]


def add_prompt_rule(conn: sqlite3.Connection, element: str, rule: str, weight: int = 5,
                    source: str | None = None) -> PromptRule:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO prompt_rules (element, rule, weight, source, created_at) VALUES (?, ?, ?, ?, ?)",
        (element, rule, weight, source, now),
    )
    conn.commit()
    return PromptRule(id=cur.lastrowid, element=element, rule=rule, weight=weight,
                      source=source, created_at=datetime.fromisoformat(now))


# --- Stats ---


def get_stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM scripts").fetchone()[0]
    rated = conn.execute("SELECT COUNT(*) FROM scripts WHERE rating IS NOT NULL").fetchone()[0]
    hits = conn.execute("SELECT COUNT(*) FROM scripts WHERE rating = 'hit'").fetchone()[0]
    rules = conn.execute("SELECT COUNT(*) FROM rulebook WHERE active = 1").fetchone()[0]
    style_rows = conn.execute(
        "SELECT style, COUNT(*) FROM scripts GROUP BY style ORDER BY COUNT(*) DESC",
    ).fetchall()
    rating_rows = conn.execute(
        "SELECT rating, COUNT(*) FROM scripts WHERE rating IS NOT NULL GROUP BY rating",
    ).fetchall()
    return {
        "total_scripts": total,
        "rated_scripts": rated,
        "hit_count": hits,
        "hit_rate": round(hits / rated * 100) if rated else 0,
        "total_rules": rules,
        "style_counts": {r[0]: r[1] for r in style_rows},
        "rating_counts": {r[0]: r[1] for r in rating_rows},
    }


# --- Tags ---


def _get_tags(conn: sqlite3.Connection, script_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT tag FROM script_tags WHERE script_id = ? ORDER BY tag", (script_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _attach_tags(conn: sqlite3.Connection, scripts: list[Script]) -> None:
    if not scripts:
        return
    ids = [s.id for s in scripts]
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT script_id, tag FROM script_tags WHERE script_id IN ({placeholders}) ORDER BY tag",
        ids,
    ).fetchall()
    tag_map: dict[int, list[str]] = {sid: [] for sid in ids}
    for sid, tag in rows:
        tag_map[sid].append(tag)
    for s in scripts:
        s.tags = tag_map.get(s.id, [])


# --- Render Log ---


def log_render_step(conn: sqlite3.Connection, script_id: int, step: str, model: str,
                    duration_seconds: float = 0, estimated_cost: float = 0,
                    status: str = "success") -> None:
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO render_log (script_id, step, model, duration_seconds, estimated_cost, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (script_id, step, model, duration_seconds, estimated_cost, status, now),
    )
    conn.commit()


def get_render_cost(conn: sqlite3.Connection, script_id: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(estimated_cost), 0) FROM render_log WHERE script_id = ? AND status = 'success'",
        (script_id,),
    ).fetchone()
    return row[0]


# --- Video Reviews ---


def save_video_review(conn: sqlite3.Connection, review: VideoReview) -> None:
    now = datetime.now().isoformat()
    for sr in review.scene_reviews:
        import json
        conn.execute(
            "INSERT INTO video_reviews (script_id, scene_index, score, issues, suggestions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (review.script_id, sr.scene_index, sr.score,
             json.dumps(sr.issues), json.dumps(sr.suggestions), now),
        )
    conn.commit()


def get_video_reviews(conn: sqlite3.Connection, script_id: int) -> list[dict]:
    import json
    rows = conn.execute(
        "SELECT scene_index, score, issues, suggestions, created_at FROM video_reviews "
        "WHERE script_id = ? ORDER BY created_at DESC, scene_index",
        (script_id,),
    ).fetchall()
    return [{"scene_index": r[0], "score": r[1], "issues": json.loads(r[2]),
             "suggestions": json.loads(r[3]), "created_at": r[4]} for r in rows]


# --- Scene Feedback ---


def save_scene_feedback(conn: sqlite3.Connection, script_id: int, scene_index: int,
                         visual_quality: int, emotional_impact: int, pacing: int,
                         lip_sync: int | None = None, notes: str = "") -> SceneFeedback:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "INSERT INTO scene_feedback (script_id, scene_index, visual_quality, emotional_impact, "
        "pacing, lip_sync, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (script_id, scene_index, visual_quality, emotional_impact, pacing, lip_sync, notes, now),
    )
    conn.commit()
    return SceneFeedback(id=cur.lastrowid, script_id=script_id, scene_index=scene_index,
                         visual_quality=visual_quality, emotional_impact=emotional_impact,
                         pacing=pacing, lip_sync=lip_sync, notes=notes,
                         created_at=datetime.fromisoformat(now))


def get_scene_feedback(conn: sqlite3.Connection, script_id: int) -> list[SceneFeedback]:
    rows = conn.execute(
        "SELECT id, script_id, scene_index, visual_quality, emotional_impact, pacing, "
        "lip_sync, notes, created_at FROM scene_feedback WHERE script_id = ? ORDER BY scene_index",
        (script_id,),
    ).fetchall()
    return [SceneFeedback(id=r[0], script_id=r[1], scene_index=r[2], visual_quality=r[3],
                          emotional_impact=r[4], pacing=r[5], lip_sync=r[6], notes=r[7],
                          created_at=datetime.fromisoformat(r[8])) for r in rows]


def analyze_scene_feedback(conn: sqlite3.Connection) -> dict:
    """Analyze patterns across all scene feedback. Returns insights dict."""
    rows = conn.execute(
        "SELECT sf.scene_index, sf.visual_quality, sf.emotional_impact, sf.pacing, "
        "sf.lip_sync, s.scenes, s.mode "
        "FROM scene_feedback sf JOIN scripts s ON sf.script_id = s.id",
    ).fetchall()

    if len(rows) < 5:
        return {"patterns": [], "total_feedback": len(rows)}

    # Cross-reference with scene attributes
    import json
    beat_scores: dict[str, list[float]] = {}
    camera_scores: dict[str, list[float]] = {}
    duration_scores: dict[str, list[float]] = {}

    for r in rows:
        idx, vis, emo, pace, lip, scenes_json, mode = r
        scenes = json.loads(scenes_json)
        if idx < len(scenes):
            scene = scenes[idx]
            avg = (vis + emo + pace) / 3.0
            beat = scene.get("beat", "unknown")
            camera = scene.get("camera", "unknown")
            dur = scene.get("duration_seconds", 0)

            beat_scores.setdefault(beat, []).append(avg)
            camera_scores.setdefault(camera, []).append(avg)
            dur_bucket = "short (3-5s)" if dur <= 5 else "medium (6-10s)" if dur <= 10 else "long (11s+)"
            duration_scores.setdefault(dur_bucket, []).append(avg)

    patterns = []
    for beat, scores in sorted(beat_scores.items()):
        if len(scores) >= 2:
            avg = sum(scores) / len(scores)
            patterns.append(f"{beat} scenes average {avg:.1f}/5 ({len(scores)} samples)")

    for camera, scores in sorted(camera_scores.items()):
        if len(scores) >= 2:
            avg = sum(scores) / len(scores)
            patterns.append(f"'{camera}' camera averages {avg:.1f}/5 ({len(scores)} samples)")

    for bucket, scores in sorted(duration_scores.items()):
        if len(scores) >= 2:
            avg = sum(scores) / len(scores)
            patterns.append(f"{bucket} scenes average {avg:.1f}/5 ({len(scores)} samples)")

    # POV lip-sync quality correlation with duration
    pov_lip_dur: dict[str, list[float]] = {}
    for r in rows:
        idx, vis, emo, pace, lip, scenes_json, mode = r
        if mode == "pov" and lip is not None:
            scenes = json.loads(scenes_json)
            if idx < len(scenes):
                dur = scenes[idx].get("duration_seconds", 0)
                dur_bucket = "short (3-5s)" if dur <= 5 else "medium (6-10s)" if dur <= 10 else "long (11s+)"
                pov_lip_dur.setdefault(dur_bucket, []).append(lip)

    for bucket, scores in sorted(pov_lip_dur.items()):
        if len(scores) >= 2:
            avg = sum(scores) / len(scores)
            patterns.append(f"POV lip-sync in {bucket} clips: {avg:.1f}/5 ({len(scores)} samples)")

    return {"patterns": patterns, "total_feedback": len(rows)}


# --- Story Templates ---


def _row_to_template(row: tuple) -> StoryTemplate:
    import json as _json
    return StoryTemplate(
        id=row[0],
        name=row[1],
        description=row[2],
        beat_structure=_json.loads(row[3]),
        matching_keywords=_json.loads(row[4]),
        visual_style=row[5],
        success_rate=row[6],
        times_used=row[7],
        created_at=datetime.fromisoformat(row[8]),
    )


def get_all_templates(conn: sqlite3.Connection) -> list[StoryTemplate]:
    """Return all story templates ordered by success rate (highest first)."""
    rows = conn.execute(
        "SELECT id, name, description, beat_structure, matching_keywords, "
        "visual_style, success_rate, times_used, created_at "
        "FROM story_templates ORDER BY success_rate DESC",
    ).fetchall()
    return [_row_to_template(r) for r in rows]


def get_template(conn: sqlite3.Connection, template_id: int) -> StoryTemplate | None:
    """Fetch a single template by ID."""
    row = conn.execute(
        "SELECT id, name, description, beat_structure, matching_keywords, "
        "visual_style, success_rate, times_used, created_at "
        "FROM story_templates WHERE id = ?",
        (template_id,),
    ).fetchone()
    return _row_to_template(row) if row else None


def get_template_by_name(conn: sqlite3.Connection, name: str) -> StoryTemplate | None:
    """Fetch a template by name (case-insensitive partial match)."""
    row = conn.execute(
        "SELECT id, name, description, beat_structure, matching_keywords, "
        "visual_style, success_rate, times_used, created_at "
        "FROM story_templates WHERE UPPER(name) LIKE '%' || UPPER(?) || '%'",
        (name,),
    ).fetchone()
    return _row_to_template(row) if row else None


def increment_template_usage(conn: sqlite3.Connection, template_id: int) -> None:
    """Increment the times_used counter for a template."""
    conn.execute(
        "UPDATE story_templates SET times_used = times_used + 1 WHERE id = ?",
        (template_id,),
    )
    conn.commit()


def update_template_success_rate(conn: sqlite3.Connection, template_id: int) -> float:
    """Recalculate success rate from scene feedback of scripts using this template."""
    row = conn.execute(
        "SELECT AVG((sf.visual_quality + sf.emotional_impact + sf.pacing) / 3.0) "
        "FROM scene_feedback sf JOIN scripts s ON sf.script_id = s.id "
        "WHERE s.template_id = ?",
        (template_id,),
    ).fetchone()
    rate = round(row[0], 2) if row and row[0] is not None else 0.0
    conn.execute(
        "UPDATE story_templates SET success_rate = ? WHERE id = ?",
        (rate, template_id),
    )
    conn.commit()
    return rate


def get_recent_template_ids(conn: sqlite3.Connection, limit: int = 3) -> list[int]:
    """Return template_ids of the most recently created scripts."""
    rows = conn.execute(
        "SELECT template_id FROM scripts WHERE template_id IS NOT NULL "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r[0] for r in rows]


# --- Generated Topics ---


def save_generated_topics(conn: sqlite3.Connection, topics: list[dict]) -> None:
    """Bulk insert generated topic suggestions."""
    now = datetime.now().isoformat()
    for t in topics:
        conn.execute(
            "INSERT INTO topics_generated (topic, template_name, angle, why, generated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (t["topic"], t["template"], t["angle"], t.get("why", ""), now),
        )
    conn.commit()


def get_generated_topics(conn: sqlite3.Connection, *,
                          unused_only: bool = False) -> list[dict]:
    """Retrieve past topic suggestions."""
    query = "SELECT id, topic, template_name, angle, why, used FROM topics_generated"
    if unused_only:
        query += " WHERE used = 0"
    query += " ORDER BY generated_at DESC"
    rows = conn.execute(query).fetchall()
    return [{"id": r[0], "topic": r[1], "template": r[2], "angle": r[3],
             "why": r[4], "used": bool(r[5])} for r in rows]


def mark_topic_used(conn: sqlite3.Connection, topic_id: int) -> None:
    """Mark a generated topic as used."""
    conn.execute("UPDATE topics_generated SET used = 1 WHERE id = ?", (topic_id,))
    conn.commit()


# --- Internal ---


def _row_to_script(row: tuple) -> Script:
    return Script(
        id=row[0],
        topic=row[1],
        angle=row[2],
        style=row[3],
        duration_target=row[4],
        hook=row[5],
        scenes=Script.parse_scenes(row[6]),
        full_script=row[7],
        word_count=row[8],
        rating=row[9],
        feedback=row[10],
        version=row[11],
        parent_id=row[12],
        character_id=row[13],
        template_id=row[14],
        mode=row[15] or "narrator",
        created_at=datetime.fromisoformat(row[16]),
    )
