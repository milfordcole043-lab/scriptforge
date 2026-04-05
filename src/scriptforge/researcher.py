from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from scriptforge import db
from scriptforge.models import Character, PromptRule, Scene


# --- Image Quality Review ---


def review_image(image_path: Path, character: Character, scene: Scene) -> tuple[int, list[str], str]:
    """Review a generated image for quality and character consistency.
    Returns (score 1-10, issues list, suggested prompt adjustment)."""
    # Since we can't run vision models locally, we do structural prompt analysis
    # to predict likely issues and build corrective prompts
    issues: list[str] = []
    adjustments: list[str] = []
    score = 10

    # Check 1: Character description completeness in the original prompt
    # If the prompt that generated this image was weak, the image likely has issues
    char_keywords = _extract_character_keywords(character)
    scene_keywords = _extract_scene_keywords(scene)

    # Check 2: Lighting specificity — vague lighting = inconsistent results
    lighting = (scene.lighting or "").lower()
    if len(lighting) < 15:
        issues.append("Lighting description too vague — may produce inconsistent results")
        adjustments.append("Add more specific lighting: color temperature, direction, source")
        score -= 1

    # Check 3: Emotion specificity — generic emotions produce generic faces
    emotion = (scene.character_emotion or "").lower()
    if emotion in ("sad", "happy", "angry", "calm", "neutral"):
        issues.append(f"Emotion '{emotion}' is too generic — AI defaults to stock expressions")
        adjustments.append(f"Replace '{emotion}' with a specific physical description: "
                          f"'eyes heavy, jaw tight, trying not to cry'")
        score -= 2

    # Check 4: Hand/body description — unanchored hands produce artifacts
    action = (scene.character_action or "").lower()
    hand_anchored = any(w in action for w in ["grip", "hold", "press", "rest", "touch",
                                                "place", "clutch", "wrap", "lean"])
    if "hand" in action or "finger" in action or "thumb" in action:
        if not hand_anchored:
            issues.append("Hands described but not anchored to an object — risk of distortion")
            adjustments.append("Anchor hands: 'fingers gripping the phone edge' not 'fingers moving'")
            score -= 2

    # Check 5: Camera angle clarity
    camera = (scene.camera or "").lower()
    if not any(w in camera for w in ["close-up", "wide", "medium", "dolly", "static",
                                      "tracking", "crane", "overhead", "pov"]):
        issues.append("Camera angle not specified — may produce inconsistent framing")
        adjustments.append("Add explicit camera: 'static close-up' or 'slow dolly-in'")
        score -= 1

    # Check 6: Scene complexity — too many elements = confusion
    location = (scene.location or "")
    if location.count(",") > 4:
        issues.append("Location description has too many elements — AI may deprioritize some")
        adjustments.append("Simplify location to 2-3 key elements")
        score -= 1

    # Check 7: Duration-appropriate detail
    if scene.duration_seconds <= 3 and len(action) > 80:
        issues.append("Too much action described for a 3-second clip — simplify")
        adjustments.append("For short clips, describe one simple action")
        score -= 1

    # Build suggested prompt adjustment
    adjustment_text = ". ".join(adjustments) if adjustments else "No adjustments needed"

    return max(1, score), issues, adjustment_text


def _extract_character_keywords(character: Character) -> list[str]:
    """Extract key visual keywords from character description."""
    text = f"{character.appearance} {character.clothing}".lower()
    return [w.strip() for w in re.split(r'[,\s]+', text) if len(w.strip()) > 3]


def _extract_scene_keywords(scene: Scene) -> list[str]:
    """Extract key visual keywords from scene."""
    text = f"{scene.location} {scene.lighting} {scene.character_action}".lower()
    return [w.strip() for w in re.split(r'[,\s]+', text) if len(w.strip()) > 3]


# --- Prompt Grader ---


_ELEMENT_PATTERNS: dict[str, list[str]] = {
    "subject": ["person", "figure", "object", "face", "hand", "silhouette", "flower", "heart",
                 "glass", "thread", "orb", "window", "door", "light", "shadow",
                 "woman", "man", "girl", "boy", "character"],
    "location": ["bedroom", "kitchen", "street", "window", "door", "room", "bus",
                  "rain", "night", "morning", "bathroom", "hallway", "car", "couch",
                  "bed", "floor", "counter", "desk", "stairs"],
    "camera": ["dolly", "tracking", "crane", "handheld", "whip", "static", "orbital",
                "close-up", "wide", "overhead", "pov", "pan", "tilt", "zoom"],
    "motion": ["drift", "spread", "lift", "fall", "float", "pulse", "unravel", "scatter",
                "grow", "shrink", "fade", "crack", "shatter", "sway", "flicker"],
    "lighting": ["golden", "amber", "neon", "soft", "harsh", "backlit", "rim", "god rays",
                  "candlelight", "moonlight", "cold blue", "warm", "shadow", "silhouette"],
    "sound": ["heartbeat", "rain", "silence", "hum", "wind", "birdsong", "static",
              "breathing", "glass", "thunder", "underwater", "ambient"],
    "style": ["cinematic", "documentary", "noir", "35mm", "grain", "anamorphic",
              "dreamlike", "surreal", "ethereal", "moody", "intimate"],
    "atmosphere": ["warm", "cold", "muted", "high contrast", "desaturated", "vibrant",
                    "foggy", "hazy", "crisp", "dark", "bright"],
}


def grade_prompt(prompt: str, prompt_rules: list[PromptRule]) -> tuple[int, list[str], str]:
    """Score a video prompt 0-100 based on prompt rules. Returns (score, missing, enhanced_prompt)."""
    prompt_lower = prompt.lower()
    total_weight = 0
    earned_weight = 0
    missing: list[str] = []

    for rule in prompt_rules:
        element = rule.element
        total_weight += rule.weight

        if element == "avoid":
            # Check that text/labels/words are NOT present
            bad_words = ["text", "label", "title card", "subtitle", "words on screen"]
            if not any(w in prompt_lower for w in bad_words):
                earned_weight += rule.weight
            else:
                missing.append(f"{element}: {rule.rule}")
        elif element == "structure":
            # Video prompts with labelled sections run 100-150 words — that's correct
            word_count = len(prompt.split())
            if word_count <= 150:
                earned_weight += rule.weight
            else:
                missing.append(f"{element}: prompt is {word_count} words (max 150)")
        elif element in _ELEMENT_PATTERNS:
            patterns = _ELEMENT_PATTERNS[element]
            if any(p in prompt_lower for p in patterns):
                earned_weight += rule.weight
            else:
                missing.append(f"{element}: {rule.rule}")
        else:
            # Unknown element — skip gracefully
            total_weight -= rule.weight

    score = round(earned_weight / total_weight * 100) if total_weight > 0 else 100

    # Build enhanced prompt if score < 70
    enhanced = prompt
    if score < 70:
        enhanced = _enhance_prompt(prompt, missing, prompt_rules)

    return score, missing, enhanced


def _enhance_prompt(prompt: str, missing: list[str], rules: list[PromptRule]) -> str:
    """Auto-enhance a prompt by adding missing elements, context-aware for POV vs narrator."""
    additions: list[str] = []
    missing_elements = {m.split(":")[0].strip() for m in missing}
    is_pov = "talking directly to camera" in prompt.lower() or "selfie" in prompt.lower()

    if "camera" in missing_elements:
        if is_pov:
            additions.append("Phone camera, slightly below eye level, subtle handheld wobble")
        else:
            additions.append("Slow dolly-in, cinematic framing")
    if "lighting" in missing_elements:
        additions.append("Soft warm lighting with subtle shadows")
    if "motion" in missing_elements:
        if is_pov:
            additions.append("Subtle weight shift, slight head movement while speaking")
        else:
            additions.append("Gentle movement, settling into stillness")
    if "atmosphere" in missing_elements:
        additions.append("Muted warm tones, high contrast")
    if "style" in missing_elements:
        additions.append("Cinematic, 35mm film grain, shallow depth of field")
    if "sound" in missing_elements:
        additions.append("Ambient silence with distant hum")

    if additions:
        return prompt.rstrip(".") + ". " + ". ".join(additions) + "."
    return prompt


def extract_findings_from_text(text: str, topic: str, source_url: str | None = None,
                                source_title: str | None = None) -> list[dict]:
    """Extract actionable findings from analyzed text. Returns list of finding dicts."""
    findings: list[dict] = []

    # Category keywords to detect
    category_keywords = {
        "hook": ["hook", "opening", "first line", "scroll stop", "attention"],
        "pacing": ["pacing", "rhythm", "pause", "silence", "beat", "timing"],
        "visual": ["visual", "image", "shot", "frame", "composition"],
        "camera": ["camera", "dolly", "tracking", "crane", "movement"],
        "lighting": ["lighting", "light", "shadow", "exposure", "contrast"],
        "sound": ["sound", "audio", "ambient", "music", "silence"],
        "storytelling": ["story", "narrative", "arc", "emotion", "character"],
        "prompt": ["prompt", "describe", "instruction", "generate"],
    }

    # Split text into sentences and look for actionable patterns
    sentences = re.split(r'[.!?]\s+', text)
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 20 or len(sentence) > 300:
            continue

        # Detect category
        s_lower = sentence.lower()
        detected_category = "prompt"  # default
        for cat, keywords in category_keywords.items():
            if any(kw in s_lower for kw in keywords):
                detected_category = cat
                break

        # Only keep sentences that sound like techniques/rules
        action_words = ["always", "never", "use", "avoid", "try", "include", "start",
                        "end", "make sure", "should", "must", "don't", "keep"]
        if any(w in s_lower for w in action_words):
            findings.append({
                "topic": topic,
                "finding": sentence,
                "category": detected_category,
                "source_url": source_url,
                "source_title": source_title,
                "confidence": "medium",
            })

    return findings


def pull_youtube_transcript(url: str) -> str | None:
    """Pull transcript text from a YouTube video URL."""
    from youtube_transcript_api import YouTubeTranscriptApi

    # Extract video ID from URL
    video_id = None
    if "v=" in url:
        video_id = url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        video_id = url.split("youtu.be/")[1].split("?")[0]

    if not video_id:
        return None

    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id)
        return " ".join(entry.text for entry in transcript)
    except Exception:
        return None
