"""Your files: index folders you choose so the assistant can search and cite them.

You add folders ("sources"). A background thread scans them every minute,
reads supported files (Markdown, text, PDF, Word), splits them into chunks,
and stores each chunk for keyword search (SQLite FTS) and meaning search
(the same local embedding model as notes). Changed files are re-indexed and
deleted files are dropped. Claude can only read files that are in the index.
"""

import contextvars
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from . import db, memory

log = logging.getLogger("aios.files")

TEXT_EXTS = {".md", ".markdown", ".txt", ".rst", ".org", ".csv"}
SUPPORTED = TEXT_EXTS | {".pdf", ".docx"}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "site-packages", "Library"}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_SOURCE = 5000
SCAN_INTERVAL = 60  # seconds

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    chunks INTEGER NOT NULL DEFAULT 0,
    pages INTEGER,
    indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS file_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    page INTEGER,
    text TEXT NOT NULL,
    vector BLOB,
    model TEXT
);
CREATE INDEX IF NOT EXISTS file_chunks_file ON file_chunks(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks_fts USING fts5(text, content='file_chunks', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS file_chunks_ai AFTER INSERT ON file_chunks BEGIN
    INSERT INTO file_chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS file_chunks_ad AFTER DELETE ON file_chunks BEGIN
    INSERT INTO file_chunks_fts(file_chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""

_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if not _schema_ready:
        with db._lock:
            db.db().executescript(SCHEMA)
        _schema_ready = True


_cache = memory.VectorCache(
    """SELECT c.id, c.file_id, c.page, c.text, c.vector, f.name, f.path
       FROM file_chunks c JOIN files f ON f.id = c.file_id WHERE c.vector IS NOT NULL"""
)


# ---------- reading files ----------

def extract(path: Path) -> list[tuple[int | None, str]]:
    """Return (page_number_or_None, text) pieces for a file."""
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return [(None, path.read_text(encoding="utf-8", errors="replace"))]
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return [(i + 1, (page.extract_text() or "")) for i, page in enumerate(reader.pages)]
    if ext == ".docx":
        import docx
        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return [(None, "\n".join(parts))]
    raise ValueError(f"Unsupported file type {ext}")


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------- indexing ----------

def index_file(source_id: int, path: Path) -> dict:
    """(Re)index one file. Never raises: failures are stored on the file row."""
    _ensure_schema()
    st = path.stat()
    status, error, rows, pages = "indexed", None, [], None
    try:
        if st.st_size > MAX_FILE_BYTES:
            raise ValueError(f"File is larger than {MAX_FILE_BYTES // 1024 // 1024} MB")
        pieces = extract(path)
        if path.suffix.lower() == ".pdf":
            pages = len(pieces)
        header = path.stem.replace("_", " ").replace("-", " ")
        for page, text in pieces:
            for c in memory.chunk(_clean(text)):
                rows.append((page, c))
        if not rows:
            status, error = "empty", "No readable text (scanned PDFs need OCR, coming later)"
    except Exception as e:  # corrupt PDF, permission denied, ...
        status, error, rows = "error", str(e)[:300], []

    vectors = []
    if rows and memory.enabled():
        # Prefix the file name so "my CV" can match a file called cv.pdf.
        vectors = memory._embedder.embed_docs([f"{header}\n{text}" for _, text in rows])
    model = memory._embedder.model_name if vectors is not None and len(vectors) else None

    with db._lock:
        conn = db.db()
        old = conn.execute("SELECT id FROM files WHERE path = ?", (str(path),)).fetchone()
        if old:
            conn.execute("DELETE FROM file_chunks WHERE file_id = ?", (old["id"],))
            conn.execute(
                """UPDATE files SET source_id=?, size=?, mtime=?, status=?, error=?, chunks=?, pages=?, indexed_at=?
                   WHERE id=?""",
                (source_id, st.st_size, st.st_mtime, status, error, len(rows), pages, db.now(), old["id"]))
            file_id = old["id"]
        else:
            cur = conn.execute(
                """INSERT INTO files (source_id, path, name, ext, size, mtime, status, error, chunks, pages, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (source_id, str(path), path.name, path.suffix.lower(), st.st_size, st.st_mtime,
                 status, error, len(rows), pages, db.now()))
            file_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO file_chunks (file_id, chunk_index, page, text, vector, model) VALUES (?, ?, ?, ?, ?, ?)",
            [(file_id, i, page, text,
              vectors[i].astype(np.float32).tobytes() if len(vectors) else None, model)
             for i, (page, text) in enumerate(rows)])
        conn.commit()
    _cache.invalidate()
    return {"id": file_id, "status": status, "chunks": len(rows)}


def _forget_file(file_id: int) -> None:
    with db._lock:
        conn = db.db()
        conn.execute("DELETE FROM file_chunks WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
        conn.commit()
    _cache.invalidate()


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for name in filenames:
            if not name.startswith(".") and not name.startswith("~$") and Path(name).suffix.lower() in SUPPORTED:
                yield Path(dirpath) / name


status = {"running": False, "current": None, "done": 0, "total": 0, "last_scan": None, "message": None}
_scan_lock = threading.Lock()


def scan_source(source: dict) -> dict:
    """Bring the index for one folder up to date. Returns counts."""
    _ensure_schema()
    root = Path(source["path"])
    known = {r["path"]: r for r in db._query("SELECT id, path, size, mtime, status FROM files WHERE source_id = ?",
                                              (source["id"],))}
    counts = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}
    seen = set()
    if root.is_dir():
        todo = []
        for path in _walk(root):
            if len(seen) >= MAX_FILES_PER_SOURCE:
                status["message"] = f"Stopped at {MAX_FILES_PER_SOURCE} files in {root.name}; choose a smaller folder."
                break
            seen.add(str(path))
            try:
                st = path.stat()
            except OSError:
                continue
            old = known.get(str(path))
            if old and old["size"] == st.st_size and abs(old["mtime"] - st.st_mtime) < 1e-6:
                counts["unchanged"] += 1
            else:
                todo.append((path, "updated" if old else "added"))
        status["total"] += len(todo)
        for path, kind in todo:
            status["current"] = path.name
            index_file(source["id"], path)
            counts[kind] += 1
            status["done"] += 1
    for p, row in known.items():
        if p not in seen:
            _forget_file(row["id"])
            counts["removed"] += 1
    return counts


def scan_all() -> dict:
    """Scan every folder. Only one scan runs at a time."""
    if not _scan_lock.acquire(blocking=False):
        return {"skipped": "scan already running"}
    try:
        status.update(running=True, done=0, total=0, current=None, message=None)
        totals = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}
        for src in list_sources():
            for k, v in scan_source(src).items():
                totals[k] += v
        status["last_scan"] = db.now()
        return totals
    finally:
        status.update(running=False, current=None)
        _scan_lock.release()


# ---------- sources ----------

def list_sources() -> list[dict]:
    _ensure_schema()
    return db._query(
        """SELECT s.*, COUNT(f.id) AS files, COALESCE(SUM(f.chunks), 0) AS chunks,
                  SUM(CASE WHEN f.status = 'error' THEN 1 ELSE 0 END) AS errors
           FROM sources s LEFT JOIN files f ON f.source_id = s.id GROUP BY s.id ORDER BY s.id""")


def add_source(path: str) -> dict:
    _ensure_schema()
    p = Path(os.path.expanduser(path.strip())).resolve()
    if not p.is_dir():
        raise ValueError(f"Folder not found: {p}")
    if p == Path(p.anchor) or p == Path.home():
        raise ValueError("That folder is too big. Pick a specific folder, such as ~/Documents/School.")
    for s in list_sources():
        sp = Path(s["path"])
        if p == sp or sp in p.parents:
            raise ValueError(f"Already covered by {sp}")
    db._exec("INSERT INTO sources (path, added_at) VALUES (?, ?)", (str(p), db.now()))
    wake()
    return next(s for s in list_sources() if s["path"] == str(p))


def remove_source(source_id: int) -> bool:
    _ensure_schema()
    for f in db._query("SELECT id FROM files WHERE source_id = ?", (source_id,)):
        _forget_file(f["id"])
    return db._exec("DELETE FROM sources WHERE id = ?", (source_id,)).rowcount > 0


def list_files(source_id: int | None = None, limit: int = 500) -> list[dict]:
    _ensure_schema()
    where, params = ("WHERE source_id = ?", (source_id,)) if source_id else ("", ())
    return db._query(f"SELECT * FROM files {where} ORDER BY mtime DESC LIMIT ?", (*params, limit))


def get_file(file_id: int) -> dict | None:
    _ensure_schema()
    rows = db._query("SELECT * FROM files WHERE id = ?", (file_id,))
    return rows[0] if rows else None


# ---------- background watcher ----------

_wake = threading.Event()
_thread: threading.Thread | None = None


def wake() -> None:
    """Ask the watcher to scan now (e.g. after adding a folder)."""
    _wake.set()


def start_watcher() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return

    def loop():
        while True:
            try:
                scan_all()
            except Exception:
                log.exception("File scan failed")
            _wake.wait(SCAN_INTERVAL)
            _wake.clear()

    _thread = threading.Thread(target=loop, daemon=True, name="aios-file-watcher")
    _thread.start()


# ---------- search ----------

def search(query: str, limit: int = 8, per_file: int = 2) -> list[dict]:
    """Hybrid search over file chunks. Each hit: file_id, name, path, page, text, match."""
    _ensure_schema()
    if not query.strip():
        return []
    words = [w for w in re.findall(r"\w+", query) if w.lower() not in db.STOPWORDS] or re.findall(r"\w+", query)
    keyword = []
    if words:
        keyword = db._query(
            """SELECT c.id, c.file_id, c.page, c.text, f.name, f.path
               FROM file_chunks_fts JOIN file_chunks c ON c.id = file_chunks_fts.rowid
               JOIN files f ON f.id = c.file_id
               WHERE file_chunks_fts MATCH ? ORDER BY rank LIMIT ?""",
            (" OR ".join(f'"{w}"*' for w in words), limit * 4))

    meaning = []
    if memory.enabled():
        matrix, rows = _cache.get()
        if rows:
            scores = matrix @ memory._embedder.embed_query(query)
            order = np.argsort(-scores)[: limit * 4]
            meaning = [(rows[i]["id"], float(scores[i]), rows[i]) for i in order]
    kw_ids = {k["id"] for k in keyword}
    meaning = memory.keep_strong(meaning, lambda m: m[1], kw_ids)

    fused = memory.rrf([k["id"] for k in keyword], [m[0] for m in meaning])
    by_id = {k["id"]: k for k in keyword} | {m[0]: m[2] for m in meaning}
    sim = {m[0]: m[1] for m in meaning}

    results, per = [], {}
    for cid in sorted(fused, key=fused.get, reverse=True):
        hit = dict(by_id[cid])
        if per.get(hit["file_id"], 0) >= per_file:
            continue
        per[hit["file_id"]] = per.get(hit["file_id"], 0) + 1
        in_kw, in_sem = cid in kw_ids, cid in sim
        hit["match"] = "both" if in_kw and in_sem else ("keyword" if in_kw else "meaning")
        if in_sem:
            hit["similarity"] = round(sim[cid], 3)
        results.append(hit)
        if len(results) >= limit:
            break
    return results


def read(file_id: int, page: int | None = None, max_chars: int = 15000) -> dict:
    """Full text of an indexed file (or one PDF page), read fresh from disk."""
    f = get_file(file_id)
    if not f:
        return {"error": f"No indexed file with id {file_id}"}
    path = Path(f["path"])
    if not path.is_file():
        return {"error": f"{f['name']} no longer exists on disk"}
    pieces = extract(path)
    if page is not None:
        pieces = [p for p in pieces if p[0] == page]
        if not pieces:
            return {"error": f"{f['name']} has no page {page}"}
    text = "\n\n".join((f"[Page {p}]\n" if p else "") + _clean(t) for p, t in pieces)
    out = {"file_id": file_id, "name": f["name"], "path": f["path"], "pages": f["pages"],
           "text": text[:max_chars]}
    if len(text) > max_chars:
        out["truncated"] = f"Showing the first {max_chars} of {len(text)} characters; ask for a specific page to see more."
    return out


# ---------- sources cited during one chat turn ----------

_cited: contextvars.ContextVar[list | None] = contextvars.ContextVar("aios_cited", default=None)


def begin_citations() -> list:
    lst: list = []
    _cited.set(lst)
    return lst


def cite(file_id: int, name: str, page: int | None) -> None:
    lst = _cited.get()
    if lst is not None and not any(c["file_id"] == file_id and c["page"] == page for c in lst):
        lst.append({"file_id": file_id, "name": name, "page": page})
