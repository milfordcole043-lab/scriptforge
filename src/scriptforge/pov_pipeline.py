from __future__ import annotations

import math
import os
import sqlite3
import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

from scriptforge import db
from scriptforge.config import (
    COST_ELEVENLABS, COST_FABRIC, COST_FLUX_PRO, COST_KLING_LIPSYNC, COST_KLING_V3,
    ELEVENLABS_API_KEY, FAL_KEY,
    KLING_NEGATIVE, MODEL_FABRIC, MODEL_FLUX_PRO, MODEL_KLING_LIPSYNC, MODEL_KLING_V3,
    OUTPUT_DIR, VOICE_POV,
    retry_api_call, safe_download,
)
from scriptforge.engine import build_pov_reference_prompt, build_pov_video_prompt
from scriptforge.models import Character, Script

console = Console()


def render_pov(conn: sqlite3.Connection, script_id: int, *,
               dry_run: bool = False, engine: str = "kling") -> Path | None:
    """Orchestrate the POV render pipeline. Engine: 'kling' (two-pass) or 'fabric' (legacy)."""
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
        _show_pov_dry_run(script, character, output_dir, engine=engine)
        return None

    from scriptforge.config import check_keys
    missing = check_keys()
    if missing:
        console.print(f"[red]Missing API keys: {', '.join(missing)}[/red]")
        return None

    (output_dir / "chunks").mkdir(parents=True, exist_ok=True)
    (output_dir / "clips").mkdir(parents=True, exist_ok=True)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)

    # Step 1: Generate full voiceover (cached)
    n_steps = 7 if engine == "kling" else 6
    console.print(f"\n[bold cyan]Step 1/{n_steps}:[/bold cyan] Generating voiceover...")
    voiceover = generate_pov_voiceover(script, output_dir, conn)

    # Step 2: Split audio into chunks
    console.print(f"[bold cyan]Step 2/{n_steps}:[/bold cyan] Splitting audio into scene chunks...")
    chunks = split_audio_by_scenes(voiceover, script, output_dir)

    # Step 3: Generate POV reference portrait (cached per script + outfit)
    first_scene = script.scenes[0] if script.scenes else None
    first_lighting = first_scene.lighting if first_scene else ""
    hook_emotion = first_scene.character_emotion if first_scene else ""
    ref_path = output_dir / "images" / "pov_reference.png"
    if ref_path.exists():
        console.print(f"[bold cyan]Step 3/{n_steps}:[/bold cyan] POV reference portrait cached, skipping.")
        ref_image = ref_path
    else:
        console.print(f"[bold cyan]Step 3/{n_steps}:[/bold cyan] Generating POV reference portrait...")
        ref_image = generate_pov_reference(
            character, first_lighting, hook_emotion, output_dir, conn, script_id,
            outfit_override=script.outfit, tone=script.tone,
        )

    if engine == "kling":
        # Step 4: Generate movement clips (Kling v3 Pro — full body/background animation)
        console.print(f"[bold cyan]Step 4/{n_steps}:[/bold cyan] Generating movement clips (Kling v3 Pro)...")
        movement_clips, clip_audio = generate_movement_clips(
            script, character, chunks, ref_image, output_dir, conn,
        )

        # Step 5: Apply lip-sync (Kling lip-sync — mouth animation on top of movement)
        console.print(f"[bold cyan]Step 5/{n_steps}:[/bold cyan] Applying lip-sync (Kling lip-sync)...")
        clips = apply_lipsync(movement_clips, clip_audio, script, output_dir, conn)

        # Step 6: Subtitles
        console.print(f"[bold cyan]Step 6/{n_steps}:[/bold cyan] Generating word-level subtitles...")
        subtitles = generate_subtitles(voiceover, output_dir)

        # Step 7: Assembly
        console.print(f"[bold cyan]Step 7/{n_steps}:[/bold cyan] Assembling final video...")
        final = assemble_pov(clips, voiceover, subtitles, output_dir)
    else:
        # Legacy Fabric pipeline
        console.print(f"[bold cyan]Step 4/{n_steps}:[/bold cyan] Generating lip-sync clips (VEED Fabric)...")
        clips = generate_lipsync_clips_fabric(script, character, chunks, ref_image, output_dir, conn)

        console.print(f"[bold cyan]Step 5/{n_steps}:[/bold cyan] Generating word-level subtitles...")
        subtitles = generate_subtitles(voiceover, output_dir)

        console.print(f"[bold cyan]Step 6/{n_steps}:[/bold cyan] Assembling final video...")
        final = assemble_pov(clips, voiceover, subtitles, output_dir)

    # Auto-review rendered output
    from scriptforge.config import ANTHROPIC_API_KEY
    if ANTHROPIC_API_KEY:
        console.print("[bold cyan]Reviewing render...[/bold cyan]")
        from scriptforge.vision_reviewer import review_rendered_video, print_review
        review = review_rendered_video(script, character, output_dir, conn)
        print_review(review)

    total_cost = db.get_render_cost(conn, script_id)
    console.print(f"\n[bold green]Done![/bold green] Video saved to: {final}")
    console.print(f"[bold]Total estimated cost: ${total_cost:.2f}[/bold]")
    return final


# --- Voiceover ---


def generate_pov_voiceover(script: Script, output_dir: Path,
                            conn: sqlite3.Connection | None = None) -> Path:
    """Generate POV voiceover using ElevenLabs with a female voice."""
    voiceover_path = output_dir / "voiceover.mp3"

    if voiceover_path.exists():
        console.print(f"    Cached: {voiceover_path.name}")
        return voiceover_path

    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    text = script.full_script
    dialogue_parts = [s.dialogue for s in script.scenes if s.dialogue]
    if dialogue_parts:
        text = " ".join(dialogue_parts)

    def _generate() -> bytes:
        gen = client.text_to_speech.convert(
            text=text,
            voice_id=VOICE_POV,
            model_id="eleven_v3",
            output_format="mp3_44100_128",
        )
        return b"".join(gen)

    audio_data = retry_api_call(_generate, label="ElevenLabs POV voiceover")
    with open(voiceover_path, "wb") as f:
        f.write(audio_data)

    from pydub import AudioSegment
    audio = AudioSegment.from_file(str(voiceover_path))
    original_dur_s = len(audio) / 1000.0
    target_s = float(script.total_duration)
    if original_dur_s > target_s * 1.1:
        speed_factor = min(1.5, original_dur_s / target_s)
        adjusted_s = original_dur_s / speed_factor
        console.print(f"    Adjusting speed: {original_dur_s:.1f}s -> {adjusted_s:.0f}s ({speed_factor:.2f}x)")
        audio = audio.speedup(playback_speed=speed_factor, chunk_size=150, crossfade=25)
        audio.export(str(voiceover_path), format="mp3")

    console.print(f"    Saved: {voiceover_path.name}")

    if conn:
        final_audio = AudioSegment.from_file(str(voiceover_path))
        final_dur_s = len(final_audio) / 1000.0
        db.log_render_step(conn, script.id, "pov_voiceover", "elevenlabs-v3",
                           final_dur_s, original_dur_s * COST_ELEVENLABS)

    return voiceover_path


# --- Audio splitting ---


def split_audio_by_scenes(voiceover: Path, script: Script, output_dir: Path) -> list[Path]:
    """Split voiceover into chunks aligned to scene durations."""
    from pydub import AudioSegment

    audio = AudioSegment.from_mp3(str(voiceover))
    chunks: list[Path] = []
    position_ms = 0
    total_scene_duration = sum(s.duration_seconds for s in script.scenes)
    if total_scene_duration == 0:
        raise ValueError("Cannot split audio: total scene duration is 0 seconds")

    for i, scene in enumerate(script.scenes):
        chunk_path = output_dir / "chunks" / f"chunk_{i + 1:02d}.mp3"

        if chunk_path.exists():
            console.print(f"    Chunk {i + 1}: cached, skipping.")
            chunks.append(chunk_path)
            ratio = scene.duration_seconds / total_scene_duration
            position_ms += int(ratio * len(audio))
            continue

        ratio = scene.duration_seconds / total_scene_duration
        chunk_duration_ms = int(ratio * len(audio))

        if i == len(script.scenes) - 1:
            chunk = audio[position_ms:]
        else:
            chunk = audio[position_ms:position_ms + chunk_duration_ms]

        chunk.export(str(chunk_path), format="mp3")
        chunk_duration_s = len(chunk) / 1000.0
        console.print(f"    Chunk {i + 1}: {chunk_duration_s:.1f}s ({scene.beat})")
        chunks.append(chunk_path)
        position_ms += chunk_duration_ms

    return chunks


# --- Reference portrait ---


def generate_pov_reference(character: Character, lighting: str, hook_emotion: str,
                            output_dir: Path,
                            conn: sqlite3.Connection | None = None,
                            script_id: int = 0,
                            outfit_override: str | None = None,
                            tone: str = "empowering") -> Path:
    """Generate a POV selfie reference portrait via Flux Pro with emotional state."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    ref_path = output_dir / "images" / "pov_reference.png"

    if ref_path.exists():
        console.print(f"    Cached: {ref_path.name}")
        return ref_path

    prompt = build_pov_reference_prompt(character, lighting, hook_emotion,
                                         outfit_override=outfit_override, tone=tone)

    result = retry_api_call(
        fal_client.subscribe, MODEL_FLUX_PRO,
        arguments={"prompt": prompt, "image_size": "portrait_16_9", "num_images": 1},
        label="Flux Pro (POV reference)",
    )
    safe_download(result["images"][0]["url"], str(ref_path), label="POV reference")

    if conn and script_id:
        db.log_render_step(conn, script_id, "pov_reference", "flux-pro", 0, COST_FLUX_PRO)

    console.print(f"    Saved: {ref_path.name}")
    return ref_path


# --- Chunk splitting ---


MAX_MOVEMENT_CHUNK_SECONDS = 10.0  # Kling lip-sync accepts 2-10s video
MAX_TOTAL_SUBCLIPS = 6


def _split_long_chunk(chunk_path: Path, max_seconds: float,
                      output_dir: Path, scene_num: int) -> list[Path]:
    """Split an audio chunk into sub-chunks if it exceeds max_seconds."""
    from pydub import AudioSegment

    audio = AudioSegment.from_file(str(chunk_path))
    duration_s = len(audio) / 1000.0

    if duration_s <= max_seconds:
        return [chunk_path]

    n_parts = math.ceil(duration_s / max_seconds)
    part_ms = len(audio) // n_parts
    sub_chunks: list[Path] = []

    for j in range(n_parts):
        sub_path = output_dir / "chunks" / f"chunk_{scene_num:02d}_{j + 1:02d}.mp3"
        start = j * part_ms
        end = len(audio) if j == n_parts - 1 else start + part_ms
        sub = audio[start:end]
        sub.export(str(sub_path), format="mp3")
        sub_chunks.append(sub_path)

    return sub_chunks


# --- Pass 1: Movement clips (Kling v3 Pro) ---


def generate_movement_clips(
    script: Script, character: Character,
    chunks: list[Path], ref_image: Path,
    output_dir: Path,
    conn: sqlite3.Connection | None = None,
) -> tuple[list[Path], list[Path]]:
    """Generate movement video clips using Kling v3 Pro.

    Pass 1 of two-pass pipeline: full body/background animation without lip-sync.
    Returns (clip_paths, matched_audio_paths) for the lip-sync pass.
    """
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    clips: list[Path] = []
    audio_for_clips: list[Path] = []
    current_image = ref_image
    total_subclips = 0

    for i, (scene, chunk) in enumerate(zip(script.scenes, chunks)):
        # Split long audio chunks, respect sub-clip budget
        remaining_budget = max(1, MAX_TOTAL_SUBCLIPS - total_subclips)
        chunk_max = MAX_MOVEMENT_CHUNK_SECONDS
        if remaining_budget <= 1:
            chunk_max = 999.0  # No splitting -- budget exhausted
        sub_chunks = _split_long_chunk(chunk, chunk_max, output_dir, i + 1)
        n_sub = len(sub_chunks)
        total_subclips += n_sub

        for j, sub_chunk in enumerate(sub_chunks):
            if n_sub == 1:
                clip_path = output_dir / "clips" / f"move_{i + 1:02d}.mp4"
                clip_label = f"scene {i + 1}"
            else:
                clip_path = output_dir / "clips" / f"move_{i + 1:02d}_{j + 1:02d}.mp4"
                clip_label = f"scene {i + 1} part {j + 1}/{n_sub}"

            # Resume: skip if exists
            if clip_path.exists():
                console.print(f"  {clip_label} [{scene.beat}]: cached, skipping.")
                clips.append(clip_path)
                audio_for_clips.append(sub_chunk)
                lf = extract_last_frame(clip_path, output_dir, i + 1)
                if lf:
                    current_image = lf
                continue

            # Determine clip duration from audio length, clamped to 3-10s
            from pydub import AudioSegment
            sub_dur_s = len(AudioSegment.from_file(str(sub_chunk))) / 1000.0
            duration = str(min(10, max(3, round(sub_dur_s))))

            console.print(f"  {clip_label} [{scene.beat}]: generating movement clip ({duration}s)...")

            # Build full cinematic prompt
            prev = script.scenes[i - 1] if i > 0 else None
            video_prompt = build_pov_video_prompt(
                scene, character, prev_scene=prev,
                scenes=script.scenes, scene_index=i,
                outfit_override=script.outfit,
            )

            image_url = retry_api_call(
                fal_client.upload_file, str(current_image),
                label=f"upload reference for {clip_label}",
            )

            result = retry_api_call(
                fal_client.subscribe, MODEL_KLING_V3,
                arguments={
                    "start_image_url": image_url,
                    "prompt": video_prompt,
                    "negative_prompt": KLING_NEGATIVE,
                    "duration": duration,
                    "generate_audio": False,
                },
                label=f"Kling v3 Pro ({clip_label})",
            )

            safe_download(result["video"]["url"], str(clip_path), label=f"{clip_label} movement clip")
            console.print(f"    Saved: {clip_path.name}")
            clips.append(clip_path)
            audio_for_clips.append(sub_chunk)

            if conn:
                step_name = f"movement_scene_{i + 1}" if n_sub == 1 else f"movement_scene_{i + 1}_sub_{j + 1}"
                db.log_render_step(conn, script.id, step_name, "kling-v3-pro",
                                   float(duration), float(duration) * COST_KLING_V3)

            # Extract last frame for chaining
            last_frame = extract_last_frame(clip_path, output_dir, i + 1)
            if last_frame:
                current_image = last_frame

    return clips, audio_for_clips


# --- Pass 2: Lip-sync (Kling lip-sync) ---


def apply_lipsync(
    clips: list[Path], audio_chunks: list[Path],
    script: Script, output_dir: Path,
    conn: sqlite3.Connection | None = None,
) -> list[Path]:
    """Apply lip-sync to movement clips using Kling lip-sync endpoint.

    Pass 2 of two-pass pipeline: overlays mouth animation onto moving video.
    """
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    synced: list[Path] = []

    for clip_path, audio_path in zip(clips, audio_chunks):
        synced_path = clip_path.with_name(clip_path.stem.replace("move_", "sync_") + ".mp4")

        # Resume: skip if exists
        if synced_path.exists():
            console.print(f"  {synced_path.stem}: cached, skipping.")
            synced.append(synced_path)
            continue

        console.print(f"  {clip_path.stem}: applying lip-sync...")

        video_url = retry_api_call(
            fal_client.upload_file, str(clip_path),
            label=f"upload video {clip_path.stem}",
        )
        audio_url = retry_api_call(
            fal_client.upload_file, str(audio_path),
            label=f"upload audio for {clip_path.stem}",
        )

        result = retry_api_call(
            fal_client.subscribe, MODEL_KLING_LIPSYNC,
            arguments={"video_url": video_url, "audio_url": audio_url},
            label=f"Kling lip-sync ({clip_path.stem})",
        )

        safe_download(result["video"]["url"], str(synced_path), label=f"{clip_path.stem} lip-synced")
        console.print(f"    Saved: {synced_path.name}")
        synced.append(synced_path)

        if conn:
            from pydub import AudioSegment
            dur_s = len(AudioSegment.from_file(str(audio_path))) / 1000.0
            billed_s = math.ceil(dur_s / 5) * 5
            db.log_render_step(conn, script.id, f"lipsync_{clip_path.stem}",
                               "kling-lipsync", dur_s, billed_s * COST_KLING_LIPSYNC)

    return synced


# --- Legacy Fabric pipeline (fallback) ---


MAX_FABRIC_CHUNK_SECONDS = 7.0


def generate_lipsync_clips_fabric(
    script: Script, character: Character,
    chunks: list[Path], ref_image: Path,
    output_dir: Path,
    conn: sqlite3.Connection | None = None,
) -> list[Path]:
    """Generate lip-synced video clips using VEED Fabric 1.0 (legacy fallback)."""
    import fal_client

    os.environ["FAL_KEY"] = FAL_KEY
    clips: list[Path] = []
    current_image = ref_image
    total_subclips = 0

    for i, (scene, chunk) in enumerate(zip(script.scenes, chunks)):
        remaining_budget = max(1, MAX_TOTAL_SUBCLIPS - total_subclips)
        chunk_max = MAX_FABRIC_CHUNK_SECONDS
        if remaining_budget <= 1:
            chunk_max = 999.0
        sub_chunks = _split_long_chunk(chunk, chunk_max, output_dir, i + 1)
        n_sub = len(sub_chunks)
        total_subclips += n_sub

        for j, sub_chunk in enumerate(sub_chunks):
            if n_sub == 1:
                clip_path = output_dir / "clips" / f"clip_{i + 1:02d}.mp4"
                clip_label = f"scene {i + 1}"
            else:
                clip_path = output_dir / "clips" / f"clip_{i + 1:02d}_{j + 1:02d}.mp4"
                clip_label = f"scene {i + 1} part {j + 1}/{n_sub}"

            if clip_path.exists():
                console.print(f"  {clip_label} [{scene.beat}]: cached, skipping.")
                clips.append(clip_path)
                lf = extract_last_frame(clip_path, output_dir, i + 1)
                if lf:
                    current_image = lf
                continue

            console.print(f"  {clip_label} [{scene.beat}]: generating lip-sync clip...")

            image_url = retry_api_call(
                fal_client.upload_file, str(current_image),
                label=f"upload reference for {clip_label}",
            )
            audio_url = retry_api_call(
                fal_client.upload_file, str(sub_chunk),
                label=f"upload audio {clip_label}",
            )

            result = retry_api_call(
                fal_client.subscribe, MODEL_FABRIC,
                arguments={"image_url": image_url, "audio_url": audio_url, "resolution": "720p"},
                label=f"VEED Fabric ({clip_label})",
            )

            safe_download(result["video"]["url"], str(clip_path), label=f"{clip_label} lip-sync clip")
            console.print(f"    Saved: {clip_path.name}")
            clips.append(clip_path)

            if conn:
                from pydub import AudioSegment
                sub_dur_s = len(AudioSegment.from_file(str(sub_chunk))) / 1000.0
                step_name = f"lipsync_scene_{i + 1}" if n_sub == 1 else f"lipsync_scene_{i + 1}_sub_{j + 1}"
                db.log_render_step(conn, script.id, step_name, "veed-fabric",
                                   sub_dur_s, sub_dur_s * COST_FABRIC)

            last_frame = extract_last_frame(clip_path, output_dir, i + 1)
            if last_frame:
                current_image = last_frame

    return clips


# --- Frame extraction ---


def extract_last_frame(clip_path: Path, output_dir: Path, scene_num: int) -> Path | None:
    """Extract the last frame of a video clip using FFmpeg."""
    frame_path = output_dir / "images" / f"lastframe_{scene_num:02d}.png"
    if frame_path.exists():
        return frame_path
    cmd = [
        "ffmpeg", "-y", "-sseof", "-0.1", "-i", str(clip_path),
        "-frames:v", "1", "-q:v", "2", str(frame_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        console.print(f"    [yellow]Could not extract last frame, reusing previous reference[/yellow]")
        return None
    console.print(f"    Extracted last frame: {frame_path.name}")
    return frame_path


# --- Subtitles ---


SUBTITLE_OFFSET: float = 0.3


def generate_subtitles(voiceover: Path, output_dir: Path) -> Path:
    """Generate word-level subtitles using faster-whisper with sync offset."""
    ass_path = output_dir / "subtitles.ass"

    if ass_path.exists():
        console.print(f"    Cached: {ass_path.name}")
        return ass_path

    from faster_whisper import WhisperModel

    model = WhisperModel("base", compute_type="int8")
    segments, _ = model.transcribe(str(voiceover), word_timestamps=True)

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
                start = _format_ass_time(word.start + SUBTITLE_OFFSET)
                end = _format_ass_time(word.end + SUBTITLE_OFFSET)
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


# --- Assembly ---


def assemble_pov(clips: list[Path], voiceover: Path, subtitles: Path,
                  output_dir: Path) -> Path:
    """Assemble POV video: concat clips + original voiceover + word-level subtitles."""
    final_path = output_dir / "final.mp4"

    concat_path = output_dir / "concat.txt"
    with open(concat_path, "w") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    concat_video = output_dir / "concat_video.mp4"
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-c:v", "copy", "-an",
        str(concat_video),
    ]
    result = subprocess.run(cmd_concat, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        console.print(f"[red]FFmpeg concat error:[/red]\n{result.stderr}")
        raise RuntimeError("FFmpeg concat failed")

    sub_path_escaped = str(subtitles.resolve()).replace("\\", "/").replace(":", "\\\\:")
    cmd_final = [
        "ffmpeg", "-y",
        "-i", str(concat_video),
        "-i", str(voiceover),
        "-vf", f"subtitles={sub_path_escaped}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(final_path),
    ]
    result = subprocess.run(cmd_final, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        console.print(f"  [yellow]Subtitle burn failed, assembling without subtitles[/yellow]")
        cmd_fallback = [
            "ffmpeg", "-y",
            "-i", str(concat_video),
            "-i", str(voiceover),
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            str(final_path),
        ]
        result = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError("FFmpeg assembly failed")

    concat_path.unlink(missing_ok=True)
    concat_video.unlink(missing_ok=True)
    console.print(f"    Saved: {final_path.name}")
    return final_path


# --- Dry run ---


def _show_pov_dry_run(script: Script, character: Character, output_dir: Path, *,
                      engine: str = "kling") -> None:
    """Show what the POV pipeline would do."""
    console.print(f"\n[bold yellow]DRY RUN (POV MODE)[/bold yellow] -- Script #{script.id}: {script.topic}\n")

    console.print(f"  Character: [bold]{character.name}[/bold] ({character.age}, {character.gender})")
    engine_label = "Kling two-pass (movement + lip-sync)" if engine == "kling" else "VEED Fabric (legacy)"
    console.print(f"  Engine: [bold magenta]{engine_label}[/bold magenta]")
    console.print(f"  Output directory: {output_dir}")
    console.print(f"  Total scenes: {len(script.scenes)}")
    total_duration = sum(s.duration_seconds for s in script.scenes)
    console.print(f"  Total duration: {total_duration}s")

    ref_cost = COST_FLUX_PRO if not (output_dir / "images" / "pov_reference.png").exists() else 0

    from scriptforge.config import WPM
    expected_audio_s = max(total_duration, script.word_count / WPM * 60)

    if engine == "kling":
        kling_video_cost = expected_audio_s * COST_KLING_V3
        # Lip-sync billed per 5s increment per clip
        n_clips = sum(max(1, math.ceil(s.duration_seconds / MAX_MOVEMENT_CHUNK_SECONDS))
                      for s in script.scenes)
        kling_lipsync_cost = sum(
            math.ceil(min(s.duration_seconds, MAX_MOVEMENT_CHUNK_SECONDS) / 5) * 5 * COST_KLING_LIPSYNC
            for s in script.scenes
        )
        vo_cost = expected_audio_s * COST_ELEVENLABS
        total_cost = ref_cost + kling_video_cost + kling_lipsync_cost + vo_cost
        console.print(f"  [bold]Estimated cost: ~${total_cost:.2f}[/bold] ({n_clips} clips x 2 passes)")
        console.print(f"    Reference: ${ref_cost:.2f} | Kling video: ${kling_video_cost:.2f}"
                       f" | Kling lip-sync: ${kling_lipsync_cost:.2f} | Voiceover: ${vo_cost:.2f}")
    else:
        fabric_cost = expected_audio_s * COST_FABRIC
        vo_cost = expected_audio_s * COST_ELEVENLABS
        n_clips = sum(max(1, math.ceil(s.duration_seconds / MAX_FABRIC_CHUNK_SECONDS))
                      for s in script.scenes)
        total_cost = ref_cost + fabric_cost + vo_cost
        console.print(f"  [bold]Estimated cost: ~${total_cost:.2f}[/bold] ({n_clips} clips)")
        console.print(f"    Reference: ${ref_cost:.2f} | Fabric: ${fabric_cost:.2f} | Voiceover: ${vo_cost:.2f}")

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
    ref_status = "cached" if (output_dir / "images" / "pov_reference.png").exists() else "generate new"
    console.print(f"  [bold]Step 3:[/bold] POV reference portrait ({ref_status})")

    if engine == "kling":
        console.print(f"  [bold]Step 4:[/bold] Generate movement clips (Kling v3 Pro, chained)")
        console.print(f"  [bold]Step 5:[/bold] Apply lip-sync (Kling lip-sync, per clip)")
        console.print(f"  [bold]Step 6:[/bold] Generate word-level subtitles (Whisper)")
        console.print(f"  [bold]Step 7:[/bold] Assemble with FFmpeg (concat + voiceover + subtitles)")
    else:
        console.print(f"  [bold]Step 4:[/bold] Generate lip-sync clips (VEED Fabric 1.0, chained)")
        console.print(f"  [bold]Step 5:[/bold] Generate word-level subtitles (Whisper)")
        console.print(f"  [bold]Step 6:[/bold] Assemble with FFmpeg (concat + voiceover + subtitles)")

    console.print(f"\n  [dim]Run without --dry-run to execute.[/dim]\n")
