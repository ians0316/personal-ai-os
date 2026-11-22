# Personal AI OS — Project Plan

A private assistant that remembers your notes, tasks and reminders, answers
questions about them, and acts for you. Everything is stored locally on your
machine in one SQLite file; only the conversation goes to the Claude API.

## Architecture

```
 Browser UI (app/static)          FastAPI server (app/server.py)
 ┌──────────────────────┐  HTTP   ┌───────────────────────────────┐
 │ Chat │ Notes │ Tasks │ ──────▶ │ /api/chat  → agent.py         │
 │ Reminders + alerts   │         │ /api/notes, /api/tasks, ...   │
 └──────────────────────┘         └──────────────┬────────────────┘
                                                 │
                         ┌───────────────────────┴──────────┐
                         │ agent.py: Claude (claude-opus-5-5)│
                         │ + tool runner + tools.py          │
                         └───────────────────────┬──────────┘
                                                 │
              memory.py: local embeddings + hybrid search
                                   db.py: SQLite (data/aios.db)
                                   notes (full-text search), note vectors,
                                   tasks, reminders, chat history
```

## Milestones

- [x] **M1 — Core brain**
  Notes with full-text search, tasks, reminders with browser alerts, and a
  chat where Claude can search/add/complete these through tools.
- [x] **M2 — Semantic memory**
  A local embedding model (BAAI/bge-small-en-v1.5 via fastembed, runs on your
  computer) turns note chunks into vectors stored in SQLite. Search merges
  keyword and meaning results (Reciprocal Rank Fusion). Each chat message
  automatically brings the most related notes along for Claude, and Claude
  updates existing notes instead of duplicating them.
  Later: switch to sqlite-vec once you have tens of thousands of notes.
- [x] **M3 — Your files**
  Connect folders in the Files tab. PDFs (page by page), Word, Markdown and
  text files are indexed on your computer and re-checked every minute
  (new, changed and deleted files). Claude searches them with `search_files`,
  reads whole files or pages with `read_file`, and cites sources like
  [Biology notes.pdf p.2]; the chat shows clickable source links.
  Claude can only read files that are in the index.
  Later: OCR for scanned PDFs, more file types (slides, spreadsheets).
- [x] **M4 — Calendar and email**
  Connect Google in the Connections tab (one-time Google Cloud setup, steps
  shown in the app). Claude can read your calendar and Gmail, answer "what
  did I miss?", and save replies as Gmail **drafts**. The app never asks for
  permission to send mail or change your calendar. Email content is marked
  as untrusted so instructions hidden in emails are not followed.
  Later: Outlook/iCal support, creating calendar events after you confirm.
- [x] **M5 — Daily briefing**
  A new Today tab. Every morning at your chosen time (default 07:30) the app
  gathers today's calendar, overdue / due-today / upcoming tasks, today's
  reminders and recent unread email, and Claude writes a short briefing
  (low effort, so it's quick and cheap). Without an API key, or if Claude
  can't be reached, a plain version is written instead. A toast and a dot on
  the Today tab tell you when it's ready. One briefing is saved per day.
- [x] **M6 — Desktop app + voice (this build)**
  `./make_app.sh` builds "Personal AI OS.app" (a native Mac window via
  pywebview that starts the server itself). Press 🎤 or Ctrl+Space to talk:
  speech is turned into text on your Mac by Whisper (base.en, ~140 MB, offline)
  and sent as a chat message. 🔊 reads replies aloud (Mac voice in the app,
  browser voice in a browser). In the app, Python records the mic because the
  window can't give web pages microphone access.
  Later: a global hotkey that works from any app (needs Accessibility
  permission), menu-bar icon, wake word.
- [ ] **M7 — React front end**
  Move the UI to React + Vite once it outgrows one file.

## Running it

See README.md.
