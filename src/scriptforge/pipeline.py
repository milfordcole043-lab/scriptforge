from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

from scriptforge import db
from scriptforge.config import (
    ELEVENLABS_API_KEY, FAL_KEY, OUTPUT_DIR,
    escape_ffmpeg_text, retry_api_call, safe_download,
)
from scriptforge.engine import build_video_prompt
from scriptforge.models import Character, Script
from scriptforge.researcher import grade_prompt

console = Console()

KLING_NEGATIVE = "blur, flickering, morphing faces, distorted hands, text, watermark, low quality, jittery motion"

# Cost per second estimates
COST_FLUX_PRO = 0.04  # per image
COST_KLING_V3 = 0.112  # per second, no audio
COST_ELEVENLABS = 0.03  # per second estimate
COST_FABRIC = 0.15  # per second at 720p


def render_script(conn: sqlite3.Connection, script_id: int, *, dry_run: bool = False) -> Path | None:
    """Route to the correct pipeline based on script mode."""
    script = db.get_script(conn, script_id)
    if not script:
        console.print(f"[red]Script #{script_id} not found.[/red]")
        return None

    if script.mode == "pov":
        from scriptforge.pov_pipeline import render_pov
        return render_pov(conn, script_id, dry_run=dry_run)

    return _render_narrator(conn, script, dry_run=dry_run)


def _render_narrator(conn: sqlite3.Connection, script: Script, *, dry_run: bool = False) -> Path | None:
    """Orchestrate the narrator render pipeline."""
    character = None
    if script.character_id:
        character = db.get_character(conn, script.character_id)
    if not character:
        console.print("[red]Script has no character. Create one with 'scriptforge character' first.[/red]")
        return None

    output_dir = OUTPUT_DIR / str(script.id)

    if dry_run:
        _show_dry_run(script, character, output_dir)
        return None

    from scriptforge.config import check_keys
    missing = check_keys()
    if missing:
        console.print(f"[red]Missing API keys: {', '.join(missing)}[/red]")
        return None

    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    (output_dir / "clips").mkdir(parents=True, exist_ok=True)

    # Step 0: Character reference portrait (cached)
    if not character.reference_image_path or not Path(character.reference_image_path).exists():
        console.print("\n[bold cyan]Step 0/6:[/bold cyan] Generating character reference portrait...")
        ref_path = generate_character_portrait(character, output_dir, conn, script.id)
        db.update_character_image(conn, character.id, str(ref_path))
        character.reference_image_path = str(ref_path)
    else:
        console.print("\n[bold cyan]Step 0/6:[/bold cyan] Character portrait cached, skipping.")

    console.print("\n[bold cyan]Step 1/6:[/bold cyan] Generating scene images...")
    images = generate_images(script, character, output_dir, conn)

    console.print("[bold cyan]Step 2/6:[/bold cyan] Generating video clips...")
    clips = generate_clips(script, character, images, output_dir, conn)

    console.print("[bold cyan]Step 3/6:[/bold cyan] Burning captions...")
    captioned = burn_captions(script, clips, output_dir)

    console.print("[bold cyan]Step 4/6:[/bold cyan] Generating voiceover...")
    voiceover = generate_voiceover(script, output_dir, conn)

    console.print("[bold cyan]Step 5/6:[/bold cyan] Assembling final video...")
    final = assemble_video(captioned, voiceover, output_dir)

    total_cost = db.get_render_cost(conn, script.id)
    console.print(f"\n[bold green]Done![/bold green] Video saved to: {final}")
    console.print(f"[bold]Total estimated cost: ${total_cost:.2f}[/bold]")
    return final


def generate_character_portrait(character: Character, output_dir: Path,
                                 conn: sqlite3.Connection | None = None,
                                 script_id: int = 0) -> Path:
    """Generate a neutral reference portrait for character consistency."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    ref_path = output_dir / "images" / "character_ref.png"

    # Resume: skip if exists
    if ref_path.exists():
        console.print(f"    Cached: {ref_path.name}")
        return ref_path

    ref_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = (
        f"Portrait of a {character.gender} in {character.age} with {character.appearance}, "
        f"wearing {character.clothing}. Neutral expression, soft even lighting, "
        f"plain background, cinematic portrait photography. Consistent lighting throughout."
    )

    result = retry_api_call(
        fal_client.subscribe, "fal-ai/flux-pro/v1.1",
        arguments={"prompt": prompt, "image_size": "portrait_16_9", "num_images": 1},
        label="Flux Pro (character portrait)",
    )
    safe_download(result["images"][0]["url"], str(ref_path), label="character portrait")
    console.print(f"    Saved: {ref_path.name}")

    if conn and script_id:
        db.log_render_step(conn, script_id, "character_portrait", "flux-pro", 0, COST_FLUX_PRO)

    return ref_path


def generate_images(script: Script, character: Character, output_dir: Path,
                     conn: sqlite3.Connection | None = None) -> list[Path]:
    """Generate a still image for each scene using fal.ai Flux Pro."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    images: list[Path] = []

    for i, scene in enumerate(script.scenes):
        image_path = output_dir / "images" / f"scene_{i + 1:02d}.png"

        # Resume: skip if exists
        if image_path.exists():
            console.print(f"  Scene {i + 1}/{len(script.scenes)} [{scene.beat}]: cached, skipping.")
            images.append(image_path)
            continue

        console.print(f"  Scene {i + 1}/{len(script.scenes)} [{scene.beat}]: generating image...")
        prompt = build_video_prompt(scene, character)

        result = retry_api_call(
            fal_client.subscribe, "fal-ai/flux-pro/v1.1",
            arguments={"prompt": prompt, "image_size": "portrait_16_9", "num_images": 1},
            label=f"Flux Pro (scene {i + 1})",
        )
        safe_download(result["images"][0]["url"], str(image_path), label=f"scene {i + 1} image")
        console.print(f"    Saved: {image_path.name}")
        images.append(image_path)

        if conn:
            db.log_render_step(conn, script.id, f"image_scene_{i + 1}", "flux-pro", 0, COST_FLUX_PRO)

    return images


def generate_clips(script: Script, character: Character, images: list[Path],
                    output_dir: Path, conn: sqlite3.Connection | None = None) -> list[Path]:
    """Animate each scene image into a video clip using fal.ai Kling v3 Pro."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    clips: list[Path] = []
    prompt_rules = db.get_prompt_rules(conn) if conn else []

    for i, (scene, image_path) in enumerate(zip(script.scenes, images)):
        clip_path = output_dir / "clips" / f"scene_{i + 1:02d}.mp4"

        # Resume: skip if exists
        if clip_path.exists():
            console.print(f"  Scene {i + 1}/{len(script.scenes)} [{scene.beat}]: cached, skipping.")
            clips.append(clip_path)
            continue

        duration = str(max(3, min(15, scene.duration_seconds)))
        video_prompt = build_video_prompt(scene, character)

        if prompt_rules:
            score, missing, enhanced = grade_prompt(video_prompt, prompt_rules)
            if score < 70:
                console.print(f"  Scene {i + 1} prompt score: {score}/100 -- auto-enhancing...")
                video_prompt = enhanced
            else:
                console.print(f"  Scene {i + 1} prompt score: {score}/100")

        console.print(f"  Scene {i + 1}/{len(script.scenes)} [{scene.beat}]: generating clip ({duration}s)...")

        image_url = retry_api_call(
            fal_client.upload_file, str(image_path),
            label=f"upload scene {i + 1} image",
        )

        result = retry_api_call(
            fal_client.subscribe, "fal-ai/kling-video/v3/pro/image-to-video",
            arguments={
                "start_image_url": image_url,
                "prompt": video_prompt,
                "negative_prompt": KLING_NEGATIVE,
                "duration": duration,
                "generate_audio": False,
            },
            label=f"Kling v3 Pro (scene {i + 1})",
        )
        safe_download(result["video"]["url"], str(clip_path), label=f"scene {i + 1} clip")
        console.print(f"    Saved: {clip_path.name} ({duration}s)")
        clips.append(clip_path)

        if conn:
            dur_s = float(duration)
            db.log_render_step(conn, script.id, f"clip_scene_{i + 1}", "kling-v3-pro",
                               dur_s, dur_s * COST_KLING_V3)

    return clips


def burn_captions(script: Script, clips: list[Path], output_dir: Path) -> list[Path]:
    """Burn bold caption text onto each clip using FFmpeg drawtext."""
    captioned: list[Path] = []

    for i, (scene, clip) in enumerate(zip(script.scenes, clips)):
        caption_path = output_dir / "clips" / f"scene_{i + 1:02d}_captioned.mp4"

        # Resume: skip if exists
        if caption_path.exists():
            console.print(f"    Scene {i + 1}: captioned file cached, skipping.")
            captioned.append(caption_path)
            continue

        caption_text = escape_ffmpeg_text(scene.caption)

        cmd = [
            "ffmpeg", "-y", "-i", str(clip),
            "-vf", (
                f"drawtext=text='{caption_text}'"
                f":fontsize=48:fontcolor=white:borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=h-h/5"
            ),
            "-c:a", "copy",
            str(caption_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            console.print(f"  [yellow]Caption burn failed for scene {i + 1}, using original clip[/yellow]")
            captioned.append(clip)
        else:
            console.print(f"    Captioned: {caption_path.name}")
            captioned.append(caption_path)

    return captioned


def generate_voiceover(script: Script, output_dir: Path,
                        conn: sqlite3.Connection | None = None) -> Path:
    """Generate voiceover audio using ElevenLabs."""
    voiceover_path = output_dir / "voiceover.mp3"

    # Resume: skip if exists
    if voiceover_path.exists():
        console.print(f"    Cached: {voiceover_path.name}")
        return voiceover_path

    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    def _generate() -> bytes:
        gen = client.text_to_speech.convert(
            text=script.full_script,
            voice_id="nPczCjzI2devNBz1zQrb",  # Brian
            model_id="eleven_v3",
            output_format="mp3_44100_128",
        )
        return b"".join(gen)

    audio_data = retry_api_call(_generate, label="ElevenLabs voiceover")
    with open(voiceover_path, "wb") as f:
        f.write(audio_data)

    console.print(f"    Saved: {voiceover_path.name}")

    if conn:
        dur_s = script.total_duration
        db.log_render_step(conn, script.id, "voiceover", "elevenlabs-v3", dur_s, dur_s * COST_ELEVENLABS)

    return voiceover_path


def assemble_video(clips: list[Path], voiceover: Path, output_dir: Path) -> Path:
    """Concatenate video clips and overlay voiceover using FFmpeg."""
    final_path = output_dir / "final.mp4"

    concat_path = output_dir / "concat.txt"
    with open(concat_path, "w") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-i", str(voiceover),
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        str(final_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        console.print(f"[red]FFmpeg error:[/red]\n{result.stderr}")
        raise RuntimeError("FFmpeg assembly failed")

    concat_path.unlink(missing_ok=True)
    console.print(f"    Saved: {final_path.name}")
    return final_path


def _show_dry_run(script: Script, character: Character, output_dir: Path) -> None:
    """Show what the pipeline would do without calling any APIs."""
    console.print(f"\n[bold yellow]DRY RUN (NARRATOR MODE)[/bold yellow] -- Script #{script.id}: {script.topic}\n")

    console.print(f"  Character: [bold]{character.name}[/bold] ({character.age}, {character.gender})")
    console.print(f"  Appearance: {character.appearance}")
    console.print(f"  Clothing: {character.clothing}")
    console.print(f"  Output directory: {output_dir}")
    console.print(f"  Total scenes: {len(script.scenes)}")
    total_duration = sum(s.duration_seconds for s in script.scenes)
    console.print(f"  Total scene duration: {total_duration}s")
    console.print(f"  Voiceover words: {script.word_count}")

    # Cost estimate
    image_cost = len(script.scenes) * COST_FLUX_PRO
    ref_cost = COST_FLUX_PRO if not character.reference_image_path else 0
    clip_cost = total_duration * COST_KLING_V3
    vo_cost = total_duration * COST_ELEVENLABS
    total_cost = image_cost + ref_cost + clip_cost + vo_cost
    console.print(f"  [bold]Estimated cost: ~${total_cost:.2f}[/bold]")
    console.print(f"    Images: ${image_cost:.2f} | Clips: ${clip_cost:.2f} | Voiceover: ${vo_cost:.2f}")
    console.print()

    table = Table(title="Render Plan")
    table.add_column("#", style="dim")
    table.add_column("Beat")
    table.add_column("Caption")
    table.add_column("Action")
    table.add_column("Location")
    table.add_column("Camera")
    table.add_column("Dur")

    for i, scene in enumerate(script.scenes):
        clip_dur = f"{max(3, min(15, scene.duration_seconds))}s"
        table.add_row(
            str(i + 1),
            scene.beat,
            scene.caption,
            scene.character_action[:40] + ("..." if len(scene.character_action) > 40 else ""),
            scene.location[:30] + ("..." if len(scene.location) > 30 else ""),
            scene.camera,
            clip_dur,
        )

    console.print(table)

    has_ref = "cached" if character.reference_image_path else "generate new"
    console.print(f"\n  [bold]Step 0:[/bold] Character reference portrait ({has_ref})")
    console.print(f"  [bold]Step 1:[/bold] Generate {len(script.scenes)} scene images via Flux Pro (9:16)")
    console.print(f"  [bold]Step 2:[/bold] Animate {len(script.scenes)} clips via Kling v3 Pro (+ negative prompt)")
    console.print(f"  [bold]Step 3:[/bold] Burn captions onto clips (FFmpeg drawtext)")
    console.print(f"  [bold]Step 4:[/bold] Generate voiceover via ElevenLabs (Brian, eleven_v3)")
    console.print(f"  [bold]Step 5:[/bold] Assemble with FFmpeg -> final.mp4")
    console.print(f"\n  [dim]Run without --dry-run to execute.[/dim]\n")
