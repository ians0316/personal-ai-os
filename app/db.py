"""Local storage: one SQLite file holds notes, tasks, reminders and chat history."""

import os
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("AIOS_DB", Path(__file__).resolve().parent.parent / "data" / "aios.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, body, tags, content='notes', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, body, tags) VALUES (new.id, new.title, new.body, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, body, tags) VALUES ('delete', old.id, old.title, old.body, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, body, tags) VALUES ('delete', old.id, old.title, old.body, old.tags);
    INSERT INTO notes_fts(rowid, title, body, tags) VALUES (new.id, new.title, new.body, new.tags);
END;

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    due TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    fired INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


_conn: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
        _conn.executescript(SCHEMA)
    return _conn


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _exec(sql: str, params=()) -> sqlite3.Cursor:
    with _lock:
        cur = db().execute(sql, params)
        db().commit()
        return cur


def _query(sql: str, params=()) -> list[dict]:
    with _lock:
        return _rows(db().execute(sql, params))


# ---------- notes ----------

def add_note(title: str, body: str = "", tags: str = "") -> dict:
    t = now()
    cur = _exec(
        "INSERT INTO notes (title, body, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (title, body, tags, t, t),
    )
    return get_note(cur.lastrowid)


def get_note(note_id: int) -> dict | None:
    rows = _query("SELECT * FROM notes WHERE id = ?", (note_id,))
    return rows[0] if rows else None


def update_note(note_id: int, title: str | None = None, body: str | None = None, tags: str | None = None) -> dict | None:
    note = get_note(note_id)
    if not note:
        return None
    _exec(
        "UPDATE notes SET title = ?, body = ?, tags = ?, updated_at = ? WHERE id = ?",
        (title if title is not None else note["title"],
         body if body is not None else note["body"],
         tags if tags is not None else note["tags"],
         now(), note_id),
    )
    return get_note(note_id)


def delete_note(note_id: int) -> bool:
    return _exec("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount > 0


def list_notes(limit: int = 100) -> list[dict]:
    return _query("SELECT * FROM notes ORDER BY updated_at DESC LIMIT ?", (limit,))


STOPWORDS = set("""a an and are as at be by can could did do does for from had has have how i i'm if in
into is it its me my of on or our should so than that the their them then there these they this to
was we were what when where which who whom why will with would you your like get got just about any
all am been being some""".split())


def search_notes(query: str, limit: int = 10) -> list[dict]:
    """Full-text search. Filler words are skipped; the rest are OR-ed so partial matches still rank."""
    words = [w for w in re.findall(r"\w+", query) if w.lower() not in STOPWORDS] or re.findall(r"\w+", query)
    if not words:
        return list_notes(limit)
    match = " OR ".join(f'"{w}"*' for w in words)
    return _query(
        """SELECT notes.*, snippet(notes_fts, 1, '[', ']', '…', 12) AS snippet
           FROM notes_fts JOIN notes ON notes.id = notes_fts.rowid
           WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?""",
        (match, limit),
    )


# ---------- tasks ----------

def add_task(title: str, due: str | None = None, priority: str = "normal") -> dict:
    cur = _exec(
        "INSERT INTO tasks (title, due, priority, created_at) VALUES (?, ?, ?, ?)",
        (title, due or None, priority, now()),
    )
    return _query("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,))[0]


def list_tasks(include_done: bool = False) -> list[dict]:
    where = "" if include_done else "WHERE done = 0"
    return _query(
        f"""SELECT * FROM tasks {where}
            ORDER BY done, due IS NULL, due,
                     CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, id"""
    )


def set_task_done(task_id: int, done: bool = True) -> dict | None:
    _exec(
        "UPDATE tasks SET done = ?, completed_at = ? WHERE id = ?",
        (int(done), now() if done else None, task_id),
    )
    rows = _query("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return rows[0] if rows else None


def delete_task(task_id: int) -> bool:
    return _exec("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount > 0


# ---------- reminders ----------

def add_reminder(message: str, remind_at: str) -> dict:
    cur = _exec(
        "INSERT INTO reminders (message, remind_at, created_at) VALUES (?, ?, ?)",
        (message, remind_at, now()),
    )
    return _query("SELECT * FROM reminders WHERE id = ?", (cur.lastrowid,))[0]


def list_reminders(include_fired: bool = False) -> list[dict]:
    where = "" if include_fired else "WHERE fired = 0"
    return _query(f"SELECT * FROM reminders {where} ORDER BY remind_at")


def pop_due_reminders() -> list[dict]:
    """Return reminders whose time has come and mark them fired."""
    with _lock:
        rows = _rows(db().execute(
            "SELECT * FROM reminders WHERE fired = 0 AND remind_at <= ? ORDER BY remind_at", (now(),)
        ))
        if rows:
            db().executemany("UPDATE reminders SET fired = 1 WHERE id = ?", [(r["id"],) for r in rows])
            db().commit()
        return rows


def delete_reminder(reminder_id: int) -> bool:
    return _exec("DELETE FROM reminders WHERE id = ?", (reminder_id,)).rowcount > 0


# ---------- chat history ----------

def add_chat_message(role: str, content: str) -> None:
    _exec("INSERT INTO chat_messages (role, content, created_at) VALUES (?, ?, ?)", (role, content, now()))


def recent_chat(limit: int = 30) -> list[dict]:
    rows = _query("SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?", (limit,))
    return list(reversed(rows))


def clear_chat() -> None:
    _exec("DELETE FROM chat_messages")
