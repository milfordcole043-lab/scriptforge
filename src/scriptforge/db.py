from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from scriptforge.models import FeedbackEntry, Finding, Hook, PromptRule, Rule, Scene, Script, VoiceProfile

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
]

_DEFAULT_RULES = [
    ("Start in a moment, not a topic. Never open with 'Did you know' or 'Scientists found'", "storytelling", "narrative arc system"),
    ("Use 'you' like a mirror -- second person, present tense, always", "voice", "narrative arc system"),
    ("One emotion per scene. Don't mix.", "emotion", "narrative arc system"),
    ("Science is the twist, not the point. Feeling first, facts second.", "structure", "narrative arc system"),
    ("End with a reframe, not advice. No 'so next time you...' -- just reframe.", "structure", "narrative arc system"),
    ("Short sentences for impact. Questions to pull the viewer in.", "pacing", "narrative arc system"),
    ("Visuals carry emotion, not illustration. Don't just show what the words say.", "visual", "narrative arc system"),
    ("Every hook must work visually WITHOUT sound -- 85% of viewers watch on mute", "hook", "narrative arc system"),
    ("Bold on-screen captions on every scene -- 3-5 words that punch", "caption", "narrative arc system"),
    ("Start with the payoff or the feeling, then explain. Inverted structure beats traditional.", "structure", "narrative arc system"),
]

_DEFAULT_VOICE_PROFILE = [
    ("tone", "warm and personal, like telling a friend something that changed how you see the world"),
    ("person", "second person (you/your)"),
    ("tense", "present tense"),
    ("style", "storytelling, not educational. Emotion before information."),
    ("pacing", "slow, cinematic. Pauses are powerful. Silence between beats."),
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
    conn.commit()
    return conn


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
    tags: list[str] | None = None,
) -> Script:
    now = datetime.now().isoformat()
    word_count = len(full_script.split())
    scenes_json = Script(
        id=0, topic=topic, hook=hook, scenes=scenes,
        full_script=full_script, created_at=datetime.now(),
    ).scenes_json
    cur = conn.execute(
        "INSERT INTO scripts (topic, angle, style, duration_target, hook, "
        "scenes, full_script, word_count, version, parent_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (topic, angle, style, duration_target, hook,
         scenes_json, full_script, word_count, version, parent_id, now),
    )
    script_id = cur.lastrowid
    tag_list = tags or []
    for tag in tag_list:
        conn.execute("INSERT INTO script_tags (script_id, tag) VALUES (?, ?)", (script_id, tag))
    # Auto-save the hook
    hook_beat = scenes[0].beat if scenes else "hook"
    conn.execute(
        "INSERT INTO hooks (text, script_id, style, created_at) VALUES (?, ?, ?, ?)",
        (hook, script_id, hook_beat, now),
    )
    conn.commit()
    return Script(
        id=script_id, topic=topic, hook=hook, scenes=scenes,
        full_script=full_script, style=style, duration_target=duration_target,
        angle=angle, word_count=word_count,
        version=version, parent_id=parent_id, created_at=datetime.fromisoformat(now),
        tags=tag_list,
    )


def get_script(conn: sqlite3.Connection, script_id: int) -> Script | None:
    row = conn.execute(
        "SELECT id, topic, angle, style, duration_target, hook, scenes, "
        "full_script, word_count, rating, feedback, version, parent_id, created_at "
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
        "full_script, word_count, rating, feedback, version, parent_id, created_at "
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
        "full_script, word_count, rating, feedback, version, parent_id, created_at "
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
        "ON CONFLICT(attribute) DO UPDATE SET value = ?, active = 1",
        (attribute, value, now, value),
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
        created_at=datetime.fromisoformat(row[13]),
    )
