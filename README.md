# Personal AI OS

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

Personal AI OS is a private assistant powered by Claude that runs on your own Mac. It remembers your notes, keeps your to-dos and reminders, searches your documents, reads your calendar and email, writes you a briefing every morning, and you can talk to it.

📖 **Full docs are in [docs/](docs/Home.md):** install and update, every feature, privacy, FAQ, troubleshooting, and the [Roadmap](docs/Roadmap.md).

> [!IMPORTANT]
> **Personal AI OS is a personal project.** It is not made or supported by Anthropic or Google.
> AI can make mistakes, so double-check important dates, facts and drafts before you rely on them.

> 🔒 **Private by design:** your notes, files, tasks and sign-ins stay on your computer in the `data/` folder. Only what Claude needs for a reply is sent to the Claude API. It can draft email but **never sends it**.

## How it works

Personal AI OS runs a small server on your Mac (`localhost:8000`) and shows it in a desktop window or your browser:

1. **Tell it things:** "Remember that Mia's birthday is 14 March", "Remind me to call the dentist at 9".
2. **Ask it things:** "When should I buy Mia a present?" finds the note by meaning, even with different words.
3. **Connect your stuff:** folders of documents, plus Google Calendar and Gmail.
4. **Start your day:** the Today tab has a fresh briefing every morning.

## Setup

```bash
git clone https://github.com/ians0316/personal-ai-os.git
cd personal-ai-os
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

Then either:

- **Desktop app:** `./make_app.sh`, then double-click `dist/Personal AI OS.app` (drag it to your Dock).
- **Browser:** `set -a; . ./.env; set +a; ./run.sh`, then open http://localhost:8000.

Get an API key at [console.anthropic.com](https://console.anthropic.com). The first start downloads a search model (~65 MB) and, the first time you talk, a speech model (~140 MB). Details: [docs/Install.md](docs/Install.md).

Keep the `data/` folder when you update: it holds everything you've saved.

## Features

| Tab | What it does |
|---|---|
| **Today** | A daily briefing at 07:30 (you choose the time): schedule, tasks needing attention, email worth a look, what's coming up |
| **Chat** | Talk or type to Claude. It searches and updates your notes, tasks, reminders, files, calendar and email for you |
| **Notes** | Notes with tags; search understands meaning ("teeth" finds your dentist note) |
| **Tasks** | To-dos with due dates and priorities; overdue ones turn red |
| **Reminders** | Pop-up alerts and desktop notifications at the right time |
| **Files** | Connect folders of PDF, Word, Markdown and text files; answers cite the file and page |
| **Connections** | Connect Google Calendar and Gmail (read, plus drafts only) |

- 🎤 **Voice:** press 🎤 or **Ctrl+Space** to talk. Speech becomes text on your Mac with Whisper, offline.
- 🔊 **Read aloud:** turn it on to hear replies; Esc stops it.

More in [docs/Features.md](docs/Features.md).

## Files

| File | What it does |
|---|---|
| `app/agent.py` | Talks to Claude (`claude-opus-5-5`) and runs the tools it asks for |
| `app/tools.py` | The actions Claude can take: notes, tasks, reminders, files, calendar, email |
| `app/db.py` | SQLite storage: notes (full-text search), tasks, reminders, chat |
| `app/memory.py` | Semantic memory: local embeddings, hybrid keyword + meaning search |
| `app/files.py` | Your files: folder watcher, PDF/Word/text reading, file search |
| `app/google_services.py` | Google sign-in, Calendar and Gmail (read + drafts, never sends) |
| `app/briefing.py` | Daily briefing: gathers your day, Claude writes it, morning scheduler |
| `app/voice.py` | Local speech-to-text (Whisper), mic recording, read-aloud |
| `app/server.py` | FastAPI web server and JSON API |
| `app/static/index.html` | The interface (plain HTML, CSS and JavaScript) |
| `desktop.py` | Desktop window (pywebview) and the bridge for mic and voice |
| `make_app.sh` / `run.sh` | Build the Mac app / start the server |
| `tests/` | 53 tests; no API key, Google account or network needed |
| `docs/` | Documentation |
| `VERSION` | Current version; raising it on `main` makes a new release |

## Documentation

- [Install and update](docs/Install.md)
- [Features](docs/Features.md)
- [Privacy](docs/Privacy.md)
- [FAQ](docs/FAQ.md)
- [Troubleshooting](docs/Troubleshooting.md)
- [Roadmap](docs/Roadmap.md)

## Report a bug

Open an [issue](https://github.com/ians0316/personal-ai-os/issues) with what you did, what you expected, and what happened. Add a screenshot or the end of `data/desktop.log` if you can, and hide anything private.

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) and the [Code of conduct](.github/CODE_OF_CONDUCT.md).

## Status

Version **0.6.0**: milestones 1–6 done. Next up: a React interface (see the [Roadmap](docs/Roadmap.md)).

## License

[Apache License 2.0](LICENSE)
