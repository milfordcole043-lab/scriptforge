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
from scriptforge.models import (
    Character, SceneReview, Script, TransitionReview, VideoReview,
)

console = Console()


# --- Frame extraction ---


def extract_scene_frames(script: Script, output_dir: Path) -> list[list[Path]]:
    """Extract 3 frames per scene: start (0.5s in), mid, end (0.5s before end).

    Returns a list of lists — one list of 3 frame paths per scene.
    """
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    all_frames: list[list[Path]] = []
    cumulative = 0.0

    for i, scene in enumerate(script.scenes):
        dur = scene.duration_seconds
        scene_frames: list[Path] = []

        # Calculate 3 timestamps: start, mid, end
        t_start = cumulative + min(0.5, dur * 0.1)
        t_mid = cumulative + dur / 2.0
        t_end = cumulative + dur - min(0.5, dur * 0.1)

        for label, t in [("start", t_start), ("mid", t_mid), ("end", t_end)]:
            frame_path = frames_dir / f"frame_{i + 1:02d}_{label}.png"
            if frame_path.exists():
                scene_frames.append(frame_path)
                continue

            cmd = [
                "ffmpeg", "-y", "-ss", str(t),
                "-i", str(output_dir / "final.mp4"),
                "-frames:v", "1", "-q:v", "2",
                str(frame_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                console.print(f"  [yellow]Could not extract {label} frame for scene {i + 1}[/yellow]")
            else:
                console.print(f"    Extracted: {frame_path.name} at {t:.1f}s")
            scene_frames.append(frame_path)

        all_frames.append(scene_frames)
        cumulative += dur

    return all_frames


# --- Image encoding ---


def _detect_media_type(path: Path) -> str:
    """Detect image media type from file header bytes."""
    with open(path, "rb") as f:
        header = f.read(12)
    if header[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _encode_image(path: Path) -> tuple[str, str] | tuple[None, str]:
    """Base64 encode an image file. Returns (base64_data, media_type)."""
    if not path.exists():
        return None, "image/png"
    media_type = _detect_media_type(path)
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8"), media_type


def _image_block(path: Path) -> list[dict]:
    """Build Claude vision image content block from a path."""
    b64, media = _encode_image(path)
    if not b64:
        return []
    return [{"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}}]


# --- Claude vision calls ---


def _call_claude_vision(content: list[dict], max_tokens: int = 800) -> dict:
    """Send content to Claude vision and parse JSON response."""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _call() -> dict:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        text = response.content[0].text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"error": "Could not parse JSON"}

    return retry_api_call(_call, label="Claude vision")


# --- Per-scene comprehensive review ---


def _review_scene_comprehensive(
    scene_frames: list[Path],
    ref_path: Path | None,
    character: Character,
    scene_index: int,
    scene_beat: str,
    scene_emotion: str,
    scene_lighting: str,
    scene_camera: str,
    outfit_description: str,
) -> SceneReview:
    """Review a scene using 3 frames + reference for comprehensive scoring."""
    content: list[dict] = []

    # Add reference portrait
    if ref_path and ref_path.exists():
        content.append({"type": "text", "text": "REFERENCE PORTRAIT (the character should look like this):"})
        content.extend(_image_block(ref_path))

    # Add all 3 scene frames
    labels = ["START of scene", "MIDDLE of scene", "END of scene"]
    for label, frame in zip(labels, scene_frames):
        if frame.exists():
            content.append({"type": "text", "text": f"{label} {scene_index + 1}:"})
            content.extend(_image_block(frame))

    prompt = (
        f"Review scene {scene_index + 1} of a video. Character description: "
        f"{character.gender}, {character.age}, {character.appearance}.\n"
        f"Expected outfit: {outfit_description}\n"
        f"Beat: {scene_beat} | Emotion: {scene_emotion} | Lighting: {scene_lighting} | Camera: {scene_camera}\n\n"
        f"You have the reference portrait and 3 frames (start, middle, end) from this scene.\n"
        f"Check for drift/morphing between start→mid→end frames.\n\n"
        f"Score each dimension 1-10 and respond in this exact JSON format:\n"
        f'{{"face_consistency": 1-10, "outfit_accuracy": 1-10, '
        f'"background_aliveness": 1-10, "body_language": 1-10, '
        f'"lip_sync_quality": 1-10, "overall": 1-10, '
        f'"issues": ["specific issues"], "suggestions": ["specific fixes"]}}\n\n'
        f"Scoring guide:\n"
        f"- face_consistency: Does the face match the reference? Any morphing between frames?\n"
        f"- outfit_accuracy: Is she wearing '{outfit_description}'? Match to reference.\n"
        f"- background_aliveness: Is the background static or moving? Bokeh, movement visible?\n"
        f"- body_language: Is there subtle movement between frames or is she frozen?\n"
        f"- lip_sync_quality: Do mouth shapes look natural? Any uncanny valley?\n"
        f"- overall: Overall scene quality holistically.\n"
        f"Be honest and specific."
    )
    content.append({"type": "text", "text": prompt})

    try:
        result = _call_claude_vision(content, max_tokens=600)
    except Exception:
        return SceneReview(scene_index=scene_index, score=5,
                           issues=["Vision API call failed"], suggestions=["Review manually"])

    return SceneReview(
        scene_index=scene_index,
        score=max(1, min(10, result.get("overall", 5))),
        issues=result.get("issues", []),
        suggestions=result.get("suggestions", []),
        face_consistency=max(1, min(10, result.get("face_consistency", 5))),
        outfit_accuracy=max(1, min(10, result.get("outfit_accuracy", 5))),
        background_aliveness=max(1, min(10, result.get("background_aliveness", 5))),
        body_language=max(1, min(10, result.get("body_language", 5))),
        lip_sync_quality=max(1, min(10, result.get("lip_sync_quality", 5))),
    )


# --- Cross-scene transition check ---


def _review_transition(
    end_frame: Path,
    start_frame: Path,
    from_scene: int,
    to_scene: int,
    character: Character,
) -> TransitionReview:
    """Check visual consistency between the end of one scene and start of the next."""
    content: list[dict] = []

    content.append({"type": "text", "text": f"END of scene {from_scene + 1}:"})
    content.extend(_image_block(end_frame))
    content.append({"type": "text", "text": f"START of scene {to_scene + 1}:"})
    content.extend(_image_block(start_frame))

    prompt = (
        f"These are two consecutive frames from a video — the end of scene {from_scene + 1} "
        f"and the start of scene {to_scene + 1}.\n"
        f"The character should be: {character.gender}, {character.age}, {character.appearance}.\n\n"
        f"Answer in this exact JSON format:\n"
        f'{{"same_person": true/false, "same_outfit": true/false, '
        f'"jarring_jump": true/false, "notes": "brief description of any visual discontinuity"}}\n\n'
        f"Check: Same face? Same outfit? Same location flow? Any jarring visual jump?"
    )
    content.append({"type": "text", "text": prompt})

    try:
        result = _call_claude_vision(content, max_tokens=300)
    except Exception:
        return TransitionReview(from_scene=from_scene, to_scene=to_scene,
                                notes="Transition check failed")

    return TransitionReview(
        from_scene=from_scene,
        to_scene=to_scene,
        same_person=result.get("same_person", True),
        same_outfit=result.get("same_outfit", True),
        jarring_jump=result.get("jarring_jump", False),
        notes=result.get("notes", ""),
    )


# --- Summary generation ---


def _build_summary(scene_reviews: list[SceneReview],
                   transition_reviews: list[TransitionReview]) -> dict:
    """Build a summary report from all review data."""
    if not scene_reviews:
        return {}

    # Find weakest and strongest
    sorted_reviews = sorted(scene_reviews, key=lambda sr: sr.score)
    weakest = sorted_reviews[0]
    strongest = sorted_reviews[-1]

    # Aggregate dimension scores
    dims = ["face_consistency", "outfit_accuracy", "background_aliveness",
            "body_language", "lip_sync_quality"]
    dim_avgs: dict[str, float] = {}
    for dim in dims:
        scores = [getattr(sr, dim) for sr in scene_reviews if getattr(sr, dim) > 0]
        dim_avgs[dim] = round(sum(scores) / len(scores), 1) if scores else 0

    # Collect all issues, count frequency
    all_issues: list[str] = []
    for sr in scene_reviews:
        all_issues.extend(sr.issues)

    # Transition problems
    transition_issues: list[str] = []
    for tr in transition_reviews:
        if not tr.same_person:
            transition_issues.append(f"Scene {tr.from_scene + 1}→{tr.to_scene + 1}: character identity changed")
        if not tr.same_outfit:
            transition_issues.append(f"Scene {tr.from_scene + 1}→{tr.to_scene + 1}: outfit changed")
        if tr.jarring_jump:
            transition_issues.append(f"Scene {tr.from_scene + 1}→{tr.to_scene + 1}: jarring visual jump")

    # Top 3 issues to fix (most impactful)
    top_issues: list[str] = []
    # Prioritize transition breaks
    top_issues.extend(transition_issues[:2])
    # Then lowest-scoring dimensions
    sorted_dims = sorted(dim_avgs.items(), key=lambda x: x[1])
    for dim_name, avg in sorted_dims:
        if avg < 7 and len(top_issues) < 3:
            top_issues.append(f"{dim_name.replace('_', ' ')} averaging {avg}/10 across scenes")

    weakest_issues = "; ".join(weakest.issues[:2]) if weakest.issues else "low overall quality"
    strongest_notes = "; ".join(strongest.issues[:1]) if strongest.issues else "clean render"

    return {
        "weakest_scene": weakest.scene_index + 1,
        "weakest_reason": weakest_issues,
        "weakest_score": weakest.score,
        "strongest_scene": strongest.scene_index + 1,
        "strongest_reason": strongest_notes,
        "strongest_score": strongest.score,
        "top_issues": top_issues[:3],
        "dimension_averages": dim_avgs,
        "transition_issues": transition_issues,
    }


# --- Main review orchestrator ---


def review_rendered_video(script: Script, character: Character, output_dir: Path,
                           conn: sqlite3.Connection | None = None) -> VideoReview:
    """Comprehensive video review: multi-frame, transitions, outfit check, scoring."""
    final_path = output_dir / "final.mp4"
    if not final_path.exists():
        return VideoReview(script_id=script.id, scene_reviews=[], overall_score=0,
                           sync_issues=["No rendered video found"], rerender_needed=[])

    # Step 1: Extract 3 frames per scene
    console.print("  Extracting scene frames (3 per scene)...")
    all_frames = extract_scene_frames(script, output_dir)

    # Find reference portrait
    ref_path = _find_reference(character, output_dir)

    # Determine outfit description
    outfit_desc = script.outfit or character.clothing

    # Step 2: Comprehensive per-scene review
    console.print("  Analyzing scenes with Claude vision...")
    scene_reviews: list[SceneReview] = []
    for i, (scene, frames) in enumerate(zip(script.scenes, all_frames)):
        existing_frames = [f for f in frames if f.exists()]
        if not existing_frames:
            scene_reviews.append(SceneReview(scene_index=i, score=0,
                                             issues=["Frames not extracted"]))
            continue

        sr = _review_scene_comprehensive(
            frames, ref_path, character, i,
            scene.beat, scene.character_emotion, scene.lighting, scene.camera,
            outfit_desc,
        )
        scene_reviews.append(sr)
        console.print(f"    Scene {i + 1} [{scene.beat}]: {sr.score}/10"
                       f" (face:{sr.face_consistency} outfit:{sr.outfit_accuracy}"
                       f" bg:{sr.background_aliveness} body:{sr.body_language}"
                       f" lip:{sr.lip_sync_quality})")

        if conn:
            db.log_render_step(conn, script.id, f"vision_review_scene_{i + 1}",
                               "claude-sonnet", 0, COST_CLAUDE_VISION)

    # Step 3: Cross-scene transition checks
    transition_reviews: list[TransitionReview] = []
    if len(all_frames) > 1:
        console.print("  Checking cross-scene transitions...")
        for i in range(len(all_frames) - 1):
            end_frame = all_frames[i][-1]   # end of scene i
            start_frame = all_frames[i + 1][0]  # start of scene i+1
            if end_frame.exists() and start_frame.exists():
                tr = _review_transition(end_frame, start_frame, i, i + 1, character)
                transition_reviews.append(tr)
                status = "OK" if not tr.jarring_jump else f"[yellow]JUMP[/yellow]"
                if not tr.same_person:
                    status = "[red]IDENTITY CHANGE[/red]"
                elif not tr.same_outfit:
                    status = "[yellow]OUTFIT CHANGE[/yellow]"
                console.print(f"    Scene {i + 1}→{i + 2}: {status}"
                               + (f" — {tr.notes}" if tr.notes else ""))

                if conn:
                    db.log_render_step(conn, script.id, f"vision_transition_{i + 1}_{i + 2}",
                                       "claude-sonnet", 0, COST_CLAUDE_VISION)

    # Step 4: Calculate overall score and summary
    overall = sum(sr.score for sr in scene_reviews) / len(scene_reviews) if scene_reviews else 0
    rerender = auto_flag_rerender_from_reviews(scene_reviews)
    summary = _build_summary(scene_reviews, transition_reviews)

    # Step 5: Audio-visual sync check
    voiceover_path = output_dir / "voiceover.mp3"
    sync_issues: list[str] = []
    if voiceover_path.exists():
        sync_issues = review_audio_visual_sync(script, voiceover_path)

    review = VideoReview(
        script_id=script.id,
        scene_reviews=scene_reviews,
        overall_score=round(overall, 1),
        sync_issues=sync_issues,
        rerender_needed=rerender,
        transition_reviews=transition_reviews,
        summary=summary,
    )

    if conn:
        db.save_video_review(conn, review)

    # Step 6: Auto-learn — store scores in scene feedback
    if conn:
        _auto_learn_from_review(conn, script, scene_reviews)

    return review


def _find_reference(character: Character, output_dir: Path) -> Path | None:
    """Find the best reference portrait — POV reference first, then character ref."""
    pov_ref = output_dir / "images" / "pov_reference.png"
    if pov_ref.exists():
        return pov_ref
    if character.reference_image_path:
        p = Path(character.reference_image_path)
        if p.exists():
            return p
    return None


def _auto_learn_from_review(conn: sqlite3.Connection, script: Script,
                            scene_reviews: list[SceneReview]) -> None:
    """Store vision review scores as scene feedback for auto-optimization learning."""
    for sr in scene_reviews:
        if sr.score == 0:
            continue
        # Map vision dimensions to scene_feedback columns:
        # visual_quality = average of face_consistency, outfit_accuracy, background_aliveness
        # emotional_impact = body_language (movement = emotion conveyed)
        # pacing = overall score (proxy)
        # lip_sync = lip_sync_quality
        visual_parts = [s for s in [sr.face_consistency, sr.outfit_accuracy, sr.background_aliveness] if s > 0]
        visual_q = round(sum(visual_parts) / len(visual_parts)) if visual_parts else sr.score
        # Scale 1-10 to 1-5 for scene_feedback
        visual_q_5 = max(1, min(5, round(visual_q / 2)))
        body_5 = max(1, min(5, round(sr.body_language / 2))) if sr.body_language > 0 else None
        overall_5 = max(1, min(5, round(sr.score / 2)))
        lip_5 = max(1, min(5, round(sr.lip_sync_quality / 2))) if sr.lip_sync_quality > 0 else None

        notes_parts = []
        if sr.outfit_accuracy > 0:
            notes_parts.append(f"outfit:{sr.outfit_accuracy}/10")
        if sr.body_language > 0:
            notes_parts.append(f"body_lang:{sr.body_language}/10")
        if sr.background_aliveness > 0:
            notes_parts.append(f"bg_alive:{sr.background_aliveness}/10")
        notes = ", ".join(notes_parts)

        db.save_scene_feedback(
            conn, script.id, sr.scene_index,
            visual_quality=visual_q_5,
            emotional_impact=body_5 or overall_5,
            pacing=overall_5,
            lip_sync=lip_5,
            notes=f"[auto-review] {notes}",
        )


# --- Audio-visual sync ---


def review_audio_visual_sync(script: Script, voiceover_path: Path) -> list[str]:
    """Check if emotional peaks align with scene transitions."""
    issues: list[str] = []
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", compute_type="int8")
        segments, _ = model.transcribe(str(voiceover_path), word_timestamps=True)

        emotional_keywords = {"hurt", "hurts", "ache", "pain", "withdrawal", "addiction",
                              "dopamine", "cocaine", "brain", "chemistry", "changes",
                              "stop", "can't", "weak", "broken"}
        keyword_times: list[tuple[str, float]] = []
        for seg in segments:
            if seg.words:
                for w in seg.words:
                    if w.word.strip().lower().rstrip(".,!?") in emotional_keywords:
                        keyword_times.append((w.word.strip(), w.start))

        transitions: list[float] = []
        cumulative = 0.0
        for scene in script.scenes:
            cumulative += scene.duration_seconds
            transitions.append(cumulative)

        for word, time in keyword_times:
            for t_idx, t_time in enumerate(transitions[:-1]):
                if abs(time - t_time) < 0.5:
                    issues.append(
                        f"Word '{word}' at {time:.1f}s lands right at scene {t_idx + 1}->{t_idx + 2} "
                        f"transition ({t_time:.1f}s) — may be cut off"
                    )
    except Exception:
        pass

    return issues


# --- Re-render flagging ---


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


# --- Pretty print ---


def print_review(review: VideoReview) -> None:
    """Pretty-print a comprehensive video review."""
    color = "green" if review.overall_score >= 7 else "yellow" if review.overall_score >= 5 else "red"
    console.print(f"\n[bold]Video Review[/bold] — Overall: [{color}]{review.overall_score}/10[/{color}]")

    # Scene scores table with dimension breakdown
    table = Table(title="Scene Scores")
    table.add_column("#", style="dim")
    table.add_column("Overall")
    table.add_column("Face")
    table.add_column("Outfit")
    table.add_column("BG")
    table.add_column("Body")
    table.add_column("Lip")
    table.add_column("Issues")
    for sr in review.scene_reviews:
        sc = "green" if sr.score >= 7 else "yellow" if sr.score >= 5 else "red"
        issues_str = "; ".join(sr.issues[:2]) if sr.issues else "—"
        table.add_row(
            str(sr.scene_index + 1),
            f"[{sc}]{sr.score}/10[/{sc}]",
            f"{sr.face_consistency}/10" if sr.face_consistency else "—",
            f"{sr.outfit_accuracy}/10" if sr.outfit_accuracy else "—",
            f"{sr.background_aliveness}/10" if sr.background_aliveness else "—",
            f"{sr.body_language}/10" if sr.body_language else "—",
            f"{sr.lip_sync_quality}/10" if sr.lip_sync_quality else "—",
            issues_str[:50],
        )
    console.print(table)

    # Transition results
    if review.transition_reviews:
        console.print("\n[bold cyan]Cross-Scene Transitions:[/bold cyan]")
        for tr in review.transition_reviews:
            issues = []
            if not tr.same_person:
                issues.append("[red]identity change[/red]")
            if not tr.same_outfit:
                issues.append("[yellow]outfit change[/yellow]")
            if tr.jarring_jump:
                issues.append("[yellow]jarring jump[/yellow]")
            status = ", ".join(issues) if issues else "[green]smooth[/green]"
            notes = f" — {tr.notes}" if tr.notes else ""
            console.print(f"  Scene {tr.from_scene + 1}→{tr.to_scene + 1}: {status}{notes}")

    # Sync issues
    if review.sync_issues:
        console.print("\n[bold yellow]Sync Issues:[/bold yellow]")
        for issue in review.sync_issues:
            console.print(f"  - {issue}")

    # Summary report
    if review.summary:
        s = review.summary
        console.print("\n[bold]Summary Report:[/bold]")
        console.print(f"  Strongest scene: #{s.get('strongest_scene', '?')}"
                       f" ({s.get('strongest_score', '?')}/10) — {s.get('strongest_reason', '')}")
        console.print(f"  Weakest scene:   #{s.get('weakest_scene', '?')}"
                       f" ({s.get('weakest_score', '?')}/10) — {s.get('weakest_reason', '')}")

        if s.get("dimension_averages"):
            dims = s["dimension_averages"]
            console.print(f"\n  [bold]Dimension Averages:[/bold]")
            for dim, avg in dims.items():
                dc = "green" if avg >= 7 else "yellow" if avg >= 5 else "red"
                console.print(f"    {dim.replace('_', ' '):25s} [{dc}]{avg}/10[/{dc}]")

        if s.get("top_issues"):
            console.print(f"\n  [bold]Top Issues to Fix:[/bold]")
            for i, issue in enumerate(s["top_issues"], 1):
                console.print(f"    {i}. {issue}")

    # Re-render flags
    if review.rerender_needed:
        scenes_str = ", ".join(str(i + 1) for i in review.rerender_needed)
        console.print(f"\n[bold red]Scenes flagged for re-render:[/bold red] {scenes_str}")
    else:
        console.print("\n[green]No re-render needed.[/green]")
    console.print()
