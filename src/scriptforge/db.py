from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from scriptforge.models import FeedbackEntry, Hook, Rule, Scene, Script

DEFAULT_DB = Path.home() / ".scriptforge" / "scriptforge.db"

_CREATE_SCRIPTS = """
CREATE TABLE IF NOT EXISTS scripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT    NOT NULL,
    angle           TEXT,
    style           TEXT    DEFAULT 'educational',
    duration_target INTEGER DEFAULT 60,
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


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(_CREATE_SCRIPTS)
    conn.execute(_CREATE_HOOKS)
    conn.execute(_CREATE_RULEBOOK)
    conn.execute(_CREATE_FEEDBACK_LOG)
    conn.execute(_CREATE_SCRIPT_TAGS)
    conn.commit()
    return conn


# --- Scripts ---


def add_script(
    conn: sqlite3.Connection,
    topic: str,
    hook: str,
    scenes: list[Scene],
    full_script: str,
    style: str = "educational",
    duration_target: int = 60,
    hook_style: str | None = None,
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
        "INSERT INTO scripts (topic, angle, style, duration_target, hook, hook_style, "
        "scenes, full_script, word_count, version, parent_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (topic, angle, style, duration_target, hook, hook_style,
         scenes_json, full_script, word_count, version, parent_id, now),
    )
    script_id = cur.lastrowid
    tag_list = tags or []
    for tag in tag_list:
        conn.execute("INSERT INTO script_tags (script_id, tag) VALUES (?, ?)", (script_id, tag))
    # Auto-save the hook
    conn.execute(
        "INSERT INTO hooks (text, script_id, style, created_at) VALUES (?, ?, ?, ?)",
        (hook, script_id, hook_style, now),
    )
    conn.commit()
    return Script(
        id=script_id, topic=topic, hook=hook, scenes=scenes,
        full_script=full_script, style=style, duration_target=duration_target,
        hook_style=hook_style, angle=angle, word_count=word_count,
        version=version, parent_id=parent_id, created_at=datetime.fromisoformat(now),
        tags=tag_list,
    )


def get_script(conn: sqlite3.Connection, script_id: int) -> Script | None:
    row = conn.execute(
        "SELECT id, topic, angle, style, duration_target, hook, hook_style, scenes, "
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
        "SELECT id, topic, angle, style, duration_target, hook, hook_style, scenes, "
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
        "SELECT id, topic, angle, style, duration_target, hook, hook_style, scenes, "
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
        hook_style=row[6],
        scenes=Script.parse_scenes(row[7]),
        full_script=row[8],
        word_count=row[9],
        rating=row[10],
        feedback=row[11],
        version=row[12],
        parent_id=row[13],
        created_at=datetime.fromisoformat(row[14]),
    )
