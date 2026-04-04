from __future__ import annotations

import sqlite3

from scriptforge import db
from scriptforge.config import WPM
from scriptforge.models import Character, Scene, Script, StoryTemplate

# --- Rule categories for contextual selection ---
_BEAT_RULES: dict[str, set[str]] = {
    "hook": {"hook", "caption", "visual", "prompt"},
    "tension": {"emotion", "pacing", "character", "location"},
    "revelation": {"structure", "storytelling", "prompt"},
    "resolution": {"voice", "structure", "pacing"},
}


# --- Template matching ---


def match_template(
    topic: str,
    conn: sqlite3.Connection,
    override_name: str | None = None,
) -> tuple[StoryTemplate | None, str]:
    """Match the best story template for a topic. Returns (template, reason)."""
    templates = db.get_all_templates(conn)
    if not templates:
        return None, "no templates available"

    # Manual override
    if override_name:
        t = db.get_template_by_name(conn, override_name)
        if t:
            return t, "manually selected"
        # Fall through to auto-match if name not found

    topic_lower = topic.lower()
    recent_ids = set(db.get_recent_template_ids(conn, limit=3))

    best_template = templates[0]
    best_score = -999.0
    best_keywords: list[str] = []
    any_keyword_hit = False

    for t in templates:
        # Keyword scoring — check if keyword appears as substring in topic
        matched = [kw for kw in t.matching_keywords if kw.lower() in topic_lower]
        score = float(len(matched))
        if matched:
            any_keyword_hit = True

        # Success rate bonus
        score += t.success_rate * 0.5

        # Recency penalty
        if t.id in recent_ids:
            score -= 3.0

        if score > best_score:
            best_score = score
            best_template = t
            best_keywords = matched

    # Default to THE MIRROR only if NO template had any keyword match
    if not any_keyword_hit and best_score <= 0:
        mirror = db.get_template_by_name(conn, "mirror")
        if mirror:
            return mirror, "default (no strong keyword match)"

    if best_keywords:
        reason = f"matched keywords: {', '.join(best_keywords)}"
    else:
        reason = f"highest score ({best_template.name})"
    return best_template, reason


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
                        scene_index: int = 0,
                        outfit_override: str | None = None) -> str:
    """Build a labelled, character-driven video prompt with temporal flow and connectivity."""
    sections = []

    # [SCENE] — location
    if scene.location:
        sections.append(f"[SCENE] {scene.location}")

    # [SUBJECT] — character + emotion
    if character:
        clothing = outfit_override or character.clothing
        emotion_cue = f", {scene.character_emotion}" if scene.character_emotion else ""
        sections.append(
            f"[SUBJECT] A {character.gender} in {character.age} with {character.appearance}, "
            f"wearing {clothing}{emotion_cue}"
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
                           scene_index: int = 0,
                           outfit_override: str | None = None) -> str:
    """Build a POV lip-sync video prompt for VEED Fabric with connectivity."""
    sections = []

    if scene.location:
        sections.append(f"[SCENE] {scene.location}")

    clothing = outfit_override or character.clothing
    emotion_cue = f", {scene.character_emotion}" if scene.character_emotion else ""
    sections.append(
        f"[SUBJECT] A {character.gender} in {character.age} with {character.appearance}, "
        f"wearing {clothing}{emotion_cue}"
    )

    # Continuity for scenes 2+
    if prev_scene and scene_index > 0:
        sections.append(
            f"[CONTINUITY] Character was just {prev_scene.character_action}. "
            f"Now {scene.character_action}. Eyes remain focused on camera throughout"
        )
    elif scene.character_action:
        sections.append(f"[ACTION] {scene.character_action}")

    sections.append("[SPEECH] Talking directly to camera, eyes locked on camera lens, clear mouth articulation, natural lip movement")

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
                                hook_emotion: str = "",
                                outfit_override: str | None = None) -> str:
    """Build a Flux Pro prompt for a POV selfie reference portrait with emotional state."""
    clothing = outfit_override or character.clothing
    parts = [
        f"A {character.gender} in {character.age} with {character.appearance}, "
        f"wearing {clothing}",
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
    parts.append("Eyes looking directly into camera lens, maintaining eye contact. "
                 "Selfie camera angle, slightly below eye level. Unposed, raw, candid. "
                 "Shot on phone camera. Consistent lighting throughout")
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


# --- Variety tracking ---


def _extract_recent_variety(conn: sqlite3.Connection, limit: int = 3) -> dict:
    """Extract locations, lighting, emotions, cameras, outfits from the last N scripts."""
    scripts = db.list_scripts(conn)[:limit]
    locations: list[str] = []
    lighting: list[str] = []
    emotions: list[str] = []
    cameras: list[str] = []
    templates: list[str] = []
    outfits: list[str] = []

    for s in scripts:
        if s.template_id:
            t = db.get_template(conn, s.template_id)
            if t:
                templates.append(t.name)
        if s.character_id:
            char = db.get_character(conn, s.character_id)
            if char and char.clothing and char.clothing not in outfits:
                outfits.append(char.clothing)
        for scene in s.scenes:
            if scene.location and scene.location not in locations:
                locations.append(scene.location)
            if scene.lighting and scene.lighting not in lighting:
                lighting.append(scene.lighting)
            if scene.character_emotion and scene.character_emotion not in emotions:
                emotions.append(scene.character_emotion)
            if scene.camera and scene.camera not in cameras:
                cameras.append(scene.camera)

    return {
        "locations": locations[:6],
        "lighting": lighting[:6],
        "emotions": emotions[:6],
        "cameras": cameras[:6],
        "templates": templates[:3],
        "outfits": outfits[:3],
    }


# --- Write context ---


def _pick_outfit(conn: sqlite3.Connection, character_id: int | None,
                  recent_outfits: list[str]) -> str | None:
    """Pick an outfit from character wardrobe that wasn't used recently."""
    if not character_id:
        return None
    char = db.get_character(conn, character_id)
    if not char or not char.wardrobe:
        return None
    # Pick first outfit not in recent list
    for outfit in char.wardrobe:
        if outfit not in recent_outfits:
            return outfit
    # All used recently — just pick the first one
    return char.wardrobe[0]


def build_write_context(
    conn: sqlite3.Connection,
    topic: str,
    style: str,
    duration_target: int,
    mode: str = "narrator",
    template_name: str | None = None,
    character_id: int | None = None,
) -> dict:
    """Assemble all context needed to write a new script."""
    rules = db.get_active_rules(conn)
    top_hooks = db.get_top_hooks(conn, limit=10)
    patterns = analyze_feedback_patterns(conn)
    voice_profile = db.get_voice_profile(conn)
    scene_patterns = db.analyze_scene_feedback(conn)
    recent_variety = _extract_recent_variety(conn)

    # Template matching
    template, template_reason = match_template(topic, conn, override_name=template_name)

    # Outfit selection from wardrobe
    outfit = _pick_outfit(conn, character_id, recent_variety.get("outfits", []))

    # Mode-aware voice profile filtering
    filtered_profile = _filter_voice_profile(voice_profile, mode)

    prompt = _build_write_prompt(topic, style, duration_target, rules, top_hooks, patterns,
                                  filtered_profile, mode, scene_patterns, template=template,
                                  recent_variety=recent_variety, outfit=outfit)

    return {
        "topic": topic,
        "style": style,
        "duration_target": duration_target,
        "rules": rules,
        "top_hooks": top_hooks,
        "feedback_patterns": patterns,
        "voice_profile": filtered_profile,
        "template": template,
        "template_reason": template_reason,
        "recent_variety": recent_variety,
        "outfit": outfit,
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


def _select_rules_for_beat(rules: list, beat: str,
                           rule_categories: set[str] | None = None) -> list:
    """Select the 3-4 most relevant rules for a specific beat."""
    relevant_categories = rule_categories if rule_categories is not None else _BEAT_RULES.get(beat, set())
    selected = [r for r in rules if r.category in relevant_categories]
    return selected[:4]


def _build_contextual_rules_section(rules: list,
                                    template: StoryTemplate | None = None) -> str:
    """Build per-beat rule sections instead of dumping everything."""
    sections = []
    sections.append("\n--- RULES PER BEAT (apply the rules listed under each beat) ---")

    if template:
        beat_list = [(b["beat"], b["beat"].upper().replace("_", " ")) for b in template.beat_structure]
    else:
        beat_list = [("hook", "HOOK"), ("tension", "TENSION"),
                     ("revelation", "REVELATION"), ("resolution", "RESOLUTION")]

    for beat_name, label in beat_list:
        # Use template's rule_categories if available
        cats = None
        if template:
            for b in template.beat_structure:
                if b["beat"] == beat_name:
                    cats = set(b.get("rule_categories", []))
                    break
        beat_rules = _select_rules_for_beat(rules, beat_name, rule_categories=cats)
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
    template: StoryTemplate | None = None,
    recent_variety: dict | None = None,
    outfit: str | None = None,
) -> str:
    """Build the full prompt for writing a new script."""
    wpm = WPM
    word_target = duration_target * wpm // 60
    sections = []

    sections.append(f"Write a {style} video script about: {topic}")
    sections.append(f"Target duration: {duration_target} seconds (~{word_target} words at {wpm} wpm)")
    sections.append(f"Mode: {mode}")
    if outfit:
        sections.append(f"Character outfit for this video: {outfit}")

    if template:
        # Template-driven narrative arc
        n_beats = len(template.beat_structure)
        sections.append(f"\n--- STORY TEMPLATE: {template.name} ---")
        sections.append(f"Structure: {template.description}")
        sections.append(f"Visual style: {template.visual_style}")
        sections.append(f"\n--- NARRATIVE ARC ({n_beats} beats, every script needs all {n_beats}) ---")
        for i, b in enumerate(template.beat_structure, 1):
            dur_min = b["duration_min"]
            dur_max = b["duration_max"]
            # POV lip-sync constraint: reduce max duration for longer beats
            if mode == "pov" and dur_max > 7:
                dur_max = max(dur_min, dur_max - 2)
            sections.append(f"{i}. {b['beat'].upper()} ({dur_min}-{dur_max}s) -- {b['description']}")
    else:
        sections.append("\n--- NARRATIVE ARC (4 beats, every script needs all 4) ---")
        if mode == "pov":
            sections.append("1. HOOK (2-3s) -- Start in a personal moment. Make the viewer FEEL before they learn. Visual hook must work without sound.")
            sections.append("2. TENSION (6-10s) -- Deepen the feeling. Make the viewer need the answer. One emotion, let it breathe.")
            sections.append("3. REVELATION (7-10s) -- The science/insight as a twist. Reframes everything. Keep it tight — lip sync degrades on longer clips.")
            sections.append("4. RESOLUTION (5-7s) -- Reframe, not advice. Short. Powerful. Let the viewer draw their own conclusion.")
        else:
            sections.append("1. HOOK (2-3s) -- Start in a personal moment. Make the viewer FEEL before they learn. Visual hook must work without sound.")
            sections.append("2. TENSION (8-12s) -- Deepen the feeling. Make the viewer need the answer. One emotion, let it breathe.")
            sections.append("3. REVELATION (10-15s) -- The science/insight as a twist. Reframes everything. Feeling first, facts second.")
            sections.append("4. RESOLUTION (5-7s) -- Reframe, not advice. Short. Powerful. Let the viewer draw their own conclusion.")
    sections.append("Build in 1-2 second pauses between beats where only visuals + sound carry the moment.")

    # Beat names for scene format
    if template:
        beat_names = "/".join(b["beat"] for b in template.beat_structure)
    else:
        beat_names = "hook/tension/revelation/resolution"

    sections.append("\n--- SCENE FORMAT (for each scene) ---")
    sections.append(f"beat: {beat_names}")
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
        sections.append(_build_contextual_rules_section(rules, template=template))

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

    if recent_variety:
        has_data = any(recent_variety.get(k) for k in ("locations", "lighting", "emotions", "cameras", "outfits"))
        if has_data:
            sections.append("\n--- AVOID REPEATING (from last 3 scripts — choose something DIFFERENT) ---")
            if recent_variety.get("locations"):
                sections.append(f"Locations used: {', '.join(recent_variety['locations'])}")
            if recent_variety.get("lighting"):
                sections.append(f"Lighting used: {', '.join(recent_variety['lighting'])}")
            if recent_variety.get("emotions"):
                sections.append(f"Emotional starts: {', '.join(recent_variety['emotions'])}")
            if recent_variety.get("cameras"):
                sections.append(f"Camera styles: {', '.join(recent_variety['cameras'])}")
            if recent_variety.get("templates"):
                sections.append(f"Templates used: {', '.join(recent_variety['templates'])}")
            if recent_variety.get("outfits"):
                sections.append(f"Outfits used: {', '.join(recent_variety['outfits'])}")
            sections.append("Each video must feel like a different moment in a different day.")

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


# --- Topic generation ---


def _build_topic_prompt(
    templates: list[StoryTemplate],
    existing_topics: list[str],
    past_suggestions: list[str],
    findings: list,
    patterns: dict,
    count: int,
) -> str:
    """Build the prompt for Claude to generate topic suggestions."""
    sections = []

    sections.append(f"Generate exactly {count} specific video topic ideas for a faceless YouTube channel.")
    sections.append("Niche: psychology, the human body, and relationships.")
    sections.append("Each topic must be phrased as a scroll-stopping hook — specific, not broad.")
    sections.append('Example of specific: "why your gut makes better dating decisions than your brain"')
    sections.append('Example of too broad: "the gut-brain connection"')

    sections.append(f"\n--- STORY TEMPLATES (spread topics across these, don't use the same one more than twice) ---")
    for t in templates:
        keywords = ", ".join(t.matching_keywords[:5])
        sections.append(f"- {t.name}: {t.description} (keywords: {keywords})")

    if existing_topics:
        sections.append("\n--- EXISTING SCRIPTS (avoid these topics) ---")
        for topic in existing_topics[:20]:
            sections.append(f"- {topic}")

    if past_suggestions:
        sections.append("\n--- PAST SUGGESTIONS (avoid repeating) ---")
        for topic in past_suggestions[:20]:
            sections.append(f"- {topic}")

    if findings:
        sections.append("\n--- RESEARCH FINDINGS (use as inspiration) ---")
        for f in findings[:10]:
            sections.append(f"- [{f.category}] {f.finding}")

    if patterns.get("hit_notes"):
        sections.append("\n--- WHAT WORKS (from past hits) ---")
        for note in patterns["hit_notes"][:5]:
            sections.append(f"- {note}")

    if patterns.get("miss_notes"):
        sections.append("\n--- WHAT TO AVOID (from past misses) ---")
        for note in patterns["miss_notes"][:5]:
            sections.append(f"- {note}")

    sections.append(f"\nReturn ONLY a JSON array of {count} objects, each with:")
    sections.append('  "topic": the specific topic phrased as a hook')
    sections.append('  "template": which template name fits best (e.g. "THE MIRROR")')
    sections.append('  "angle": the unique perspective or hook that makes this specific')
    sections.append('  "why": one sentence on why this would perform well')
    sections.append("\nNo markdown, no explanation. Just the JSON array.")

    return "\n".join(sections)


def generate_topics(conn: sqlite3.Connection, count: int = 5) -> list[dict]:
    """Generate topic suggestions using Claude, informed by templates and history."""
    import json

    import anthropic
    from scriptforge.config import ANTHROPIC_API_KEY, retry_api_call

    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")

    templates = db.get_all_templates(conn)
    scripts = db.list_scripts(conn)
    existing_topics = [s.topic for s in scripts]
    past_suggestions = [t["topic"] for t in db.get_generated_topics(conn)]
    findings = db.get_findings(conn)
    patterns = analyze_feedback_patterns(conn)

    prompt = _build_topic_prompt(templates, existing_topics, past_suggestions,
                                  findings, patterns, count)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _call_claude() -> list[dict]:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise ValueError("Could not parse topics JSON from response")

    topics = retry_api_call(_call_claude, label="Claude topic generation")

    # Validate structure
    validated = []
    for t in topics[:count]:
        validated.append({
            "topic": t.get("topic", ""),
            "template": t.get("template", "THE MIRROR"),
            "angle": t.get("angle", ""),
            "why": t.get("why", ""),
        })

    db.save_generated_topics(conn, validated)
    return validated
