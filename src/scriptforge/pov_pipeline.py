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
from scriptforge.engine import build_pov_reference_prompt, build_pov_video_prompt
from scriptforge.models import Character, Script

console = Console()

# Young female voice for POV confessional — Lily (ElevenLabs)
POV_VOICE_ID = "pFZP5JQG7iQjIQuC4Bku"


def render_pov(conn: sqlite3.Connection, script_id: int, *, dry_run: bool = False) -> Path | None:
    """Orchestrate the POV lip-sync render pipeline."""
    script = db.get_script(conn, script_id)
    if not script:
        console.print(f"[red]Script #{script_id} not found.[/red]")
        return None

    character = None
    if script.character_id:
        character = db.get_character(conn, script.character_id)
    if not character:
        console.print("[red]Script has no character. Create one with 'scriptforge character' first.[/red]")
        return None

    output_dir = OUTPUT_DIR / str(script_id)

    if dry_run:
        _show_pov_dry_run(script, character, output_dir)
        return None

    from scriptforge.config import check_keys
    missing = check_keys()
    if missing:
        console.print(f"[red]Missing API keys: {', '.join(missing)}[/red]")
        return None

    (output_dir / "chunks").mkdir(parents=True, exist_ok=True)
    (output_dir / "clips").mkdir(parents=True, exist_ok=True)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)

    # Step 1: Generate full voiceover
    console.print("\n[bold cyan]Step 1/6:[/bold cyan] Generating voiceover...")
    voiceover = generate_pov_voiceover(script, output_dir)

    # Step 2: Split audio into chunks
    console.print("[bold cyan]Step 2/6:[/bold cyan] Splitting audio into scene chunks...")
    chunks = split_audio_by_scenes(voiceover, script, output_dir)

    # Step 3: Generate POV reference portrait
    console.print("[bold cyan]Step 3/6:[/bold cyan] Generating POV reference portrait...")
    first_lighting = script.scenes[0].lighting if script.scenes else ""
    ref_image = generate_pov_reference(character, first_lighting, output_dir)

    # Step 4: Generate lip-sync clips
    console.print("[bold cyan]Step 4/6:[/bold cyan] Generating lip-sync video clips...")
    clips = generate_lipsync_clips(script, character, chunks, ref_image, output_dir)

    # Step 5: Generate word-level subtitles
    console.print("[bold cyan]Step 5/6:[/bold cyan] Generating word-level subtitles...")
    subtitles = generate_subtitles(voiceover, output_dir)

    # Step 6: Assemble final video
    console.print("[bold cyan]Step 6/6:[/bold cyan] Assembling final video...")
    final = assemble_pov(clips, voiceover, subtitles, output_dir)

    console.print(f"\n[bold green]Done![/bold green] Video saved to: {final}")
    return final


def generate_pov_voiceover(script: Script, output_dir: Path) -> Path:
    """Generate POV voiceover using ElevenLabs with a female voice."""
    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    # Use dialogue from scenes if available, otherwise full_script
    text = script.full_script
    dialogue_parts = [s.dialogue for s in script.scenes if s.dialogue]
    if dialogue_parts:
        text = " ".join(dialogue_parts)

    audio_generator = client.text_to_speech.convert(
        text=text,
        voice_id=POV_VOICE_ID,
        model_id="eleven_v3",
        output_format="mp3_44100_128",
    )

    voiceover_path = output_dir / "voiceover.mp3"
    with open(voiceover_path, "wb") as f:
        for chunk in audio_generator:
            f.write(chunk)

    console.print(f"    Saved: {voiceover_path.name}")
    return voiceover_path


def split_audio_by_scenes(voiceover: Path, script: Script, output_dir: Path) -> list[Path]:
    """Split voiceover into chunks aligned to scene durations."""
    from pydub import AudioSegment

    audio = AudioSegment.from_mp3(str(voiceover))
    chunks: list[Path] = []
    position_ms = 0
    total_scene_duration = sum(s.duration_seconds for s in script.scenes)
    audio_duration_s = len(audio) / 1000.0

    for i, scene in enumerate(script.scenes):
        # Proportionally split audio based on scene duration ratios
        ratio = scene.duration_seconds / total_scene_duration
        chunk_duration_ms = int(ratio * len(audio))

        # Last chunk gets remainder
        if i == len(script.scenes) - 1:
            chunk = audio[position_ms:]
        else:
            chunk = audio[position_ms:position_ms + chunk_duration_ms]

        chunk_path = output_dir / "chunks" / f"chunk_{i + 1:02d}.mp3"
        chunk.export(str(chunk_path), format="mp3")
        chunk_duration_s = len(chunk) / 1000.0
        console.print(f"    Chunk {i + 1}: {chunk_duration_s:.1f}s ({scene.beat})")
        chunks.append(chunk_path)
        position_ms += chunk_duration_ms

    return chunks


def generate_pov_reference(character: Character, lighting: str, output_dir: Path) -> Path:
    """Generate a POV selfie reference portrait via Flux Pro."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    prompt = build_pov_reference_prompt(character, lighting)

    result = fal_client.subscribe(
        "fal-ai/flux-pro/v1.1",
        arguments={"prompt": prompt, "image_size": "portrait_16_9", "num_images": 1},
    )
    image_url = result["images"][0]["url"]
    ref_path = output_dir / "images" / "pov_reference.png"
    urllib.request.urlretrieve(image_url, str(ref_path))
    console.print(f"    Saved: {ref_path.name}")
    return ref_path


def generate_lipsync_clips(script: Script, character: Character,
                            chunks: list[Path], ref_image: Path,
                            output_dir: Path) -> list[Path]:
    """Generate lip-synced video clips using VEED Fabric 1.0."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    clips: list[Path] = []
    current_image = ref_image

    for i, (scene, chunk) in enumerate(zip(script.scenes, chunks)):
        console.print(f"  Scene {i + 1}/{len(script.scenes)} [{scene.beat}]: generating lip-sync clip...")

        image_url = fal_client.upload_file(str(current_image))
        audio_url = fal_client.upload_file(str(chunk))

        result = fal_client.subscribe(
            "veed/fabric-1.0",
            arguments={
                "image_url": image_url,
                "audio_url": audio_url,
                "resolution": "720p",
            },
        )

        video_url = result["video"]["url"]
        clip_path = output_dir / "clips" / f"clip_{i + 1:02d}.mp4"
        urllib.request.urlretrieve(video_url, str(clip_path))
        console.print(f"    Saved: {clip_path.name}")
        clips.append(clip_path)

        # Extract last frame for next clip's reference
        if i < len(script.scenes) - 1:
            last_frame = extract_last_frame(clip_path, output_dir, i + 1)
            if last_frame:
                current_image = last_frame

    return clips


def extract_last_frame(clip_path: Path, output_dir: Path, scene_num: int) -> Path | None:
    """Extract the last frame of a video clip using FFmpeg."""
    frame_path = output_dir / "images" / f"lastframe_{scene_num:02d}.png"
    cmd = [
        "ffmpeg", "-y", "-sseof", "-0.1", "-i", str(clip_path),
        "-frames:v", "1", "-q:v", "2", str(frame_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"    [yellow]Could not extract last frame, reusing previous reference[/yellow]")
        return None
    console.print(f"    Extracted last frame: {frame_path.name}")
    return frame_path


def generate_subtitles(voiceover: Path, output_dir: Path) -> Path:
    """Generate word-level subtitles using faster-whisper."""
    from faster_whisper import WhisperModel

    model = WhisperModel("base", compute_type="int8")
    segments, _ = model.transcribe(str(voiceover), word_timestamps=True)

    ass_path = output_dir / "subtitles.ass"
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,4,0,2,40,40,120,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for segment in segments:
        if segment.words:
            for word in segment.words:
                start = _format_ass_time(word.start)
                end = _format_ass_time(word.end)
                text = word.word.strip().upper()
                if text:
                    lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    ass_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"    Saved: {ass_path.name}")
    return ass_path


def _format_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format H:MM:SS.CC"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def assemble_pov(clips: list[Path], voiceover: Path, subtitles: Path,
                  output_dir: Path) -> Path:
    """Assemble POV video: concat clips + original voiceover + word-level subtitles."""
    concat_path = output_dir / "concat.txt"
    with open(concat_path, "w") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    # First concat clips without audio
    concat_video = output_dir / "concat_video.mp4"
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-c:v", "copy", "-an",
        str(concat_video),
    ]
    result = subprocess.run(cmd_concat, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]FFmpeg concat error:[/red]\n{result.stderr}")
        raise RuntimeError("FFmpeg concat failed")

    # Then overlay voiceover + burn subtitles
    final_path = output_dir / "final.mp4"
    cmd_final = [
        "ffmpeg", "-y",
        "-i", str(concat_video),
        "-i", str(voiceover),
        "-vf", f"ass='{subtitles.resolve()}'",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(final_path),
    ]
    result = subprocess.run(cmd_final, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback without subtitles if ASS burn fails
        console.print(f"  [yellow]Subtitle burn failed, assembling without subtitles[/yellow]")
        cmd_fallback = [
            "ffmpeg", "-y",
            "-i", str(concat_video),
            "-i", str(voiceover),
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            str(final_path),
        ]
        result = subprocess.run(cmd_fallback, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError("FFmpeg assembly failed")

    # Clean up temp files
    concat_path.unlink(missing_ok=True)
    concat_video.unlink(missing_ok=True)
    console.print(f"    Saved: {final_path.name}")
    return final_path


def _show_pov_dry_run(script: Script, character: Character, output_dir: Path) -> None:
    """Show what the POV pipeline would do."""
    console.print(f"\n[bold yellow]DRY RUN (POV MODE)[/bold yellow] -- Script #{script.id}: {script.topic}\n")

    console.print(f"  Character: [bold]{character.name}[/bold] ({character.age}, {character.gender})")
    console.print(f"  Mode: [bold magenta]POV lip-sync[/bold magenta]")
    console.print(f"  Output directory: {output_dir}")
    console.print(f"  Total scenes: {len(script.scenes)}")
    total_duration = sum(s.duration_seconds for s in script.scenes)
    console.print(f"  Total duration: {total_duration}s")
    console.print(f"  Estimated Fabric calls: {len(script.scenes)}")
    cost = total_duration * 0.15
    console.print(f"  Estimated cost: ~${cost:.2f} (Fabric 720p) + ElevenLabs + Flux Pro")
    console.print()

    table = Table(title="POV Render Plan")
    table.add_column("#", style="dim")
    table.add_column("Beat")
    table.add_column("Dialogue")
    table.add_column("Action")
    table.add_column("Dur")

    for i, scene in enumerate(script.scenes):
        dialogue = scene.dialogue or scene.voiceover
        table.add_row(
            str(i + 1),
            scene.beat,
            dialogue[:50] + ("..." if len(dialogue) > 50 else ""),
            scene.character_action[:30] + ("..." if len(scene.character_action) > 30 else ""),
            f"{scene.duration_seconds}s",
        )

    console.print(table)

    console.print(f"\n  [bold]Step 1:[/bold] Generate voiceover (ElevenLabs, female voice)")
    console.print(f"  [bold]Step 2:[/bold] Split audio into {len(script.scenes)} scene chunks")
    console.print(f"  [bold]Step 3:[/bold] Generate POV reference portrait (Flux Pro, selfie angle, teeth visible)")
    console.print(f"  [bold]Step 4:[/bold] Generate {len(script.scenes)} lip-sync clips (VEED Fabric 1.0, chained)")
    console.print(f"  [bold]Step 5:[/bold] Generate word-level subtitles (Whisper)")
    console.print(f"  [bold]Step 6:[/bold] Assemble with FFmpeg (concat + voiceover + subtitles)")
    console.print(f"\n  [dim]Run without --dry-run to execute.[/dim]\n")
