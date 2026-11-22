## Highlights
- **First release of Personal AI OS.** A private assistant powered by Claude that runs on your own Mac: chat, notes, tasks, reminders, your documents, Google Calendar and Gmail, a daily briefing, and voice.
- **Desktop app.** `./make_app.sh` builds a double-clickable "Personal AI OS.app".
- **Talk to it.** Press 🎤 or Ctrl+Space. Your speech is turned into text on your Mac by Whisper, offline.

## What's included
- **Chat** with Claude, which can search and update your notes, tasks and reminders.
- **Semantic memory.** Notes are found by meaning, not just exact words (local embeddings).
- **Your files.** Connect folders of PDFs, Word, Markdown and text files; answers cite the file and page.
- **Calendar and email.** Read Google Calendar and Gmail, and save replies as Gmail **drafts**. It can never send email or change your calendar.
- **Daily briefing** every morning on the Today tab, written by Claude (a plain version if there's no API key).
- **Voice** input and read-aloud replies.

## How to install
1. Download the zip below and unzip it.
2. In Terminal, in that folder: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. Put your Claude API key in a `.env` file: `ANTHROPIC_API_KEY=sk-ant-...`
4. Run `./run.sh` and open http://localhost:8000, or build the desktop app with `./make_app.sh`.

See [docs/Install.md](https://github.com/ians0316/personal-ai-os/blob/main/docs/Install.md) for details.

> ⚠️ Your notes, tasks and settings live in the `data/` folder. When you update, copy the new files over your old folder and keep `data/`, or you'll start empty.
