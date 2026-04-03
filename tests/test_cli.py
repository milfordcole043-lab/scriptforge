from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from scriptforge.cli import cli


def _invoke(tmp_path: Path, args: list[str] | None = None) -> object:
    runner = CliRunner()
    return runner.invoke(cli, ["--db-path", str(tmp_path / "test.db")] + (args or []))


# --- write ---


def test_write_no_generate(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["write", "AI basics", "--no-generate"])
    assert result.exit_code == 0
    assert "Context assembled" in result.output
    assert "AI basics" in result.output


def test_write_with_style(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["write", "Coffee history", "--style", "story", "--no-generate"])
    assert result.exit_code == 0
    assert "story" in result.output.lower()


def test_write_shows_voice_profile(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["write", "Test topic", "--no-generate"])
    assert result.exit_code == 0
    # seed_defaults runs on connect, so voice profile should show
    assert "tone" in result.output.lower()


def test_write_shows_seeded_rules(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["write", "Test topic", "--no-generate"])
    assert result.exit_code == 0
    assert "Rulebook" in result.output
    assert "10 rules" in result.output


# --- view ---


def test_view_not_found(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["view", "999"])
    assert "not found" in result.output.lower()


# --- list ---


def test_list_empty(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["list"])
    assert result.exit_code == 0
    assert "No scripts" in result.output


# --- rate ---


def test_rate_not_found(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["rate", "999", "hit", "good stuff"])
    assert "not found" in result.output.lower()


# --- hooks ---


def test_hooks_empty(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["hooks"])
    assert result.exit_code == 0
    assert "No hooks" in result.output


# --- rules ---


def test_rules_shows_seeded(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["rules"])
    assert result.exit_code == 0
    # Should have seeded 10 rules
    assert "Rulebook" in result.output


def test_rules_add_and_list(tmp_path: Path) -> None:
    _invoke(tmp_path, ["rules", "--add", "Always open with a question", "--category", "hook"])
    result = _invoke(tmp_path, ["rules"])
    assert "Always open with a question" in result.output


# --- search ---


def test_search_empty(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["search", "nonexistent"])
    assert result.exit_code == 0
    assert "No results" in result.output


# --- stats ---


def test_stats_empty(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["stats"])
    assert result.exit_code == 0
    assert "No scripts" in result.output or "0" in result.output


# --- analyze ---


def test_analyze_not_enough(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["analyze"])
    assert result.exit_code == 0
    assert "Not enough" in result.output or "no feedback" in result.output.lower()
