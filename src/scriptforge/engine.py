from __future__ import annotations

import sqlite3

from scriptforge import db
from scriptforge.config import WPM
from scriptforge.models import Character, Scene, Script

# --- Rule categories for contextual selection ---
_BEAT_RULES: dict[str, set[str]] = {
    "hook": {"hook", "caption", "visual", "prompt"},
    "tension": {"emotion", "pacing", "character", "location"},
    "revelation": {"structure", "storytelling", "prompt"},
    "resolution": {"voice", "structure", "pacing"},
}


# --- Temporal flow ---


def _build_temporal_motion(scene: Scene) -> str:
    """Build motion description with temporal phases based on duration."""
    motion = scene.motion or ""
    action = scene.character_action or ""
    if not motion and not action:
        return ""

    parts = motion.split(",") if motion else [action]
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return motion

    start = parts[0]
    middle = parts[1] if len(parts) > 1 else f"{start} intensifies"
    end = parts[-1] if len(parts) > 2 else "settling into stillness"

    if scene.duration_seconds >= 10 and len(parts) >= 2:
        return f"Initially {start}. Then {middle}. Finally {end}"
    else:
        rest = f"{parts[-1]} comes to rest" if len(parts) > 1 else f"{start}, then stillness"
        return f"Initially {start}. Then {rest}"


# --- Video prompt builders ---


def build_video_prompt(scene: Scene, character: Character | None = None,
                        prev_scene: Scene | None = None,
                        scenes: list[Scene] | None = None,
                        scene_index: int = 0) -> str:
    """Build a labelled, character-driven video prompt with temporal flow and connectivity."""
    sections = []

    # [SCENE] — location
    if scene.location:
        sections.append(f"[SCENE] {scene.location}")

    # [SUBJECT] — character + emotion
    if character:
        emotion_cue = f", {scene.character_emotion}" if scene.character_emotion else ""
        sections.append(
            f"[SUBJECT] A {character.gender} in {character.age} with {character.appearance}, "
            f"wearing {character.clothing}{emotion_cue}"
        )

    # Continuity note for scenes 2+
    if prev_scene and scene_index > 0:
        sections.append(
            f"[CONTINUITY] Continuation of previous scene. Character was just {prev_scene.character_action}. "
            f"Now {scene.character_action}"
        )
    elif scene.character_action:
        sections.append(f"[ACTION] {scene.character_action}")

    # [CAMERA]
    if scene.camera:
        sections.append(f"[CAMERA] {scene.camera}")

    # [LIGHTING] — with interpolation if scenes provided
    lighting = scene.lighting
    if scenes and len(scenes) > 1 and scene_index > 0:
        lighting = _interpolate_lighting(scenes, scene_index)
    if lighting:
        sections.append(f"[LIGHTING] {lighting}. Consistent lighting throughout")

    # [MOTION] — temporal flow
    temporal_motion = _build_temporal_motion(scene)
    if temporal_motion:
        sections.append(f"[MOTION] {temporal_motion}")

    # [STYLE]
    sections.append("[STYLE] Cinematic, intimate")

    return ". ".join(sections) + "."


def build_pov_video_prompt(scene: Scene, character: Character,
                           prev_scene: Scene | None = None,
                           scenes: list[Scene] | None = None,
                           scene_index: int = 0) -> str:
    """Build a POV lip-sync video prompt for VEED Fabric with connectivity."""
    sections = []

    if scene.location:
        sections.append(f"[SCENE] {scene.location}")

    emotion_cue = f", {scene.character_emotion}" if scene.character_emotion else ""
    sections.append(
        f"[SUBJECT] A {character.gender} in {character.age} with {character.appearance}, "
        f"wearing {character.clothing}{emotion_cue}"
    )

    # Continuity for scenes 2+
    if prev_scene and scene_index > 0:
        sections.append(
            f"[CONTINUITY] Character was just {prev_scene.character_action}. "
            f"Now {scene.character_action}"
        )
    elif scene.character_action:
        sections.append(f"[ACTION] {scene.character_action}")

    sections.append("[SPEECH] Talking directly to camera, clear mouth articulation, natural lip movement")

    # Light progression
    lighting = scene.lighting
    if scenes and len(scenes) > 1 and scene_index > 0:
        lighting = _interpolate_lighting(scenes, scene_index)
    if lighting:
        sections.append(f"[LIGHTING] {lighting}. Consistent lighting throughout")

    sections.append("[CAMERA] Phone camera perspective, slightly below eye level, subtle handheld wobble")
    sections.append("[STYLE] Raw, intimate, cinematic")

    return ". ".join(sections) + "."


def build_pov_reference_prompt(character: Character, lighting: str = "",
                                hook_emotion: str = "") -> str:
    """Build a Flux Pro prompt for a POV selfie reference portrait with emotional state."""
    parts = [
        f"A {character.gender} in {character.age} with {character.appearance}, "
        f"wearing {character.clothing}",
    ]
    # Emotional state from hook scene — far more important than generic smile
    if hook_emotion:
        parts.append(f"{hook_emotion}, lips slightly parted showing teeth")
    else:
        parts.append("Exhausted expression, lips slightly parted showing teeth, eyes heavy and tired")
    parts.append("Holding phone in selfie position")
    if lighting:
        parts.append(lighting)
    else:
        parts.append("Soft warm lighting")
    parts.append("Selfie camera angle, slightly below eye level. Unposed, raw, candid. Shot on phone camera. Consistent lighting throughout")
    return ". ".join(parts) + "."


# --- Light progression ---


def _interpolate_lighting(scenes: list[Scene], index: int) -> str:
    """Interpolate lighting between first and last scene for middle scenes."""
    if index == 0 or index >= len(scenes) - 1:
        return scenes[index].lighting

    first_lighting = scenes[0].lighting
    last_lighting = scenes[-1].lighting
    current_lighting = scenes[index].lighting

    # If the scene already has specific lighting, use it but add transition context
    if current_lighting and current_lighting != first_lighting:
        return current_lighting

    # Auto-interpolate based on position
    total = len(scenes) - 1
    progress = index / total

    if progress <= 0.33:
        return f"{first_lighting}, beginning to shift"
    elif progress <= 0.66:
        return f"{first_lighting} mixing with early traces of {last_lighting}"
    else:
        return f"Transitioning from {first_lighting} toward {last_lighting}"


# --- Write context ---


def build_write_context(
    conn: sqlite3.Connection,
    topic: str,
    style: str,
    duration_target: int,
    mode: str = "narrator",
) -> dict:
    """Assemble all context needed to write a new script."""
    rules = db.get_active_rules(conn)
    top_hooks = db.get_top_hooks(conn, limit=10)
    patterns = analyze_feedback_patterns(conn)
    voice_profile = db.get_voice_profile(conn)
    scene_patterns = db.analyze_scene_feedback(conn)

    # Mode-aware voice profile filtering
    filtered_profile = _filter_voice_profile(voice_profile, mode)

    prompt = _build_write_prompt(topic, style, duration_target, rules, top_hooks, patterns,
                                  filtered_profile, mode, scene_patterns)

    return {
        "topic": topic,
        "style": style,
        "duration_target": duration_target,
        "rules": rules,
        "top_hooks": top_hooks,
        "feedback_patterns": patterns,
        "voice_profile": filtered_profile,
        "prompt": prompt,
    }


def build_rewrite_context(conn: sqlite3.Connection, script_id: int) -> dict | None:
    """Assemble context needed to rewrite an existing script."""
    script = db.get_script(conn, script_id)
    if not script:
        return None

    rules = db.get_active_rules(conn)
    voice_profile = db.get_voice_profile(conn)
    filtered_profile = _filter_voice_profile(voice_profile, script.mode)
    feedback_entries = db.get_feedback_log(conn, script_id)
    feedback_text = "\n".join(f"- [{e.rating}] {e.notes}" for e in feedback_entries)

    prompt = _build_rewrite_prompt(script, feedback_text, rules, filtered_profile)

    return {
        "original_script": script,
        "feedback": feedback_text,
        "rules": rules,
        "voice_profile": filtered_profile,
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


# --- Voice profile filtering ---


def _filter_voice_profile(voice_profile: list, mode: str) -> list:
    """Filter voice profile by mode. Narrator gets non-pov, POV gets pov_* only."""
    if mode == "pov":
        return [vp for vp in voice_profile if vp.attribute.startswith("pov_")]
    return [vp for vp in voice_profile if not vp.attribute.startswith("pov_")]


def _build_voice_section(voice_profile: list) -> str:
    if not voice_profile:
        return ""
    lines = ["\n--- VOICE PROFILE ---"]
    for vp in voice_profile:
        # Strip pov_ prefix for cleaner display
        attr = vp.attribute.replace("pov_", "") if vp.attribute.startswith("pov_") else vp.attribute
        lines.append(f"- {attr}: {vp.value}")
    return "\n".join(lines)


# --- Contextual rule selection ---


def _select_rules_for_beat(rules: list, beat: str) -> list:
    """Select the 3-4 most relevant rules for a specific beat."""
    relevant_categories = _BEAT_RULES.get(beat, set())
    selected = [r for r in rules if r.category in relevant_categories]
    return selected[:4]


def _build_contextual_rules_section(rules: list) -> str:
    """Build per-beat rule sections instead of dumping everything."""
    sections = []
    sections.append("\n--- RULES PER BEAT (apply the rules listed under each beat) ---")

    for beat_name, label in [("hook", "HOOK"), ("tension", "TENSION"),
                              ("revelation", "REVELATION"), ("resolution", "RESOLUTION")]:
        beat_rules = _select_rules_for_beat(rules, beat_name)
        if beat_rules:
            sections.append(f"\n  {label}:")
            for r in beat_rules:
                sections.append(f"    - {r.rule}")

    return "\n".join(sections)


# --- Write prompt ---


def _build_write_prompt(
    topic: str,
    style: str,
    duration_target: int,
    rules: list,
    top_hooks: list,
    patterns: dict,
    voice_profile: list,
    mode: str = "narrator",
    scene_patterns: dict | None = None,
) -> str:
    """Build the full prompt for writing a new script."""
    wpm = WPM
    word_target = duration_target * wpm // 60
    sections = []

    sections.append(f"Write a {style} video script about: {topic}")
    sections.append(f"Target duration: {duration_target} seconds (~{word_target} words at {wpm} wpm)")
    sections.append(f"Mode: {mode}")

    sections.append("\n--- NARRATIVE ARC (4 beats, every script needs all 4) ---")
    sections.append("1. HOOK (2-3s) -- Start in a personal moment. Make the viewer FEEL before they learn. Visual hook must work without sound.")
    sections.append("2. TENSION (8-12s) -- Deepen the feeling. Make the viewer need the answer. One emotion, let it breathe.")
    sections.append("3. REVELATION (10-15s) -- The science/insight as a twist. Reframes everything. Feeling first, facts second.")
    sections.append("4. RESOLUTION (5-7s) -- Reframe, not advice. Short. Powerful. Let the viewer draw their own conclusion.")
    sections.append("Build in 1-2 second pauses between beats where only visuals + sound carry the moment.")

    sections.append("\n--- SCENE FORMAT (for each scene) ---")
    sections.append("beat: hook/tension/revelation/resolution")
    if mode == "pov":
        sections.append("dialogue: (first person 'I/me', raw speech, messy, real)")
    else:
        sections.append("voiceover: (second person 'you', present tense, storytelling)")
    sections.append("character_action: (what the character is physically doing -- small, human gestures)")
    sections.append("location: (specific real setting -- dark bedroom, messy sheets, kitchen counter)")
    sections.append("character_emotion: (internal state -- desperate longing, quiet recognition)")
    sections.append("camera: (dolly-in, tracking, crane, handheld, whip pan, static, orbital)")
    sections.append("lighting: (real light sources -- cold blue phone screen, warm amber dawn through window)")
    sections.append("motion: (describe with temporal flow: 'Initially X, then Y, finally Z')")
    sections.append("sound: (ambient -- silence, heartbeat, rain, distant birdsong)")
    sections.append("caption: (3-5 word bold overlay -- must work without sound)")
    sections.append("duration: (seconds)")

    if voice_profile:
        sections.append(_build_voice_section(voice_profile))

    # Contextual rules per beat instead of dumping all
    if rules:
        sections.append(_build_contextual_rules_section(rules))

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

    if scene_patterns and scene_patterns.get("patterns"):
        sections.append("\n--- DATA-DRIVEN INSIGHTS (from scene-level feedback) ---")
        for p in scene_patterns["patterns"][:8]:
            sections.append(f"- {p}")

    return "\n".join(sections)


def _build_rewrite_prompt(script: Script, feedback_text: str, rules: list, voice_profile: list) -> str:
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
        sections.append(_build_contextual_rules_section(rules))

    sections.append("\nAddress the feedback while keeping what worked. Follow the 4-beat arc. Include captions for every scene.")

    return "\n".join(sections)
