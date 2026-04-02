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
from scriptforge.models import Script

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

    # Check API keys before starting
    from scriptforge.config import check_keys
    missing = check_keys()
    if missing:
        console.print(f"[red]Missing API keys: {', '.join(missing)}[/red]")
        console.print("[dim]Add them to .env and try again.[/dim]")
        return None

    # Create output directories
    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    (output_dir / "clips").mkdir(parents=True, exist_ok=True)

    # Step 1: Generate images
    console.print("\n[bold cyan]Step 1/4:[/bold cyan] Generating images...")
    images = generate_images(script, output_dir)

    # Step 2: Generate video clips
    console.print("[bold cyan]Step 2/4:[/bold cyan] Generating video clips...")
    clips = generate_clips(script, images, output_dir)

    # Step 3: Generate voiceover
    console.print("[bold cyan]Step 3/4:[/bold cyan] Generating voiceover...")
    voiceover = generate_voiceover(script, output_dir)

    # Step 4: Assemble final video
    console.print("[bold cyan]Step 4/4:[/bold cyan] Assembling final video...")
    final = assemble_video(clips, voiceover, output_dir)

    console.print(f"\n[bold green]Done![/bold green] Video saved to: {final}")
    return final


def generate_images(script: Script, output_dir: Path) -> list[Path]:
    """Generate a still image for each scene using fal.ai Flux Pro."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    images: list[Path] = []

    for i, scene in enumerate(script.scenes):
        console.print(f"  Scene {i + 1}/{len(script.scenes)}: generating image...")
        result = fal_client.subscribe(
            "fal-ai/flux-pro/v1.1",
            arguments={
                "prompt": scene.visual,
                "image_size": "landscape_16_9",
                "num_images": 1,
            },
        )
        image_url = result["images"][0]["url"]
        image_path = output_dir / "images" / f"scene_{i + 1:02d}.png"
        urllib.request.urlretrieve(image_url, str(image_path))
        console.print(f"    Saved: {image_path.name}")
        images.append(image_path)

    return images


def generate_clips(script: Script, images: list[Path], output_dir: Path) -> list[Path]:
    """Animate each scene image into a video clip using fal.ai Kling."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    clips: list[Path] = []

    for i, (scene, image_path) in enumerate(zip(script.scenes, images)):
        console.print(f"  Scene {i + 1}/{len(script.scenes)}: generating clip ({scene.duration_seconds}s)...")

        # Kling supports 5s or 10s — pick closest
        kling_duration = "10" if scene.duration_seconds > 7 else "5"

        # Upload image to get a URL for Kling
        image_url = fal_client.upload_file(str(image_path))

        result = fal_client.subscribe(
            "fal-ai/kling-video/v2/master/image-to-video",
            arguments={
                "image_url": image_url,
                "prompt": scene.visual,
                "duration": kling_duration,
            },
        )
        video_url = result["video"]["url"]
        clip_path = output_dir / "clips" / f"scene_{i + 1:02d}.mp4"
        urllib.request.urlretrieve(video_url, str(clip_path))
        console.print(f"    Saved: {clip_path.name} ({kling_duration}s)")
        clips.append(clip_path)

    return clips


def generate_voiceover(script: Script, output_dir: Path) -> Path:
    """Generate voiceover audio using ElevenLabs."""
    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    audio_generator = client.text_to_speech.convert(
        text=script.full_script,
        voice_id="JBFqnCBsd6RMkjVDRZzb",  # George — deep, calm narrator
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
    # Write concat list
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

    # Clean up concat file
    concat_path.unlink()
    console.print(f"    Saved: {final_path.name}")
    return final_path


def _show_dry_run(script: Script, output_dir: Path) -> None:
    """Show what the pipeline would do without calling any APIs."""
    console.print(f"\n[bold yellow]DRY RUN[/bold yellow] — Script #{script.id}: {script.topic}\n")

    console.print(f"  Output directory: {output_dir}")
    console.print(f"  Total scenes: {len(script.scenes)}")
    total_duration = sum(s.duration_seconds for s in script.scenes)
    console.print(f"  Total scene duration: {total_duration}s")
    console.print(f"  Voiceover words: {script.word_count}")
    console.print()

    table = Table(title="Render Plan")
    table.add_column("#", style="dim")
    table.add_column("Visual Prompt")
    table.add_column("Duration")
    table.add_column("Kling Duration")
    table.add_column("Image Output")
    table.add_column("Clip Output")

    for i, scene in enumerate(script.scenes):
        kling_dur = "10s" if scene.duration_seconds > 7 else "5s"
        table.add_row(
            str(i + 1),
            scene.visual[:60] + ("..." if len(scene.visual) > 60 else ""),
            f"{scene.duration_seconds}s",
            kling_dur,
            f"scene_{i + 1:02d}.png",
            f"scene_{i + 1:02d}.mp4",
        )

    console.print(table)

    console.print(f"\n  [bold]Step 1:[/bold] Generate {len(script.scenes)} images via fal.ai Flux Pro")
    console.print(f"  [bold]Step 2:[/bold] Animate {len(script.scenes)} clips via fal.ai Kling")
    console.print(f"  [bold]Step 3:[/bold] Generate voiceover via ElevenLabs (eleven_v3)")
    console.print(f"  [bold]Step 4:[/bold] Assemble with FFmpeg -> final.mp4")
    console.print(f"\n  [dim]Run without --dry-run to execute.[/dim]\n")
