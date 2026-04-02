# scriptforge

## What is this?
A personal knowledge system for writing better faceless video scripts.
Claude Code reads from and writes to this system to compound quality over time.

## Tech
- Python 3.12, Click, Rich, SQLite, pytest

## Structure
src/scriptforge/ — main code (models, db, engine, cli)
tests/ — pytest tests

## Rules
- Keep it simple. No overengineering.
- Tests before implementation.
- Commit after every working layer.
- Type hints on all functions.
- The engine builds context/prompts; Claude does the actual writing.
