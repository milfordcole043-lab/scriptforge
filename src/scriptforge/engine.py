from __future__ import annotations

import sqlite3

from scriptforge import db
from scriptforge.models import Scene


def build_seedance_prompt(scene: Scene) -> str:
    """Build a rich Seedance video prompt from scene fields."""
    parts = [scene.visual]
    if scene.camera:
        parts.append(scene.camera)
    if scene.motion:
        parts.append(scene.motion)
    if scene.sound:
        parts.append(f"Ambient {scene.sound}")
    return ". ".join(parts) + "."


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
    voice_profile = db.get_voice_profile(conn)

    prompt = _build_write_prompt(topic, style, duration_target, rules, top_hooks, patterns, voice_profile)

    return {
        "topic": topic,
        "style": style,
        "duration_target": duration_target,
        "rules": rules,
        "top_hooks": top_hooks,
        "feedback_patterns": patterns,
        "voice_profile": voice_profile,
        "prompt": prompt,
    }


def build_rewrite_context(conn: sqlite3.Connection, script_id: int) -> dict | None:
    """Assemble context needed to rewrite an existing script."""
    script = db.get_script(conn, script_id)
    if not script:
        return None

    rules = db.get_active_rules(conn)
    voice_profile = db.get_voice_profile(conn)
    feedback_entries = db.get_feedback_log(conn, script_id)
    feedback_text = "\n".join(f"- [{e.rating}] {e.notes}" for e in feedback_entries)

    prompt = _build_rewrite_prompt(script, feedback_text, rules, voice_profile)

    return {
        "original_script": script,
        "feedback": feedback_text,
        "rules": rules,
        "voice_profile": voice_profile,
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


def _build_voice_section(voice_profile: list) -> str:
    if not voice_profile:
        return ""
    lines = ["\n--- VOICE PROFILE ---"]
    for vp in voice_profile:
        lines.append(f"- {vp.attribute}: {vp.value}")
    return "\n".join(lines)


def _build_write_prompt(
    topic: str,
    style: str,
    duration_target: int,
    rules: list,
    top_hooks: list,
    patterns: dict,
    voice_profile: list,
) -> str:
    """Build the full prompt for writing a new script."""
    wpm = 130
    word_target = duration_target * wpm // 60
    sections = []

    sections.append(f"Write a {style} video script about: {topic}")
    sections.append(f"Target duration: {duration_target} seconds (~{word_target} words at {wpm} wpm)")

    sections.append("\n--- NARRATIVE ARC (4 beats, every script needs all 4) ---")
    sections.append("1. HOOK (2-3s) -- Start in a personal moment using 'you'. Make the viewer FEEL before they learn. Visual hook must work without sound.")
    sections.append("2. TENSION (8-12s) -- Deepen the feeling. Make the viewer need the answer. One emotion, let it breathe.")
    sections.append("3. REVELATION (10-15s) -- The science/insight as a twist. Reframes everything. Feeling first, facts second.")
    sections.append("4. RESOLUTION (5-7s) -- Reframe, not advice. Short. Powerful. Let the viewer draw their own conclusion.")
    sections.append("Build in 1-2 second pauses between beats where only visuals + sound carry the moment.")

    sections.append("\n--- SCENE FORMAT (for each scene) ---")
    sections.append("beat: hook/tension/revelation/resolution")
    sections.append("voiceover: (second person 'you', present tense, storytelling)")
    sections.append("visual: (cinematic, poetic -- emotion not illustration)")
    sections.append("camera: (dolly-in, tracking, crane, handheld, whip pan, static, orbital)")
    sections.append("motion: (what moves -- particles drift, cracks spread, petals lift)")
    sections.append("sound: (ambient -- heartbeat, rain, silence, low hum)")
    sections.append("emotion: (what the viewer should feel)")
    sections.append("duration: (seconds)")
    sections.append("caption: (3-5 word bold overlay -- must work without sound)")

    if voice_profile:
        sections.append(_build_voice_section(voice_profile))

    if rules:
        sections.append("\n--- RULEBOOK (follow these rules) ---")
        for r in rules:
            cat = f"[{r.category}] " if r.category else ""
            sections.append(f"- {cat}{r.rule}")

    if top_hooks:
        sections.append("\n--- TOP HOOKS (use as inspiration) ---")
        for h in top_hooks[:5]:
            rating = f" ({h.rating})" if h.rating else ""
            sections.append(f'- "{h.text}"{rating}')

    if patterns["hit_notes"]:
        sections.append("\n--- WHAT WORKS (from past hits) ---")
        for note in patterns["hit_notes"][:5]:
            sections.append(f"- {note}")

    if patterns["miss_notes"]:
        sections.append("\n--- WHAT TO AVOID (from past misses) ---")
        for note in patterns["miss_notes"][:5]:
            sections.append(f"- {note}")

    return "\n".join(sections)


def _build_rewrite_prompt(script: object, feedback_text: str, rules: list, voice_profile: list) -> str:
    """Build the full prompt for rewriting an existing script."""
    sections = []

    sections.append(f"Rewrite this {script.style} video script about: {script.topic}")
    sections.append(f"Target duration: {script.duration_target} seconds")
    sections.append("Must follow the 4-beat narrative arc: hook, tension, revelation, resolution.")

    sections.append(f"\n--- ORIGINAL SCRIPT ---\n{script.full_script}")
    sections.append(f"\n--- ORIGINAL HOOK ---\n{script.hook}")

    if feedback_text:
        sections.append(f"\n--- FEEDBACK ---\n{feedback_text}")

    if voice_profile:
        sections.append(_build_voice_section(voice_profile))

    if rules:
        sections.append("\n--- RULEBOOK ---")
        for r in rules:
            cat = f"[{r.category}] " if r.category else ""
            sections.append(f"- {cat}{r.rule}")

    sections.append("\nAddress the feedback while keeping what worked. Follow the 4-beat arc. Include captions for every scene.")

    return "\n".join(sections)
