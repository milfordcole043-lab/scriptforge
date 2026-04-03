from __future__ import annotations

import os
import sqlite3
import subprocess
import urllib.request
from pathlib import Path

from rich.console import Console
from rich.table import Table

from scriptforge import db
from scriptforge.config import ELEVENLABS_API_KEY, FAL_KEY, OUTPUT_DIR
from scriptforge.engine import build_video_prompt
from scriptforge.models import Script
from scriptforge.researcher import grade_prompt

console = Console()


def render_script(conn: sqlite3.Connection, script_id: int, *, dry_run: bool = False) -> Path | None:
    """Orchestrate the full render pipeline for a script."""
    script = db.get_script(conn, script_id)
    if not script:
        console.print(f"[red]Script #{script_id} not found.[/red]")
        return None

    output_dir = OUTPUT_DIR / str(script_id)

    if dry_run:
        _show_dry_run(script, output_dir)
        return None

    from scriptforge.config import check_keys
    missing = check_keys()
    if missing:
        console.print(f"[red]Missing API keys: {', '.join(missing)}[/red]")
        console.print("[dim]Add them to .env and try again.[/dim]")
        return None

    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    (output_dir / "clips").mkdir(parents=True, exist_ok=True)

    console.print("\n[bold cyan]Step 1/5:[/bold cyan] Generating images...")
    images = generate_images(script, output_dir)

    console.print("[bold cyan]Step 2/5:[/bold cyan] Generating video clips...")
    clips = generate_clips(script, images, output_dir, conn=conn)

    console.print("[bold cyan]Step 3/5:[/bold cyan] Burning captions...")
    captioned = burn_captions(script, clips, output_dir)

    console.print("[bold cyan]Step 4/5:[/bold cyan] Generating voiceover...")
    voiceover = generate_voiceover(script, output_dir)

    console.print("[bold cyan]Step 5/5:[/bold cyan] Assembling final video...")
    final = assemble_video(captioned, voiceover, output_dir)

    console.print(f"\n[bold green]Done![/bold green] Video saved to: {final}")
    return final


def generate_images(script: Script, output_dir: Path) -> list[Path]:
    """Generate a still image for each scene using fal.ai Flux Pro."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    images: list[Path] = []

    for i, scene in enumerate(script.scenes):
        console.print(f"  Scene {i + 1}/{len(script.scenes)} [{scene.beat}]: generating image...")
        result = fal_client.subscribe(
            "fal-ai/flux-pro/v1.1",
            arguments={
                "prompt": scene.visual,
                "image_size": "portrait_16_9",
                "num_images": 1,
            },
        )
        image_url = result["images"][0]["url"]
        image_path = output_dir / "images" / f"scene_{i + 1:02d}.png"
        urllib.request.urlretrieve(image_url, str(image_path))
        console.print(f"    Saved: {image_path.name}")
        images.append(image_path)

    return images


def generate_clips(script: Script, images: list[Path], output_dir: Path,
                    conn: sqlite3.Connection | None = None) -> list[Path]:
    """Animate each scene image into a video clip using fal.ai Kling v3 Pro."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    clips: list[Path] = []

    # Load prompt rules for grading
    prompt_rules = db.get_prompt_rules(conn) if conn else []

    for i, (scene, image_path) in enumerate(zip(script.scenes, images)):
        # Kling v3 Pro supports 3-15s
        duration = str(max(3, min(15, scene.duration_seconds)))
        video_prompt = build_video_prompt(scene)

        # Grade and auto-enhance the prompt
        if prompt_rules:
            score, missing, enhanced = grade_prompt(video_prompt, prompt_rules)
            if score < 70:
                console.print(f"  Scene {i + 1} prompt score: {score}/100 — auto-enhancing...")
                video_prompt = enhanced
            else:
                console.print(f"  Scene {i + 1} prompt score: {score}/100")

        console.print(f"  Scene {i + 1}/{len(script.scenes)} [{scene.beat}]: generating clip ({duration}s)...")

        image_url = fal_client.upload_file(str(image_path))

        result = fal_client.subscribe(
            "fal-ai/kling-video/v3/pro/image-to-video",
            arguments={
                "start_image_url": image_url,
                "prompt": video_prompt,
                "duration": duration,
                "generate_audio": False,
            },
        )
        video_url = result["video"]["url"]
        clip_path = output_dir / "clips" / f"scene_{i + 1:02d}.mp4"
        urllib.request.urlretrieve(video_url, str(clip_path))
        console.print(f"    Saved: {clip_path.name} ({duration}s)")
        clips.append(clip_path)

    return clips


def burn_captions(script: Script, clips: list[Path], output_dir: Path) -> list[Path]:
    """Burn bold caption text onto each clip using FFmpeg drawtext."""
    captioned: list[Path] = []

    for i, (scene, clip) in enumerate(zip(script.scenes, clips)):
        caption_path = output_dir / "clips" / f"scene_{i + 1:02d}_captioned.mp4"
        caption_text = scene.caption.replace("'", "\\'").replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y", "-i", str(clip),
            "-vf", (
                f"drawtext=text='{caption_text}'"
                f":fontsize=48:fontcolor=white:borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=h-h/5"
                f":fontfile=C\\\\:/Windows/Fonts/arialbd.ttf"
            ),
            "-c:a", "copy",
            str(caption_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"  [yellow]Caption burn failed for scene {i + 1}, using original clip[/yellow]")
            captioned.append(clip)
        else:
            console.print(f"    Captioned: {caption_path.name}")
            captioned.append(caption_path)

    return captioned


def generate_voiceover(script: Script, output_dir: Path) -> Path:
    """Generate voiceover audio using ElevenLabs."""
    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    audio_generator = client.text_to_speech.convert(
        text=script.full_script,
        voice_id="nPczCjzI2devNBz1zQrb",  # Brian -- warm, natural narrator
        model_id="eleven_v3",
        output_format="mp3_44100_128",
    )

    voiceover_path = output_dir / "voiceover.mp3"
    with open(voiceover_path, "wb") as f:
        for chunk in audio_generator:
            f.write(chunk)

    console.print(f"    Saved: {voiceover_path.name}")
    return voiceover_path


def assemble_video(clips: list[Path], voiceover: Path, output_dir: Path) -> Path:
    """Concatenate video clips and overlay voiceover using FFmpeg."""
    concat_path = output_dir / "concat.txt"
    with open(concat_path, "w") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    final_path = output_dir / "final.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-i", str(voiceover),
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        str(final_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]FFmpeg error:[/red]\n{result.stderr}")
        raise RuntimeError("FFmpeg assembly failed")

    concat_path.unlink()
    console.print(f"    Saved: {final_path.name}")
    return final_path


def _show_dry_run(script: Script, output_dir: Path) -> None:
    """Show what the pipeline would do without calling any APIs."""
    console.print(f"\n[bold yellow]DRY RUN[/bold yellow] -- Script #{script.id}: {script.topic}\n")

    console.print(f"  Output directory: {output_dir}")
    console.print(f"  Total scenes: {len(script.scenes)}")
    total_duration = sum(s.duration_seconds for s in script.scenes)
    console.print(f"  Total scene duration: {total_duration}s")
    console.print(f"  Voiceover words: {script.word_count}")
    console.print()

    table = Table(title="Render Plan")
    table.add_column("#", style="dim")
    table.add_column("Beat")
    table.add_column("Caption")
    table.add_column("Visual Prompt")
    table.add_column("Camera")
    table.add_column("Duration")
    table.add_column("Clip Dur")

    for i, scene in enumerate(script.scenes):
        clip_dur = f"{max(3, min(15, scene.duration_seconds))}s"
        table.add_row(
            str(i + 1),
            scene.beat,
            scene.caption,
            scene.visual[:40] + ("..." if len(scene.visual) > 40 else ""),
            scene.camera,
            f"{scene.duration_seconds}s",
            clip_dur,
        )

    console.print(table)

    console.print(f"\n  [bold]Step 1:[/bold] Generate {len(script.scenes)} images via fal.ai Flux Pro (9:16)")
    console.print(f"  [bold]Step 2:[/bold] Animate {len(script.scenes)} clips via Kling v3 Pro")
    console.print(f"  [bold]Step 3:[/bold] Burn captions onto clips (FFmpeg drawtext)")
    console.print(f"  [bold]Step 4:[/bold] Generate voiceover via ElevenLabs (Brian, eleven_v3)")
    console.print(f"  [bold]Step 5:[/bold] Assemble with FFmpeg -> final.mp4")
    console.print(f"\n  [dim]Run without --dry-run to execute.[/dim]\n")
