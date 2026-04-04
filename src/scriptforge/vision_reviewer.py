from __future__ import annotations

import base64
import json
import sqlite3
import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

from scriptforge import db
from scriptforge.config import ANTHROPIC_API_KEY, COST_CLAUDE_VISION, retry_api_call
from scriptforge.models import Character, SceneReview, Script, VideoReview

console = Console()


def extract_scene_frames(script: Script, output_dir: Path) -> list[Path]:
    """Extract one frame per scene at the midpoint of each scene's duration."""
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    cumulative_seconds = 0.0

    for i, scene in enumerate(script.scenes):
        frame_path = frames_dir / f"frame_{i + 1:02d}.png"
        if frame_path.exists():
            frames.append(frame_path)
            cumulative_seconds += scene.duration_seconds
            continue

        midpoint = cumulative_seconds + scene.duration_seconds / 2.0
        cmd = [
            "ffmpeg", "-y", "-ss", str(midpoint),
            "-i", str(output_dir / "final.mp4"),
            "-frames:v", "1", "-q:v", "2",
            str(frame_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            console.print(f"  [yellow]Could not extract frame for scene {i + 1}[/yellow]")
        else:
            console.print(f"    Extracted: {frame_path.name} at {midpoint:.1f}s")
        frames.append(frame_path)
        cumulative_seconds += scene.duration_seconds

    return frames


def _encode_image(path: Path) -> str | None:
    """Base64 encode an image file."""
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _review_frame_with_claude(frame_path: Path, ref_path: Path | None,
                               character: Character, scene_index: int,
                               scene_beat: str, scene_emotion: str,
                               scene_lighting: str, scene_camera: str) -> SceneReview:
    """Send a frame to Claude's vision API for quality analysis."""
    import anthropic

    frame_b64 = _encode_image(frame_path)
    if not frame_b64:
        return SceneReview(scene_index=scene_index, score=5, issues=["Could not load frame"],
                           suggestions=["Re-render this scene"])

    messages_content = []

    # Add reference portrait if available
    if ref_path and ref_path.exists():
        ref_b64 = _encode_image(ref_path)
        if ref_b64:
            messages_content.append({
                "type": "text",
                "text": "Reference portrait of the character (for consistency comparison):"
            })
            messages_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": ref_b64}
            })

    messages_content.append({
        "type": "text",
        "text": f"Scene {scene_index + 1} frame to review:"
    })
    messages_content.append({
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": frame_b64}
    })

    prompt = (
        f"Review this video frame for quality. The character should be: "
        f"{character.gender}, {character.age}, {character.appearance}, wearing {character.clothing}.\n\n"
        f"Scene beat: {scene_beat}\n"
        f"Expected emotion: {scene_emotion}\n"
        f"Expected lighting: {scene_lighting}\n"
        f"Expected camera: {scene_camera}\n\n"
        f"Respond in this exact JSON format:\n"
        f'{{"score": 1-10, "issues": ["list of specific issues"], '
        f'"suggestions": ["list of specific improvements"]}}\n\n'
        f"Check for:\n"
        f"1. Character consistency (face, hair, clothing match reference?)\n"
        f"2. AI artifacts (extra fingers, morphing face, distorted objects, garbled text)\n"
        f"3. Emotion match (does the character's expression match '{scene_emotion}'?)\n"
        f"4. Lighting correctness (does it match '{scene_lighting}'?)\n"
        f"5. Camera angle (does it match '{scene_camera}'?)\n"
        f"Be honest and specific. If it looks good, say so."
    )
    messages_content.append({"type": "text", "text": prompt})

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _call_claude() -> dict:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": messages_content}],
        )
        text = response.content[0].text
        # Extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"score": 5, "issues": ["Could not parse review"], "suggestions": []}

    try:
        result = retry_api_call(_call_claude, label=f"Claude vision (scene {scene_index + 1})")
    except Exception:
        return SceneReview(scene_index=scene_index, score=5,
                           issues=["Vision API call failed"],
                           suggestions=["Review manually"])

    return SceneReview(
        scene_index=scene_index,
        score=max(1, min(10, result.get("score", 5))),
        issues=result.get("issues", []),
        suggestions=result.get("suggestions", []),
    )


def review_rendered_video(script: Script, character: Character, output_dir: Path,
                           conn: sqlite3.Connection | None = None) -> VideoReview:
    """Review a rendered video by extracting and analyzing frames."""
    final_path = output_dir / "final.mp4"
    if not final_path.exists():
        return VideoReview(script_id=script.id, scene_reviews=[], overall_score=0,
                           sync_issues=["No rendered video found"], rerender_needed=[])

    console.print("  Extracting scene frames...")
    frames = extract_scene_frames(script, output_dir)

    # Find reference portrait
    ref_path = None
    if character.reference_image_path:
        ref_path = Path(character.reference_image_path)

    console.print("  Analyzing frames with Claude vision...")
    scene_reviews: list[SceneReview] = []
    for i, (scene, frame) in enumerate(zip(script.scenes, frames)):
        if not frame.exists():
            scene_reviews.append(SceneReview(scene_index=i, score=0,
                                             issues=["Frame not extracted"]))
            continue

        sr = _review_frame_with_claude(
            frame, ref_path, character, i,
            scene.beat, scene.character_emotion, scene.lighting, scene.camera,
        )
        scene_reviews.append(sr)
        console.print(f"    Scene {i + 1} [{scene.beat}]: {sr.score}/10")

        if conn:
            db.log_render_step(conn, script.id, f"vision_review_scene_{i + 1}",
                               "claude-sonnet", 0, COST_CLAUDE_VISION)

    overall = sum(sr.score for sr in scene_reviews) / len(scene_reviews) if scene_reviews else 0
    rerender = auto_flag_rerender_from_reviews(scene_reviews)

    # Check audio-visual sync
    voiceover_path = output_dir / "voiceover.mp3"
    sync_issues = []
    if voiceover_path.exists():
        sync_issues = review_audio_visual_sync(script, voiceover_path)

    review = VideoReview(
        script_id=script.id,
        scene_reviews=scene_reviews,
        overall_score=round(overall, 1),
        sync_issues=sync_issues,
        rerender_needed=rerender,
    )

    if conn:
        db.save_video_review(conn, review)

    return review


def review_audio_visual_sync(script: Script, voiceover_path: Path) -> list[str]:
    """Check if emotional peaks align with scene transitions."""
    issues: list[str] = []
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", compute_type="int8")
        segments, _ = model.transcribe(str(voiceover_path), word_timestamps=True)

        # Build word timeline
        emotional_keywords = {"hurt", "hurts", "ache", "pain", "withdrawal", "addiction",
                              "dopamine", "cocaine", "brain", "chemistry", "changes",
                              "stop", "can't", "weak", "broken"}
        keyword_times: list[tuple[str, float]] = []
        for seg in segments:
            if seg.words:
                for w in seg.words:
                    if w.word.strip().lower().rstrip(".,!?") in emotional_keywords:
                        keyword_times.append((w.word.strip(), w.start))

        # Calculate scene transition times
        transitions: list[float] = []
        cumulative = 0.0
        for scene in script.scenes:
            cumulative += scene.duration_seconds
            transitions.append(cumulative)

        # Check if keywords land near transitions (potential misalignment)
        for word, time in keyword_times:
            for t_idx, t_time in enumerate(transitions[:-1]):
                if abs(time - t_time) < 0.5:
                    issues.append(
                        f"Word '{word}' at {time:.1f}s lands right at scene {t_idx + 1}->{t_idx + 2} "
                        f"transition ({t_time:.1f}s) — may be cut off"
                    )
    except Exception:
        pass  # Whisper not available or audio issue — skip sync check

    return issues


def auto_flag_rerender_from_reviews(scene_reviews: list[SceneReview]) -> list[int]:
    """Return scene indices that need re-rendering."""
    critical_keywords = {"morphing", "extra finger", "distorted", "garbled", "deformed",
                         "six finger", "wrong face", "inconsistent character"}
    flagged: list[int] = []
    for sr in scene_reviews:
        if sr.score < 6:
            flagged.append(sr.scene_index)
            continue
        for issue in sr.issues:
            if any(kw in issue.lower() for kw in critical_keywords):
                flagged.append(sr.scene_index)
                break
    return flagged


def print_review(review: VideoReview) -> None:
    """Pretty-print a video review with Rich."""
    color = "green" if review.overall_score >= 7 else "yellow" if review.overall_score >= 5 else "red"
    console.print(f"\n[bold]Video Review[/bold] — Overall: [{color}]{review.overall_score}/10[/{color}]")

    table = Table(title="Scene Scores")
    table.add_column("#", style="dim")
    table.add_column("Score")
    table.add_column("Issues")
    table.add_column("Suggestions")
    for sr in review.scene_reviews:
        sc = "green" if sr.score >= 7 else "yellow" if sr.score >= 5 else "red"
        issues_str = "; ".join(sr.issues[:2]) if sr.issues else "None"
        sugg_str = "; ".join(sr.suggestions[:2]) if sr.suggestions else "None"
        table.add_row(str(sr.scene_index + 1), f"[{sc}]{sr.score}/10[/{sc}]",
                       issues_str[:60], sugg_str[:60])
    console.print(table)

    if review.sync_issues:
        console.print("\n[bold yellow]Sync Issues:[/bold yellow]")
        for issue in review.sync_issues:
            console.print(f"  - {issue}")

    if review.rerender_needed:
        scenes_str = ", ".join(str(i + 1) for i in review.rerender_needed)
        console.print(f"\n[bold red]Scenes flagged for re-render:[/bold red] {scenes_str}")
    else:
        console.print("\n[green]No re-render needed.[/green]")
    console.print()
