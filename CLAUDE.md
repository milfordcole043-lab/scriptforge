# scriptforge

## What is this?
A personal knowledge system for writing better faceless video scripts.
Claude Code reads from and writes to this system to compound quality over time.

## Tech
- Python 3.12, Click, Rich, SQLite, pytest
- fal.ai (Flux Pro, Kling v3 Pro, VEED Fabric), ElevenLabs, FFmpeg, faster-whisper, pydub

## Structure
```
src/scriptforge/
  models.py        — dataclasses: Scene, Script, Character, Hook, Rule, Finding, PromptRule
  db.py            — SQLite schema, CRUD, seeded defaults, render cost logging
  engine.py        — prompt builders (labelled, temporal, connected), narrative arc, contextual rules
  pipeline.py      — narrator render pipeline (Flux Pro -> Kling -> captions -> voiceover -> assembly)
  pov_pipeline.py  — POV lip-sync pipeline (voiceover -> chunks -> Fabric lip-sync -> subtitles)
  researcher.py    — prompt grader (0-100), research findings, YouTube transcript analysis
  cli.py           — 20+ CLI commands
  config.py        — API keys, model IDs, costs, voice IDs, retry logic
tests/             — 131+ tests across 8 test files
```

## Two Pipelines
- **Narrator mode** (script.mode="narrator"): cinematic third-person, Kling v3 Pro video
- **POV mode** (script.mode="pov"): first-person lip-sync, VEED Fabric video, word-level subtitles

## Rules
- Keep it simple. No overengineering.
- Tests before implementation.
- Commit after every working layer.
- Type hints on all functions.
- The engine builds context/prompts; Claude does the actual writing.
- Always dry-run before spending credits.
- Create a character before writing scripts.
- Rate scripts after watching to improve the system.
