from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from scriptforge import db
from scriptforge.engine import analyze_feedback_patterns, build_rewrite_context, build_write_context
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
@click.option("--no-generate", is_flag=True, hidden=True, help="Show context only (for testing).")
@click.pass_context
def write(ctx: click.Context, topic: str, style: str, duration: int, no_generate: bool) -> None:
    """Write a new script. Assembles context from rulebook, hooks, and feedback."""
    conn = _get_conn(ctx)
    context = build_write_context(conn, topic=topic, style=style, duration_target=duration)
    wpm = 130
    word_target = duration * wpm // 60

    console.print(Panel(f"[bold]Topic:[/bold] {topic}\n[bold]Style:[/bold] {style}\n"
                        f"[bold]Duration:[/bold] {duration}s (~{word_target} words at {wpm} wpm)\n"
                        f"[bold]Arc:[/bold] hook -> tension -> revelation -> resolution",
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

    if script.scenes:
        table = Table(title="Scenes")
        table.add_column("#", style="dim")
        table.add_column("Beat")
        table.add_column("Caption")
        table.add_column("Voiceover")
        table.add_column("Camera")
        table.add_column("Emotion")
        table.add_column("Dur", justify="right")
        for i, s in enumerate(script.scenes, 1):
            table.add_row(str(i), s.beat, s.caption, s.voiceover, s.camera, s.emotion, f"{s.duration_seconds}s")
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
    """Rate a script and log feedback."""
    conn = _get_conn(ctx)
    if db.rate_script(conn, script_id, rating, notes):
        color = "green" if rating == "hit" else "red" if rating == "miss" else "yellow"
        console.print(f"[{color}]Rated #{script_id} as {rating}.[/{color}] Feedback logged.")
    else:
        console.print(f"[red]Script #{script_id} not found.[/red]")


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
        content += f"VO: {s.voiceover}\n"
        content += f"VISUAL: {s.visual}\n"
        content += f"CAMERA: {s.camera} | MOTION: {s.motion} | SOUND: {s.sound}\n"
        content += f"EMOTION: {s.emotion}\n"
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
