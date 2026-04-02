from __future__ import annotations

import sqlite3

from scriptforge import db


def build_write_context(
    conn: sqlite3.Connection,
    topic: str,
    style: str,
    duration_target: int,
) -> dict:
    """Assemble all context needed to write a new script."""
    rules = db.get_active_rules(conn)
    top_hooks = db.get_top_hooks(conn, limit=10)
    patterns = analyze_feedback_patterns(conn)

    prompt = _build_write_prompt(topic, style, duration_target, rules, top_hooks, patterns)

    return {
        "topic": topic,
        "style": style,
        "duration_target": duration_target,
        "rules": rules,
        "top_hooks": top_hooks,
        "feedback_patterns": patterns,
        "prompt": prompt,
    }


def build_rewrite_context(conn: sqlite3.Connection, script_id: int) -> dict | None:
    """Assemble context needed to rewrite an existing script."""
    script = db.get_script(conn, script_id)
    if not script:
        return None

    rules = db.get_active_rules(conn)
    feedback_entries = db.get_feedback_log(conn, script_id)
    feedback_text = "\n".join(f"- [{e.rating}] {e.notes}" for e in feedback_entries)

    prompt = _build_rewrite_prompt(script, feedback_text, rules)

    return {
        "original_script": script,
        "feedback": feedback_text,
        "rules": rules,
        "prompt": prompt,
    }


def analyze_feedback_patterns(conn: sqlite3.Connection) -> dict:
    """Extract patterns from all feedback to guide future scripts."""
    all_feedback = db.get_all_feedback(conn)
    hit_notes = [e.notes for e in all_feedback if e.rating == "hit" and e.notes]
    miss_notes = [e.notes for e in all_feedback if e.rating == "miss" and e.notes]

    return {
        "hit_notes": hit_notes,
        "miss_notes": miss_notes,
        "total_rated": len(all_feedback),
    }


def _build_write_prompt(
    topic: str,
    style: str,
    duration_target: int,
    rules: list,
    top_hooks: list,
    patterns: dict,
) -> str:
    """Build the full prompt for writing a new script."""
    sections = []

    sections.append(f"Write a {style} video script about: {topic}")
    sections.append(f"Target duration: {duration_target} seconds (~{duration_target * 150 // 60} words)")

    sections.append("\nFormat the script as:")
    sections.append("1. HOOK (first 2 seconds - the most critical line)")
    sections.append("2. SCENES (array of scenes, each with: voiceover, visual description, duration, transition)")
    sections.append("3. FULL SCRIPT (complete voiceover as plain text)")

    if rules:
        sections.append("\n--- RULEBOOK (follow these rules) ---")
        for r in rules:
            cat = f"[{r.category}] " if r.category else ""
            sections.append(f"- {cat}{r.rule}")

    if top_hooks:
        sections.append("\n--- TOP HOOKS (use these as inspiration) ---")
        for h in top_hooks[:5]:
            rating = f" ({h.rating})" if h.rating else ""
            style_tag = f" [{h.style}]" if h.style else ""
            sections.append(f'- "{h.text}"{style_tag}{rating}')

    if patterns["hit_notes"]:
        sections.append("\n--- WHAT WORKS (from past hits) ---")
        for note in patterns["hit_notes"][:5]:
            sections.append(f"- {note}")

    if patterns["miss_notes"]:
        sections.append("\n--- WHAT TO AVOID (from past misses) ---")
        for note in patterns["miss_notes"][:5]:
            sections.append(f"- {note}")

    return "\n".join(sections)


def _build_rewrite_prompt(script: object, feedback_text: str, rules: list) -> str:
    """Build the full prompt for rewriting an existing script."""
    sections = []

    sections.append(f"Rewrite this {script.style} video script about: {script.topic}")
    sections.append(f"Target duration: {script.duration_target} seconds")

    sections.append(f"\n--- ORIGINAL SCRIPT ---\n{script.full_script}")
    sections.append(f"\n--- ORIGINAL HOOK ---\n{script.hook}")

    if feedback_text:
        sections.append(f"\n--- FEEDBACK ---\n{feedback_text}")

    if rules:
        sections.append("\n--- RULEBOOK ---")
        for r in rules:
            cat = f"[{r.category}] " if r.category else ""
            sections.append(f"- {cat}{r.rule}")

    sections.append("\nAddress the feedback while keeping what worked. Return the same format: HOOK, SCENES, FULL SCRIPT.")

    return "\n".join(sections)
