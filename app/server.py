"""Web server: JSON API + the browser UI."""

import json
from contextlib import asynccontextmanager
from urllib.parse import quote
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, briefing, db, files, google_services as google, memory, voice

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app):
    memory.warm_up()      # load the embedding model + index notes in the background
    files.start_watcher()  # scan connected folders now and every minute
    briefing.start_scheduler()  # write the morning briefing at the chosen time
    voice.warm_up()             # load the speech model so the first voice message is quick
    yield


app = FastAPI(title="Personal AI OS", lifespan=lifespan)
NO_KEY = "Claude API key missing or invalid. Set ANTHROPIC_API_KEY and restart the server."


# ---------- models ----------

class ChatIn(BaseModel):
    message: str

class NoteIn(BaseModel):
    title: str
    body: str = ""
    tags: str = ""

class NotePatch(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: str | None = None

class TaskIn(BaseModel):
    title: str
    due: str | None = None
    priority: str = "normal"

class TaskPatch(BaseModel):
    done: bool

class SourceIn(BaseModel):
    path: str

class GoogleClientIn(BaseModel):
    client_json: str

class BriefingSettingsIn(BaseModel):
    enabled: bool | None = None
    time: str | None = None

class ReminderIn(BaseModel):
    message: str
    remind_at: str


# ---------- chat ----------

@app.post("/api/chat")
async def chat(body: ChatIn):
    text = body.message.strip()
    if not text:
        raise HTTPException(400, "Empty message")
    try:
        return await run_in_threadpool(agent.chat, text)
    except anthropic.AuthenticationError:
        raise HTTPException(401, NO_KEY)
    except anthropic.RateLimitError:
        raise HTTPException(429, "Rate limited by the Claude API. Wait a moment and try again.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Claude API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(503, "Couldn't reach the Claude API. Check your internet connection.")
    except anthropic.AnthropicError as e:
        raise HTTPException(500, f"Claude client error: {e}")
    except TypeError as e:
        # The SDK raises TypeError when no credentials are configured at all.
        if "authentication method" in str(e):
            raise HTTPException(401, NO_KEY)
        raise


@app.get("/api/memory/status")
def memory_status():
    return {"semantic": memory.enabled(), "model": memory.MODEL_NAME if memory.enabled() else None}


@app.post("/api/memory/reindex")
def memory_reindex():
    return {"reindexed": memory.backfill()}


@app.get("/api/chat/history")
def chat_history():
    return db.recent_chat(100)


@app.delete("/api/chat/history")
def clear_history():
    db.clear_chat()
    return {"ok": True}


# ---------- notes ----------

@app.get("/api/notes")
def notes(q: str = ""):
    return memory.search(q, 50) if q.strip() else db.list_notes()

@app.post("/api/notes")
def create_note(n: NoteIn):
    return memory.save_note(n.title, n.body, n.tags)

@app.patch("/api/notes/{note_id}")
def edit_note(note_id: int, n: NotePatch):
    note = memory.edit_note(note_id, n.title, n.body, n.tags)
    if not note:
        raise HTTPException(404, "Note not found")
    return note

@app.delete("/api/notes/{note_id}")
def remove_note(note_id: int):
    if not memory.remove_note(note_id):
        raise HTTPException(404, "Note not found")
    return {"ok": True}


# ---------- tasks ----------

@app.get("/api/tasks")
def tasks(include_done: bool = True):
    return db.list_tasks(include_done)

@app.post("/api/tasks")
def create_task(t: TaskIn):
    return db.add_task(t.title, t.due, t.priority)

@app.patch("/api/tasks/{task_id}")
def edit_task(task_id: int, t: TaskPatch):
    task = db.set_task_done(task_id, t.done)
    if not task:
        raise HTTPException(404, "Task not found")
    return task

@app.delete("/api/tasks/{task_id}")
def remove_task(task_id: int):
    if not db.delete_task(task_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}


# ---------- reminders ----------

@app.get("/api/reminders")
def reminders():
    return db.list_reminders()

@app.post("/api/reminders")
def create_reminder(r: ReminderIn):
    from .tools import _valid_time
    try:
        when = _valid_time(r.remind_at)
    except ValueError:
        raise HTTPException(400, "Use the format YYYY-MM-DD HH:MM")
    return db.add_reminder(r.message, when)

@app.get("/api/reminders/due")
def due_reminders():
    """The UI polls this; each due reminder is returned once."""
    return db.pop_due_reminders()

@app.delete("/api/reminders/{reminder_id}")
def remove_reminder(reminder_id: int):
    if not db.delete_reminder(reminder_id):
        raise HTTPException(404, "Reminder not found")
    return {"ok": True}


# ---------- files ----------

@app.get("/api/sources")
def sources():
    return {"sources": files.list_sources(), "status": files.status}

@app.post("/api/sources")
def create_source(s: SourceIn):
    try:
        return files.add_source(s.path)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.delete("/api/sources/{source_id}")
def remove_source(source_id: int):
    if not files.remove_source(source_id):
        raise HTTPException(404, "Folder not found")
    return {"ok": True}

@app.post("/api/sources/scan")
def scan_now():
    files.wake()
    return {"ok": True}

@app.get("/api/files")
def list_files(source_id: int | None = None):
    return files.list_files(source_id)

@app.get("/api/files/search")
def search_files(q: str):
    return files.search(q, 20)

@app.get("/api/files/{file_id}/raw")
def raw_file(file_id: int):
    """Open an indexed file in the browser. Only files in the index can be served."""
    f = files.get_file(file_id)
    if not f or not Path(f["path"]).is_file():
        raise HTTPException(404, "File not found")
    media = {".pdf": "application/pdf", ".md": "text/plain; charset=utf-8", ".markdown": "text/plain; charset=utf-8",
             ".txt": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8", ".rst": "text/plain; charset=utf-8",
             ".org": "text/plain; charset=utf-8"}.get(f["ext"])
    return FileResponse(f["path"], media_type=media, filename=None if media else f["name"],
                        content_disposition_type="inline")


# ---------- Google (calendar + email) ----------

@app.get("/api/google/status")
def google_status():
    return google.status()

@app.post("/api/google/client")
def google_client(c: GoogleClientIn):
    try:
        google.save_client_config(c.client_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "That isn't valid JSON. Paste the whole contents of the downloaded file.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return google.status()

@app.get("/api/google/connect")
def google_connect():
    try:
        return RedirectResponse(google.begin_auth())
    except google.NotConnected as e:
        raise HTTPException(400, str(e))

@app.get("/api/google/callback")
def google_callback(state: str = "", code: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse("/?google=" + quote(error or "cancelled") + "#connections")
    try:
        google.finish_auth(state, code)
    except Exception as e:
        return RedirectResponse("/?google=" + quote(f"error: {e}"[:200]) + "#connections")
    return RedirectResponse("/?google=connected#connections")

@app.post("/api/google/disconnect")
def google_disconnect():
    google.disconnect()
    return google.status()

@app.get("/api/calendar")
def calendar(days: int = 7):
    try:
        return google.list_events(max(1, min(days, 60)))
    except google.NotConnected as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"Google Calendar error: {e}")


# ---------- daily briefing ----------

@app.get("/api/briefing")
def get_briefing(day: str | None = None):
    return {"briefing": briefing.get(day), "settings": briefing.get_settings()}

@app.post("/api/briefing/generate")
async def make_briefing():
    return await run_in_threadpool(briefing.generate)

@app.post("/api/briefing/seen")
def briefing_seen():
    briefing.mark_seen()
    return {"ok": True}

@app.put("/api/briefing/settings")
def briefing_settings(s: BriefingSettingsIn):
    try:
        return briefing.save_settings(s.enabled, s.time)
    except ValueError:
        raise HTTPException(400, "Use a time like 07:30")

@app.get("/api/briefing/history")
def briefing_history():
    return briefing.history()


# ---------- voice ----------

MAX_AUDIO_BYTES = 25 * 1024 * 1024

@app.get("/api/voice/status")
def voice_status():
    return {"ready": voice.ready(), "model": voice.MODEL_NAME}

@app.post("/api/voice/transcribe")
async def transcribe(request: Request):
    """Body is the raw audio clip (webm/ogg/wav/m4a) recorded by the browser."""
    data = await request.body()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too long")
    try:
        text = await run_in_threadpool(voice.transcribe, data)
    except Exception:
        raise HTTPException(400, "Couldn't understand that audio. Try recording again.")
    return {"text": text}


# ---------- UI ----------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

app.mount("/static", StaticFiles(directory=STATIC), name="static")
