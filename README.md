# Personal AI OS

Your own assistant that remembers notes, keeps your to-dos and reminds you of
things, powered by Claude. Data stays on your computer in `data/aios.db`.

## Setup (once)

```bash
cd aios
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Get an API key at https://console.anthropic.com and set it:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
./run.sh
```

Then open http://localhost:8000

The first start downloads a small embedding model (~65 MB) into `data/models`.
To run with keyword search only, start with `AIOS_EMBEDDINGS=off ./run.sh`.

## Desktop app and voice

```bash
./make_app.sh
```

This builds `dist/Personal AI OS.app`; double-click it (or drag it to your Dock).
Put your key in a `.env` file in this folder (`ANTHROPIC_API_KEY=sk-ant-...`) so
the app can find it. The first time you talk, macOS asks for microphone access.

Press 🎤 or **Ctrl+Space** to start talking, and again to send. Speech is
transcribed on your Mac (Whisper `base.en`). 🔊 turns on read-aloud; Esc stops it.

## Connect Google (optional)

Open the **Connections** tab and follow the steps there. You create your own
OAuth client in Google Cloud (free), paste its JSON, and approve access on
Google's page. Your token stays in `data/google_token.json` on your computer.

## Project layout

| File | What it does |
|---|---|
| `app/db.py` | SQLite storage: notes (full-text search), tasks, reminders, chat |
| `app/memory.py` | Semantic memory: local embeddings, hybrid keyword + meaning search |
| `app/files.py` | Your files: folder watcher, PDF/Word/text reading, file search |
| `app/google_services.py` | Google sign-in, Calendar and Gmail (read + drafts, never sends) |
| `app/briefing.py` | Daily briefing: gathers your day, Claude writes it, morning scheduler |
| `app/voice.py` | Local speech-to-text (Whisper), mic recording, read-aloud |
| `desktop.py` | Desktop window (pywebview) + the bridge for mic and voice |
| `make_app.sh` | Builds the double-clickable Mac app |
| `app/tools.py` | The actions Claude can take (search/add notes, tasks, reminders) |
| `app/agent.py` | Talks to Claude and runs the tools it asks for |
| `app/server.py` | FastAPI web server and JSON API |
| `app/static/index.html` | The web interface |
| `tests/` | Tests for storage, tools, API and semantic search (no API key needed) |
| `PLAN.md` | Roadmap for the next milestones |

## Tests

```bash
.venv/bin/python -m pytest -q
```
