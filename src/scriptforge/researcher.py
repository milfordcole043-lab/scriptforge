from __future__ import annotations

import re
import sqlite3

from scriptforge import db
from scriptforge.models import PromptRule


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
            # Check word count under 80
            word_count = len(prompt.split())
            if word_count <= 80:
                earned_weight += rule.weight
            else:
                missing.append(f"{element}: prompt is {word_count} words (max 80)")
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
    """Auto-enhance a prompt by adding missing elements."""
    additions: list[str] = []

    missing_elements = {m.split(":")[0].strip() for m in missing}

    if "camera" in missing_elements:
        additions.append("Slow dolly-in, cinematic framing")
    if "lighting" in missing_elements:
        additions.append("Soft warm lighting with subtle shadows")
    if "motion" in missing_elements:
        additions.append("Gentle movement, particles drifting slowly")
    if "atmosphere" in missing_elements:
        additions.append("Muted warm tones, high contrast")
    if "style" in missing_elements:
        additions.append("Cinematic, 35mm film grain")
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
