from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from scriptforge import db
from scriptforge.cli import cli
from scriptforge.engine import _build_topic_prompt, generate_topics


def _invoke(tmp_path: Path, args: list[str] | None = None) -> object:
    runner = CliRunner()
    return runner.invoke(cli, ["--db-path", str(tmp_path / "test.db")] + (args or []))


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "test.db")
    db.seed_defaults(connection)
    yield connection
    connection.close()


# --- DB CRUD ---


def test_save_and_get_generated_topics(conn: sqlite3.Connection) -> None:
    topics = [
        {"topic": "why your gut decides who you date", "template": "THE MYSTERY",
         "angle": "gut-brain axis in attraction", "why": "combines body + relationships"},
        {"topic": "your brain on rejection is identical to physical pain", "template": "THE MIRROR",
         "angle": "pain overlap in fMRI", "why": "universal experience"},
    ]
    db.save_generated_topics(conn, topics)
    retrieved = db.get_generated_topics(conn)
    assert len(retrieved) == 2
    assert retrieved[0]["topic"] == "why your gut decides who you date"
    assert retrieved[0]["template"] == "THE MYSTERY"
    assert retrieved[0]["used"] is False


def test_mark_topic_used(conn: sqlite3.Connection) -> None:
    db.save_generated_topics(conn, [
        {"topic": "test topic", "template": "THE MIRROR", "angle": "test", "why": "test"},
    ])
    topics = db.get_generated_topics(conn)
    assert topics[0]["used"] is False
    db.mark_topic_used(conn, topics[0]["id"])
    updated = db.get_generated_topics(conn)
    assert updated[0]["used"] is True


def test_get_unused_topics_only(conn: sqlite3.Connection) -> None:
    db.save_generated_topics(conn, [
        {"topic": "used topic", "template": "THE MIRROR", "angle": "a", "why": "a"},
        {"topic": "fresh topic", "template": "THE MYSTERY", "angle": "b", "why": "b"},
    ])
    topics = db.get_generated_topics(conn)
    db.mark_topic_used(conn, topics[0]["id"])
    unused = db.get_generated_topics(conn, unused_only=True)
    assert len(unused) == 1
    assert unused[0]["topic"] == "fresh topic"


# --- Prompt building ---


def test_topic_prompt_contains_templates(conn: sqlite3.Connection) -> None:
    templates = db.get_all_templates(conn)
    prompt = _build_topic_prompt(templates, [], [], [], {}, 5)
    assert "THE MIRROR" in prompt
    assert "THE MYSTERY" in prompt
    assert "THE ZOOM OUT" in prompt
    assert "psychology" in prompt.lower()
    assert "JSON" in prompt


def test_topic_prompt_includes_avoidance(conn: sqlite3.Connection) -> None:
    templates = db.get_all_templates(conn)
    existing = ["heartbreak neuroscience", "sleep deprivation"]
    past = ["gut instinct dating"]
    prompt = _build_topic_prompt(templates, existing, past, [], {}, 5)
    assert "heartbreak neuroscience" in prompt
    assert "gut instinct dating" in prompt


def test_topic_prompt_includes_findings(conn: sqlite3.Connection) -> None:
    templates = db.get_all_templates(conn)
    f = db.add_finding(conn, topic="love", finding="oxytocin drops after 2 years",
                        category="relationships")
    findings = db.get_findings(conn)
    prompt = _build_topic_prompt(templates, [], [], findings, {}, 5)
    assert "oxytocin" in prompt


def test_topic_prompt_includes_feedback(conn: sqlite3.Connection) -> None:
    templates = db.get_all_templates(conn)
    patterns = {"hit_notes": ["strong emotional opening"], "miss_notes": ["too abstract"]}
    prompt = _build_topic_prompt(templates, [], [], [], patterns, 5)
    assert "strong emotional opening" in prompt
    assert "too abstract" in prompt


# --- Generate topics (mocked Claude) ---


_MOCK_RESPONSE = json.dumps([
    {"topic": "why your brain replays rejection at 3 AM", "template": "THE MIRROR",
     "angle": "default mode network + rejection sensitivity", "why": "universal 3 AM experience"},
    {"topic": "the 7-second rule your body uses to decide attraction", "template": "THE TIMELINE",
     "angle": "biological sequence of attraction signals", "why": "specific timeframe hooks viewers"},
])


def _mock_claude_client():
    """Create a mock Anthropic client that returns topic JSON."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=_MOCK_RESPONSE)]
    mock_client.messages.create.return_value = mock_response
    return mock_client


@patch.dict("sys.modules", {"anthropic": MagicMock()})
def test_generate_topics_returns_correct_structure(conn: sqlite3.Connection) -> None:
    import sys
    mock_anthropic = sys.modules["anthropic"]
    mock_anthropic.Anthropic.return_value = _mock_claude_client()
    with patch("scriptforge.config.ANTHROPIC_API_KEY", "test-key"):
        topics = generate_topics(conn, count=2)
    assert len(topics) == 2
    assert topics[0]["topic"] == "why your brain replays rejection at 3 AM"
    assert topics[0]["template"] == "THE MIRROR"
    assert "angle" in topics[0]
    assert "why" in topics[0]


@patch.dict("sys.modules", {"anthropic": MagicMock()})
def test_generate_topics_saves_to_db(conn: sqlite3.Connection) -> None:
    import sys
    mock_anthropic = sys.modules["anthropic"]
    mock_anthropic.Anthropic.return_value = _mock_claude_client()
    with patch("scriptforge.config.ANTHROPIC_API_KEY", "test-key"):
        generate_topics(conn, count=2)
    saved = db.get_generated_topics(conn)
    assert len(saved) == 2


# --- CLI ---


@patch.dict("sys.modules", {"anthropic": MagicMock()})
def test_cli_topics_command(tmp_path: Path) -> None:
    import sys
    mock_anthropic = sys.modules["anthropic"]
    mock_anthropic.Anthropic.return_value = _mock_claude_client()
    with patch("scriptforge.config.ANTHROPIC_API_KEY", "test-key"):
        result = _invoke(tmp_path, ["topics", "--count", "2"])
    assert result.exit_code == 0
    assert "Topic Ideas" in result.output
    assert "rejection" in result.output.lower()
