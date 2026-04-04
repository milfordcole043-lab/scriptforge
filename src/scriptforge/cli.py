from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scriptforge import db
from scriptforge.engine import (
    analyze_feedback_patterns, auto_optimize, build_rewrite_context,
    build_write_context, generate_topics,
)
from scriptforge.pipeline import render_script

console = Console()


def _get_conn(ctx: click.Context) -> sqlite3.Connection:
    if "conn" not in ctx.obj:
        ctx.obj["conn"] = db.connect(ctx.obj["db_path"])
        db.seed_defaults(ctx.obj["conn"])
    return ctx.obj["conn"]


@click.group()
@click.option("--db-path", default=None, hidden=True, help="Override database path.")
@click.pass_context
def cli(ctx: click.Context, db_path: str | None) -> None:
    """ScriptForge - a knowledge system for better video scripts."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = Path(db_path) if db_path else db.DEFAULT_DB


# --- write ---


@cli.command()
@click.argument("topic")
@click.option("--style", "-s", type=click.Choice(["educational", "story", "viral", "cinematic", "explainer"]),
              default="educational", help="Script style.")
@click.option("--duration", "-d", type=int, default=45, help="Target duration in seconds.")
@click.option("--template", "-t", default=None, help="Override template (e.g. 'mystery', 'contradiction').")
@click.option("--no-generate", is_flag=True, hidden=True, help="Show context only (for testing).")
@click.pass_context
def write(ctx: click.Context, topic: str, style: str, duration: int,
          template: str | None, no_generate: bool) -> None:
    """Write a new script. Assembles context from rulebook, hooks, and feedback."""
    conn = _get_conn(ctx)
    context = build_write_context(conn, topic=topic, style=style, duration_target=duration,
                                   template_name=template)
    from scriptforge.config import WPM
    wpm = WPM
    word_target = duration * wpm // 60

    tmpl = context["template"]
    if tmpl:
        arc_str = " -> ".join(b["beat"] for b in tmpl.beat_structure)
        tmpl_line = f"\n[bold]Template:[/bold] {tmpl.name} [dim]({context['template_reason']})[/dim]"
    else:
        arc_str = "hook -> tension -> revelation -> resolution"
        tmpl_line = ""
    console.print(Panel(f"[bold]Topic:[/bold] {topic}\n[bold]Style:[/bold] {style}\n"
                        f"[bold]Duration:[/bold] {duration}s (~{word_target} words at {wpm} wpm)"
                        f"{tmpl_line}\n[bold]Arc:[/bold] {arc_str}",
                        title="Script Brief"))

    if context["voice_profile"]:
        console.print(f"\n[bold cyan]Voice Profile:[/bold cyan]")
        for vp in context["voice_profile"]:
            console.print(f"  [dim]{vp.attribute}:[/dim] {vp.value}")

    if context["rules"]:
        console.print(f"\n[bold cyan]Rulebook ({len(context['rules'])} rules):[/bold cyan]")
        for r in context["rules"]:
            cat = f"[dim][{r.category}][/dim] " if r.category else ""
            console.print(f"  {cat}{r.rule}")

    if context["top_hooks"]:
        console.print(f"\n[bold cyan]Top Hooks ({len(context['top_hooks'])}):[/bold cyan]")
        for h in context["top_hooks"][:5]:
            rating_str = f" [green](good)[/green]" if h.rating == "good" else ""
            console.print(f'  "{h.text}"{rating_str}')

    patterns = context["feedback_patterns"]
    if patterns["hit_notes"] or patterns["miss_notes"]:
        console.print(f"\n[bold cyan]Feedback Patterns:[/bold cyan]")
        for note in patterns["hit_notes"][:3]:
            console.print(f"  [green]+[/green] {note}")
        for note in patterns["miss_notes"][:3]:
            console.print(f"  [red]-[/red] {note}")

    console.print("\n[bold]Context assembled.[/bold] Prompt ready.\n")

    if no_generate:
        return

    console.print(Panel(context["prompt"], title="Generation Prompt", border_style="dim"))
    console.print("\n[dim]Use this prompt to generate the script, then save with the data.[/dim]")


# --- view ---


@cli.command()
@click.argument("script_id", type=int)
@click.pass_context
def view(ctx: click.Context, script_id: int) -> None:
    """View a full script with scenes."""
    conn = _get_conn(ctx)
    script = db.get_script(conn, script_id)
    if not script:
        console.print(f"[red]Script #{script_id} not found.[/red]")
        return

    tags_str = " ".join(f"[magenta]#{t}[/magenta]" for t in script.tags)
    header = (f"[bold]{script.topic}[/bold] ({script.style}, {script.duration_target}s)\n"
              f"Hook: {script.hook}\n"
              f"Words: {script.word_count} | Version: {script.version} | Duration: {script.total_duration}s")
    if tags_str:
        header += f" | Tags: {tags_str}"
    if script.rating:
        color = "green" if script.rating == "hit" else "red" if script.rating == "miss" else "yellow"
        header += f" | Rating: [{color}]{script.rating}[/{color}]"

    console.print(Panel(header, title=f"Script #{script.id}"))

    if script.character_id:
        char = db.get_character(conn, script.character_id)
        if char:
            console.print(f"\n[bold]Character:[/bold] {char.name} ({char.age}, {char.gender}) -- {char.appearance}, wearing {char.clothing}")

    if script.scenes:
        table = Table(title="Scenes")
        table.add_column("#", style="dim")
        table.add_column("Beat")
        table.add_column("Caption")
        table.add_column("Action")
        table.add_column("Location")
        table.add_column("Camera")
        table.add_column("Emotion")
        table.add_column("Dur", justify="right")
        for i, s in enumerate(script.scenes, 1):
            table.add_row(str(i), s.beat, s.caption, s.character_action[:30],
                          s.location[:25], s.camera, s.character_emotion, f"{s.duration_seconds}s")
        console.print(table)

    if script.full_script:
        console.print(Panel(script.full_script, title="Full Script"))

    if script.feedback:
        console.print(f"\n[bold]Feedback:[/bold] {script.feedback}")


# --- list ---


@cli.command("list")
@click.pass_context
def list_cmd(ctx: click.Context) -> None:
    """List all scripts with ratings."""
    conn = _get_conn(ctx)
    scripts = db.list_scripts(conn)
    if not scripts:
        console.print("[dim]No scripts yet.[/dim]")
        return

    table = Table(title="Scripts")
    table.add_column("ID", style="dim")
    table.add_column("Topic")
    table.add_column("Style")
    table.add_column("Words", justify="right")
    table.add_column("Rating")
    table.add_column("Ver", justify="right")
    for s in scripts:
        rating = ""
        if s.rating:
            color = "green" if s.rating == "hit" else "red" if s.rating == "miss" else "yellow"
            rating = f"[{color}]{s.rating}[/{color}]"
        table.add_row(str(s.id), s.topic, s.style, str(s.word_count), rating, str(s.version))
    console.print(table)


# --- rate ---


@cli.command()
@click.argument("script_id", type=int)
@click.argument("rating", type=click.Choice(["hit", "miss", "rewrite"]))
@click.argument("notes")
@click.pass_context
def rate(ctx: click.Context, script_id: int, rating: str, notes: str) -> None:
    """Rate a script (quick mode). For scene-by-scene feedback, use 'scriptforge feedback-rate'."""
    conn = _get_conn(ctx)
    if db.rate_script(conn, script_id, rating, notes):
        color = "green" if rating == "hit" else "red" if rating == "miss" else "yellow"
        console.print(f"[{color}]Rated #{script_id} as {rating}.[/{color}] Feedback logged.")
    else:
        console.print(f"[red]Script #{script_id} not found.[/red]")


@cli.command("feedback-rate")
@click.argument("script_id", type=int)
@click.pass_context
def feedback_rate(ctx: click.Context, script_id: int) -> None:
    """Rate a script scene-by-scene with granular feedback."""
    conn = _get_conn(ctx)
    script = db.get_script(conn, script_id)
    if not script:
        console.print(f"[red]Script #{script_id} not found.[/red]")
        return

    console.print(f"\n[bold]Rating script #{script_id}: {script.topic}[/bold]\n")
    is_pov = script.mode == "pov"
    all_scores: list[float] = []

    for i, scene in enumerate(script.scenes):
        console.print(f"[bold cyan]Scene {i + 1}[/bold cyan] [{scene.beat}] — {scene.caption}")
        console.print(f"  Action: {scene.character_action[:60]}")
        console.print(f"  Duration: {scene.duration_seconds}s")

        vis = click.prompt("  Visual quality (1-5)", type=click.IntRange(1, 5))
        emo = click.prompt("  Emotional impact (1-5)", type=click.IntRange(1, 5))
        pace = click.prompt("  Pacing (1-5)", type=click.IntRange(1, 5))
        lip = None
        if is_pov:
            lip = click.prompt("  Lip sync quality (1-5)", type=click.IntRange(1, 5))

        notes = click.prompt("  Notes (optional)", default="", show_default=False)

        db.save_scene_feedback(conn, script_id, i, vis, emo, pace, lip, notes)
        avg = (vis + emo + pace + (lip or 0)) / (4 if lip else 3)
        all_scores.append(avg)
        console.print(f"  [dim]Scene {i + 1} average: {avg:.1f}/5[/dim]\n")

    overall = sum(all_scores) / len(all_scores) if all_scores else 0
    overall_notes = click.prompt("Overall notes", default="", show_default=False)

    # Map to hit/miss/rewrite for backward compatibility
    if overall >= 4:
        auto_rating = "hit"
    elif overall >= 2.5:
        auto_rating = "rewrite"
    else:
        auto_rating = "miss"

    db.rate_script(conn, script_id, auto_rating,
                   f"Scene-level avg: {overall:.1f}/5. {overall_notes}")

    color = "green" if auto_rating == "hit" else "yellow" if auto_rating == "rewrite" else "red"
    console.print(f"\n[{color}]Overall: {overall:.1f}/5 ({auto_rating})[/{color}]")
    console.print(f"[green]Scene feedback saved for all {len(script.scenes)} scenes.[/green]")

    # Auto-optimization: update template rates, detect patterns, generate rules
    learned = auto_optimize(conn)
    if learned:
        console.print(f"\n[bold cyan]System learned:[/bold cyan]")
        for msg in learned:
            console.print(msg)


@cli.command()
@click.argument("script_id", type=int)
@click.pass_context
def feedback(ctx: click.Context, script_id: int) -> None:
    """View scene-level feedback for a script."""
    conn = _get_conn(ctx)
    entries = db.get_scene_feedback(conn, script_id)
    if not entries:
        console.print(f"[dim]No scene feedback for script #{script_id}.[/dim]")
        return

    table = Table(title=f"Scene Feedback — Script #{script_id}")
    table.add_column("#", style="dim")
    table.add_column("Visual")
    table.add_column("Emotion")
    table.add_column("Pacing")
    table.add_column("Lip Sync")
    table.add_column("Notes")
    for sf in entries:
        lip_str = str(sf.lip_sync) if sf.lip_sync else "-"
        table.add_row(str(sf.scene_index + 1), str(sf.visual_quality), str(sf.emotional_impact),
                       str(sf.pacing), lip_str, sf.notes[:40])
    console.print(table)


@cli.command()
@click.argument("script_id", type=int)
@click.pass_context
def review(ctx: click.Context, script_id: int) -> None:
    """Run vision review on a rendered script."""
    conn = _get_conn(ctx)
    script = db.get_script(conn, script_id)
    if not script:
        console.print(f"[red]Script #{script_id} not found.[/red]")
        return

    character = None
    if script.character_id:
        character = db.get_character(conn, script.character_id)
    if not character:
        console.print("[red]No character linked to this script.[/red]")
        return

    from scriptforge.config import ANTHROPIC_API_KEY, OUTPUT_DIR
    if not ANTHROPIC_API_KEY:
        console.print("[red]ANTHROPIC_API_KEY not set in .env[/red]")
        return

    output_dir = OUTPUT_DIR / str(script_id)
    if not (output_dir / "final.mp4").exists():
        console.print(f"[red]No rendered video found at {output_dir}/final.mp4[/red]")
        return

    from scriptforge.vision_reviewer import review_rendered_video, print_review
    rev = review_rendered_video(script, character, output_dir, conn)
    print_review(rev)


@cli.command()
@click.pass_context
def reviews(ctx: click.Context) -> None:
    """Show all past video reviews."""
    conn = _get_conn(ctx)
    # Get distinct script_ids from video_reviews
    rows = conn.execute(
        "SELECT DISTINCT script_id FROM video_reviews ORDER BY script_id",
    ).fetchall()
    if not rows:
        console.print("[dim]No video reviews yet.[/dim]")
        return

    for (sid,) in rows:
        reviews_data = db.get_video_reviews(conn, sid)
        if reviews_data:
            scores = [r["score"] for r in reviews_data]
            avg = sum(scores) / len(scores) if scores else 0
            color = "green" if avg >= 7 else "yellow" if avg >= 5 else "red"
            console.print(f"  Script #{sid}: [{color}]{avg:.1f}/10[/{color}] ({len(scores)} scenes reviewed)")


# --- rewrite ---


@cli.command()
@click.argument("script_id", type=int)
@click.pass_context
def rewrite(ctx: click.Context, script_id: int) -> None:
    """Rewrite a script using its feedback."""
    conn = _get_conn(ctx)
    context = build_rewrite_context(conn, script_id)
    if not context:
        console.print(f"[red]Script #{script_id} not found.[/red]")
        return

    original = context["original_script"]
    console.print(Panel(f"[bold]Rewriting:[/bold] {original.topic} (v{original.version})\n"
                        f"[bold]Feedback:[/bold]\n{context['feedback'] or 'None'}",
                        title=f"Rewrite #{script_id}"))

    console.print(Panel(context["prompt"], title="Rewrite Prompt", border_style="dim"))


# --- hooks ---


@cli.command()
@click.pass_context
def hooks(ctx: click.Context) -> None:
    """List top-rated hooks."""
    conn = _get_conn(ctx)
    hook_list = db.get_top_hooks(conn, limit=15)
    if not hook_list:
        console.print("[dim]No hooks yet.[/dim]")
        return

    table = Table(title="Top Hooks")
    table.add_column("ID", style="dim")
    table.add_column("Hook")
    table.add_column("Style")
    table.add_column("Rating")
    for h in hook_list:
        rating = ""
        if h.rating:
            color = "green" if h.rating == "good" else "red"
            rating = f"[{color}]{h.rating}[/{color}]"
        table.add_row(str(h.id), h.text, h.style or "", rating)
    console.print(table)


@cli.command()
@click.pass_context
def templates(ctx: click.Context) -> None:
    """List all story templates with success rates."""
    conn = _get_conn(ctx)
    tmpl_list = db.get_all_templates(conn)
    if not tmpl_list:
        console.print("[dim]No templates found.[/dim]")
        return

    table = Table(title="Story Templates")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Beats")
    table.add_column("Rate", justify="right")
    table.add_column("Used", justify="right")
    for t in tmpl_list:
        beats = " -> ".join(b["beat"] for b in t.beat_structure)
        rate_str = f"{t.success_rate:.1f}" if t.success_rate > 0 else "-"
        if t.success_rate >= 4.0:
            rate_str = f"[green]{rate_str}[/green]"
        elif t.success_rate >= 3.0:
            rate_str = f"[yellow]{rate_str}[/yellow]"
        elif t.success_rate > 0:
            rate_str = f"[red]{rate_str}[/red]"
        desc = t.description[:60] + "..." if len(t.description) > 60 else t.description
        table.add_row(t.name, desc, beats, rate_str, str(t.times_used))
    console.print(table)


@cli.command()
@click.option("--count", "-c", type=int, default=5, help="Number of topics to generate.")
@click.pass_context
def topics(ctx: click.Context, count: int) -> None:
    """Generate topic suggestions using Claude, informed by templates and history."""
    conn = _get_conn(ctx)
    from scriptforge.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        console.print("[red]ANTHROPIC_API_KEY not set in .env[/red]")
        return

    console.print(f"[dim]Generating {count} topic ideas...[/dim]\n")
    try:
        topic_list = generate_topics(conn, count=count)
    except Exception as e:
        console.print(f"[red]Error generating topics: {e}[/red]")
        return

    if not topic_list:
        console.print("[dim]No topics generated.[/dim]")
        return

    table = Table(title="Topic Ideas")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Topic", style="bold")
    table.add_column("Template")
    table.add_column("Angle")
    table.add_column("Why", style="dim")
    for i, t in enumerate(topic_list, 1):
        table.add_row(str(i), t["topic"], t["template"], t["angle"], t["why"])
    console.print(table)
    console.print(f"\n[dim]Use: scriptforge write \"<topic>\" to start writing.[/dim]")


# --- rules ---


@cli.command()
@click.option("--add", "rule_text", default=None, help="Add a new rule.")
@click.option("--category", "-c", default=None, help="Rule category.")
@click.pass_context
def rules(ctx: click.Context, rule_text: str | None, category: str | None) -> None:
    """Show active rulebook, or add a new rule with --add."""
    conn = _get_conn(ctx)
    if rule_text:
        rule = db.add_rule(conn, rule=rule_text, category=category)
        console.print(f"[green]Rule added:[/green] #{rule.id} -- {rule.rule}")
        return

    active = db.get_active_rules(conn)
    if not active:
        console.print("[dim]No active rules yet.[/dim]")
        return

    table = Table(title="Rulebook")
    table.add_column("ID", style="dim")
    table.add_column("Category")
    table.add_column("Rule")
    for r in active:
        table.add_row(str(r.id), r.category or "", r.rule)
    console.print(table)


# --- search ---


@cli.command()
@click.argument("query")
@click.pass_context
def search(ctx: click.Context, query: str) -> None:
    """Search scripts by topic, hook, or content."""
    conn = _get_conn(ctx)
    results = db.search_scripts(conn, query)
    if not results:
        console.print(f"[dim]No results for \"{query}\".[/dim]")
        return

    table = Table(title=f"Search: {query}")
    table.add_column("ID", style="dim")
    table.add_column("Topic")
    table.add_column("Hook")
    table.add_column("Rating")
    for s in results:
        rating = s.rating or ""
        table.add_row(str(s.id), s.topic, s.hook[:50], rating)
    console.print(table)


# --- export ---


@cli.command()
@click.argument("script_id", type=int)
@click.option("--output", "-o", default=None, help="Output file path.")
@click.pass_context
def export(ctx: click.Context, script_id: int, output: str | None) -> None:
    """Export a script to a .txt file."""
    conn = _get_conn(ctx)
    script = db.get_script(conn, script_id)
    if not script:
        console.print(f"[red]Script #{script_id} not found.[/red]")
        return

    filename = output or f"script_{script_id}_{script.topic.replace(' ', '_').lower()}.txt"
    content = f"TOPIC: {script.topic}\nSTYLE: {script.style}\nDURATION: {script.duration_target}s\n\n"
    content += f"HOOK: {script.hook}\n\n"
    content += "SCENES:\n"
    for i, s in enumerate(script.scenes, 1):
        content += f"\n[Scene {i} - {s.beat} - {s.duration_seconds}s]\n"
        content += f"CAPTION: {s.caption}\n"
        if s.dialogue:
            content += f"DIALOGUE: {s.dialogue}\n"
        if s.voiceover:
            content += f"VO: {s.voiceover}\n"
        content += f"ACTION: {s.character_action}\n"
        content += f"LOCATION: {s.location}\n"
        content += f"LIGHTING: {s.lighting}\n"
        content += f"CAMERA: {s.camera} | MOTION: {s.motion} | SOUND: {s.sound}\n"
        content += f"EMOTION: {s.character_emotion}\n"
    content += f"\nFULL SCRIPT:\n{script.full_script}\n"

    Path(filename).write_text(content, encoding="utf-8")
    console.print(f"[green]Exported:[/green] {filename}")


# --- stats ---


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show productivity stats."""
    conn = _get_conn(ctx)
    s = db.get_stats(conn)
    if s["total_scripts"] == 0:
        console.print("[dim]No scripts yet.[/dim]")
        return

    console.print("\n[bold]ScriptForge Stats[/bold]\n")
    console.print(f"  Total scripts:  {s['total_scripts']}")
    console.print(f"  Rated:          {s['rated_scripts']}")
    console.print(f"  Hit rate:       [bold]{s['hit_rate']}%[/bold]")
    console.print(f"  Active rules:   {s['total_rules']}")

    if s["style_counts"]:
        console.print("\n  [bold]By style:[/bold]")
        for style, count in s["style_counts"].items():
            console.print(f"    {style}: {count}")

    if s["rating_counts"]:
        console.print("\n  [bold]By rating:[/bold]")
        for rating, count in s["rating_counts"].items():
            color = "green" if rating == "hit" else "red" if rating == "miss" else "yellow"
            console.print(f"    [{color}]{rating}[/{color}]: {count}")
    console.print()


# --- analyze ---


@cli.command()
@click.pass_context
def analyze(ctx: click.Context) -> None:
    """Analyze feedback patterns and suggest new rules."""
    conn = _get_conn(ctx)
    patterns = analyze_feedback_patterns(conn)

    if patterns["total_rated"] == 0:
        console.print("[dim]Not enough rated scripts to analyze. Rate some scripts first.[/dim]")
        return

    console.print("\n[bold]Feedback Analysis[/bold]\n")
    console.print(f"  Total feedback entries: {patterns['total_rated']}")

    if patterns["hit_notes"]:
        console.print("\n  [bold green]What works (hits):[/bold green]")
        for note in patterns["hit_notes"]:
            console.print(f"    [green]+[/green] {note}")

    if patterns["miss_notes"]:
        console.print("\n  [bold red]What fails (misses):[/bold red]")
        for note in patterns["miss_notes"]:
            console.print(f"    [red]-[/red] {note}")

    console.print("\n[dim]Use 'scriptforge rules --add \"rule\"' to codify patterns into your rulebook.[/dim]\n")


# --- render ---


@cli.command()
@click.argument("script_id", type=int)
@click.option("--dry-run", is_flag=True, help="Show render plan without calling APIs.")
@click.pass_context
def render(ctx: click.Context, script_id: int, dry_run: bool) -> None:
    """Render a script into a finished video."""
    conn = _get_conn(ctx)
    render_script(conn, script_id, dry_run=dry_run)


# --- character ---


@cli.command()
@click.argument("name")
@click.option("--age", required=True, help="Character age (e.g. 'late 20s').")
@click.option("--gender", required=True, help="Character gender.")
@click.option("--appearance", required=True, help="Physical appearance details.")
@click.option("--clothing", required=True, help="Specific outfit description.")
@click.pass_context
def character(ctx: click.Context, name: str, age: str, gender: str,
              appearance: str, clothing: str) -> None:
    """Create a character profile for use in scripts."""
    conn = _get_conn(ctx)
    char = db.add_character(conn, name=name, age=age, gender=gender,
                            appearance=appearance, clothing=clothing)
    console.print(f"\n[green]Character created:[/green] #{char.id} -- {char.name}")
    console.print(f"  Age: {char.age} | Gender: {char.gender}")
    console.print(f"  Appearance: {char.appearance}")
    console.print(f"  Clothing: {char.clothing}")
    console.print(f"\n[dim]Use --character {char.id} when writing scripts.[/dim]\n")


@cli.command("characters")
@click.pass_context
def list_characters_cmd(ctx: click.Context) -> None:
    """List all character profiles."""
    conn = _get_conn(ctx)
    chars = db.list_characters(conn)
    if not chars:
        console.print("[dim]No characters yet.[/dim]")
        return
    table = Table(title="Characters")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Age")
    table.add_column("Appearance")
    table.add_column("Clothing")
    table.add_column("Portrait")
    for c in chars:
        has_ref = "[green]yes[/green]" if c.reference_image_path else "[dim]no[/dim]"
        table.add_row(str(c.id), c.name, c.age, c.appearance[:40], c.clothing[:30], has_ref)
    console.print(table)


# --- migrations ---


@cli.command("migrate-maya")
@click.pass_context
def migrate_maya(ctx: click.Context) -> None:
    """Update Maya's appearance, wardrobe, and reset her reference portrait."""
    conn = _get_conn(ctx)
    char = db.get_character(conn, 1)
    if not char or char.name.lower() != "maya":
        console.print("[red]Maya not found at character ID 1.[/red]")
        return

    # Update appearance
    new_appearance = (
        "dark wavy hair styled and clean, warm brown skin with healthy glow, "
        "high cheekbones, full lips, expressive dark eyes with long lashes, "
        "slim athletic build, bright alert eyes, confident natural expression, "
        "clear skin, small beauty mark below left eye, two thin gold rings on right hand, "
        "slightly asymmetric smile wider on the left"
    )
    db.update_character_appearance(conn, char.id, appearance=new_appearance)
    console.print("[green]Updated appearance.[/green]")

    # Replace wardrobe
    new_wardrobe = [
        {"outfit": "fitted black leather jacket over white silk camisole, gold layered necklaces", "tones": ["empowering", "intense"]},
        {"outfit": "rust colored satin slip dress with thin straps, delicate chain bracelet", "tones": ["empowering", "curious"]},
        {"outfit": "emerald green crop top, high-waisted black tailored pants, statement earrings", "tones": ["empowering", "intense"]},
        {"outfit": "cream oversized cashmere sweater falling off one shoulder, minimal gold jewelry", "tones": ["curious", "vulnerable"]},
        {"outfit": "burgundy velvet blazer, black lace top underneath, rings on every finger", "tones": ["empowering", "intense"]},
        {"outfit": "white bodysuit tucked into light wash vintage jeans, chunky gold hoops", "tones": ["empowering", "curious"]},
    ]
    db.update_character_wardrobe(conn, char.id, new_wardrobe)
    console.print(f"[green]Replaced wardrobe with {len(new_wardrobe)} outfits.[/green]")

    # Clear reference portrait
    if char.reference_image_path:
        ref_path = Path(char.reference_image_path)
        if ref_path.exists():
            ref_path.unlink()
            console.print(f"[yellow]Deleted old portrait: {ref_path.name}[/yellow]")
    db.update_character_image(conn, char.id, "")
    console.print("[green]Cleared reference image path — fresh portrait will generate on next render.[/green]")

    # Seed new body language and quality rules into existing DB
    existing_rules = {r.rule for r in db.get_active_rules(conn)}
    new_rules = [
        ("Slow subtle character movements create life: gentle weight shift, slight lean forward, fingers touching jewelry, small hand gestures while talking. Background elements should move MORE than the character.", "visual", "body language system"),
        ("What fails in lip-sync video: fast camera pans, camera rotation, character walking while talking, complex simultaneous body movements. What works: gentle sway, hair touch, head tilt, necklace touch.", "visual", "body language system"),
        ("Never describe a character with perfect symmetry or flawless skin. Include natural imperfections: beauty marks, asymmetric smile, visible pores. AI artifacts come from over-idealized descriptions.", "visual", "quality system"),
    ]
    added = 0
    for rule_text, category, source in new_rules:
        if rule_text not in existing_rules:
            db.add_rule(conn, rule=rule_text, category=category, source=source)
            added += 1
    if added:
        console.print(f"[green]Added {added} new rules (body language + quality).[/green]")

    console.print("\n[bold green]Maya migration complete.[/bold green]\n")


# --- research ---


@cli.command()
@click.argument("topic")
@click.pass_context
def research(ctx: click.Context, topic: str) -> None:
    """Research a topic and store findings."""
    from scriptforge.researcher import extract_findings_from_text
    conn = _get_conn(ctx)
    console.print(f"\n[bold]Researching:[/bold] {topic}")
    console.print("[dim]Provide your research text, and findings will be extracted and stored.[/dim]")
    console.print("[dim]Use this command after gathering research via web search.[/dim]\n")
    # This command is designed to be called by Claude Code with research context
    # The actual research text comes from Claude's web search results
    console.print(f"[yellow]Topic '{topic}' registered.[/yellow] Use Claude Code to research and feed findings.")


# --- transcript ---


@cli.command()
@click.argument("url")
@click.pass_context
def transcript(ctx: click.Context, url: str) -> None:
    """Pull and analyze a YouTube video transcript."""
    from scriptforge.researcher import pull_youtube_transcript, extract_findings_from_text
    conn = _get_conn(ctx)

    console.print(f"\n[bold]Pulling transcript:[/bold] {url}")
    text = pull_youtube_transcript(url)
    if not text:
        console.print("[red]Could not fetch transcript. Check the URL or video availability.[/red]")
        return

    console.print(f"  Transcript length: {len(text.split())} words")
    findings = extract_findings_from_text(text, topic=f"YouTube: {url}", source_url=url)

    for f in findings:
        db.add_finding(conn, topic=f["topic"], finding=f["finding"], category=f["category"],
                       source_url=f.get("source_url"), source_title=f.get("source_title"),
                       confidence=f.get("confidence", "medium"))

    console.print(f"  [green]Extracted {len(findings)} findings.[/green]\n")


# --- findings ---


@cli.command()
@click.option("--apply", "apply_findings", is_flag=True, help="Apply unapplied findings to rulebook.")
@click.option("--category", "-c", default=None, help="Filter by category.")
@click.pass_context
def findings(ctx: click.Context, apply_findings: bool, category: str | None) -> None:
    """List research findings, or apply them to the rulebook."""
    conn = _get_conn(ctx)

    if apply_findings:
        unapplied = db.get_unapplied_findings(conn)
        if not unapplied:
            console.print("[dim]No unapplied findings.[/dim]")
            return
        applied = 0
        for f in unapplied:
            if f.confidence == "high":
                db.add_rule(conn, rule=f.finding, category=f.category, source=f.source_url or f.topic)
                db.mark_finding_applied(conn, f.id)
                applied += 1
                console.print(f"  [green]+[/green] {f.finding}")
        console.print(f"\n[green]Applied {applied} high-confidence findings to rulebook.[/green]")
        return

    all_findings = db.get_findings(conn, category=category)
    if not all_findings:
        console.print("[dim]No findings yet. Use 'scriptforge research' or 'scriptforge transcript' to gather data.[/dim]")
        return

    table = Table(title="Research Findings")
    table.add_column("ID", style="dim")
    table.add_column("Category")
    table.add_column("Finding")
    table.add_column("Confidence")
    table.add_column("Applied")
    for f in all_findings:
        applied_str = "[green]yes[/green]" if f.applied else "[dim]no[/dim]"
        table.add_row(str(f.id), f.category, f.finding[:80], f.confidence, applied_str)
    console.print(table)


# --- grade ---


@cli.command()
@click.argument("prompt_text")
@click.pass_context
def grade(ctx: click.Context, prompt_text: str) -> None:
    """Score a video prompt and show what's missing."""
    from scriptforge.researcher import grade_prompt
    conn = _get_conn(ctx)
    prompt_rules = db.get_prompt_rules(conn)

    if not prompt_rules:
        console.print("[dim]No prompt rules loaded. Run seed_defaults first.[/dim]")
        return

    score, missing, enhanced = grade_prompt(prompt_text, prompt_rules)

    color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
    console.print(f"\n[bold]Prompt Score:[/bold] [{color}]{score}/100[/{color}]\n")

    if missing:
        console.print("[bold]Missing elements:[/bold]")
        for m in missing:
            console.print(f"  [red]-[/red] {m}")

    if score < 70:
        console.print(f"\n[bold]Enhanced prompt:[/bold]\n{enhanced}")

    console.print()
