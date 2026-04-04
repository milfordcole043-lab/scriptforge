# ScriptForge

A personal knowledge system that writes better faceless video scripts every time. Claude Code reads from and writes to this system — the rulebook, research findings, and feedback compound quality over time.

## Architecture

```
src/scriptforge/
  models.py      — Scene, Script, Character, Hook, Rule, Finding, PromptRule
  db.py          — SQLite schema, CRUD, seeded defaults (21 rules, 18 prompt rules, 8 voice profiles)
  engine.py      — prompt builders, narrative arc, temporal flow, light progression, contextual rules
  pipeline.py    — narrator render pipeline (Flux Pro + Kling v3 Pro + ElevenLabs + FFmpeg)
  pov_pipeline.py — POV lip-sync pipeline (ElevenLabs + pydub + Flux Pro + VEED Fabric + Whisper + FFmpeg)
  researcher.py  — prompt grader (0-100), research finding extraction, YouTube transcript analysis
  cli.py         — 20+ Click commands with Rich output
  config.py      — API keys, model IDs, costs, voice IDs, retry logic
```

## Two Render Pipelines

**Narrator mode** — cinematic third-person storytelling:
1. Character reference portrait (Flux Pro, cached)
2. Scene images with labelled prompts (Flux Pro, 9:16)
3. Video clips with negative prompts (Kling v3 Pro, 3-15s)
4. Caption burning (FFmpeg drawtext)
5. Voiceover (ElevenLabs, Brian voice)
6. Assembly (FFmpeg concat)

**POV mode** — first-person lip-sync confessional:
1. Voiceover first (ElevenLabs, Lily voice)
2. Audio chunking by scene (pydub)
3. POV reference portrait (Flux Pro, selfie angle, teeth visible)
4. Lip-sync clips chained via last-frame extraction (VEED Fabric 1.0)
5. Word-level subtitles (faster-whisper, ASS format)
6. Assembly (FFmpeg concat + voiceover + subtitles)

## Narrative System

Every script follows a 4-beat arc:
- **Hook** (2-3s) — personal moment, works without sound
- **Tension** (8-12s) — deepen the feeling, one emotion
- **Revelation** (10-15s) — science/insight as a twist
- **Resolution** (5-7s) — reframe, not advice

Duration: 25-50 seconds. Pacing: 130 wpm. Captions on every scene.

## CLI Commands

| Command | Description |
|---------|-------------|
| `scriptforge write "topic"` | Assemble context + generation prompt |
| `scriptforge view <id>` | View full script with all scene fields |
| `scriptforge list` | List all scripts with ratings |
| `scriptforge rate <id> hit/miss/rewrite "notes"` | Rate and log feedback |
| `scriptforge rewrite <id>` | Generate rewrite prompt from feedback |
| `scriptforge render <id>` | Full render pipeline |
| `scriptforge render <id> --dry-run` | Preview render plan + cost estimate |
| `scriptforge character "name" --age --gender --appearance --clothing` | Create character profile |
| `scriptforge characters` | List all characters |
| `scriptforge hooks` | Top-rated hooks |
| `scriptforge rules` | Active rulebook (--add to create) |
| `scriptforge search "query"` | Search scripts |
| `scriptforge export <id>` | Export to .txt |
| `scriptforge stats` | Dashboard |
| `scriptforge analyze` | Feedback pattern analysis |
| `scriptforge research "topic"` | Register research topic |
| `scriptforge transcript <url>` | Analyze YouTube transcript |
| `scriptforge findings` | List research findings (--apply for rulebook) |
| `scriptforge grade "prompt"` | Score a video prompt 0-100 |

## Tech Stack

- Python 3.12, Click, Rich, SQLite, pytest
- fal.ai (Flux Pro, Kling v3 Pro, VEED Fabric 1.0)
- ElevenLabs (v3 TTS)
- FFmpeg (assembly, captions, frame extraction)
- faster-whisper (word-level subtitles)
- pydub (audio splitting)

## Installation

```bash
git clone https://github.com/milfordcole043-lab/scriptforge.git
cd scriptforge
pip install -e .
```

Add API keys to `.env`:
```
ELEVENLABS_API_KEY=your_key
FAL_KEY=your_key
```

## Running Tests

```bash
python -m pytest tests/ -v
```

```
131 passed
```

## License

MIT
