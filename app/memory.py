"""Semantic memory: finds notes by meaning, not just matching words.

Each note is split into chunks, each chunk is turned into a vector (a list of
384 numbers) by a small embedding model that runs locally on your computer.
Similar meanings give similar vectors, so a search compares the question's
vector with every chunk's vector (cosine similarity).

Search is "hybrid": keyword results (SQLite full-text) and meaning results are
merged with Reciprocal Rank Fusion, so exact names and fuzzy ideas both work.

Set AIOS_EMBEDDINGS=off to run with keyword search only.
"""

import hashlib
import logging
import os
import threading
from pathlib import Path

import numpy as np

from . import db

log = logging.getLogger("aios.memory")

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_DIR = Path(os.environ.get("AIOS_MODEL_DIR", Path(__file__).resolve().parent.parent / "data" / "models"))
ENABLED = os.environ.get("AIOS_EMBEDDINGS", "on").lower() not in ("off", "0", "false")

CHUNK_CHARS = 800      # ~200 tokens, well under the model's 512-token limit
CHUNK_OVERLAP = 150
MIN_SIMILARITY = 0.50  # meaning-only matches weaker than this are ignored
RELATIVE_GAP = 0.07    # ...and so are ones much weaker than the best match
RRF_K = 60             # standard Reciprocal Rank Fusion constant

SCHEMA = """
CREATE TABLE IF NOT EXISTS note_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,
    model TEXT NOT NULL,
    note_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS note_chunks_note ON note_chunks(note_id);
"""


# ---------- embedding model ----------

class Embedder:
    """Wraps the local model. Loaded lazily on first use (about a second)."""

    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding
                MODEL_DIR.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(self.model_name, cache_dir=str(MODEL_DIR))
        return self._model

    def embed_docs(self, texts: list[str]) -> np.ndarray:
        return _normalise(np.array(list(self._load().embed(texts)), dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        return _normalise(np.array(list(self._load().query_embed([text])), dtype=np.float32))[0]


def _normalise(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


_embedder: Embedder | None = Embedder() if ENABLED else None


def set_embedder(e) -> None:
    """Swap the model (tests use a fake one). Pass None to disable."""
    global _embedder
    _embedder = e
    for c in VectorCache.registry:
        c.invalidate()


def enabled() -> bool:
    return _embedder is not None


# ---------- chunking ----------

def note_text(note: dict) -> str:
    parts = [note["title"], note.get("body") or ""]
    if note.get("tags"):
        parts.append("Tags: " + note["tags"])
    return "\n".join(p for p in parts if p).strip()


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split on paragraph/sentence boundaries where possible."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if cut > size // 2:
                end = start + cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _hash(note: dict) -> str:
    return hashlib.sha1(note_text(note).encode()).hexdigest()


# ---------- in-memory vector cache ----------

class VectorCache:
    """All vectors returned by `sql` as one matrix, rebuilt only after data changes.
    `sql` must select a `vector` column; the other columns come back as row dicts."""

    registry: list["VectorCache"] = []

    def __init__(self, sql: str):
        self.sql = sql
        self.lock = threading.Lock()
        self.matrix: np.ndarray | None = None
        self.rows: list[dict] = []
        VectorCache.registry.append(self)

    def invalidate(self):
        with self.lock:
            self.matrix = None

    def get(self) -> tuple[np.ndarray, list[dict]]:
        with self.lock:
            if self.matrix is None:
                rows = db._query(self.sql)
                self.matrix = (np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
                               if rows else np.zeros((0, 1), dtype=np.float32))
                self.rows = [{k: v for k, v in r.items() if k != "vector"} for r in rows]
            return self.matrix, self.rows


def rrf(*rankings: list, k: int = RRF_K) -> dict:
    """Reciprocal Rank Fusion: merge ranked lists of ids into one score per id."""
    scores: dict = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0) + 1 / (k + rank + 1)
    return scores


def keep_strong(hits: list, score_of, always: set = frozenset()) -> list:
    """Drop meaning matches that are weak overall or far below the best one."""
    best = score_of(hits[0]) if hits else 0
    return [h for h in hits if h[0] in always
            or (score_of(h) >= MIN_SIMILARITY and score_of(h) >= best - RELATIVE_GAP)]


_cache = VectorCache("SELECT note_id, text, vector FROM note_chunks")
_schema_ready = False


def _ensure_schema():
    global _schema_ready
    if not _schema_ready:
        with db._lock:
            db.db().executescript(SCHEMA)
        _schema_ready = True


# ---------- indexing ----------

def index_note(note: dict) -> None:
    """(Re)compute vectors for one note. Skips work if nothing changed."""
    if not enabled() or not note:
        return
    _ensure_schema()
    h = _hash(note)
    existing = db._query("SELECT note_hash, model FROM note_chunks WHERE note_id = ? LIMIT 1", (note["id"],))
    if existing and existing[0]["note_hash"] == h and existing[0]["model"] == _embedder.model_name:
        return
    pieces = chunk(note_text(note))
    vectors = _embedder.embed_docs(pieces) if pieces else []
    with db._lock:
        conn = db.db()
        conn.execute("DELETE FROM note_chunks WHERE note_id = ?", (note["id"],))
        conn.executemany(
            "INSERT INTO note_chunks (note_id, chunk_index, text, vector, model, note_hash) VALUES (?, ?, ?, ?, ?, ?)",
            [(note["id"], i, p, v.astype(np.float32).tobytes(), _embedder.model_name, h)
             for i, (p, v) in enumerate(zip(pieces, vectors))],
        )
        conn.commit()
    _cache.invalidate()


def forget_note(note_id: int) -> None:
    _ensure_schema()
    db._exec("DELETE FROM note_chunks WHERE note_id = ?", (note_id,))
    _cache.invalidate()


def backfill() -> int:
    """Index every note that is new or changed since it was last indexed. Returns how many were (re)indexed."""
    if not enabled():
        return 0
    _ensure_schema()
    current = {r["note_id"]: (r["note_hash"], r["model"]) for r in
               db._query("SELECT note_id, note_hash, model FROM note_chunks WHERE chunk_index = 0")}
    stale = [n for n in db._query("SELECT * FROM notes")
             if current.get(n["id"]) != (_hash(n), _embedder.model_name)]
    for n in stale:
        index_note(n)
    db._exec("DELETE FROM note_chunks WHERE note_id NOT IN (SELECT id FROM notes)")
    _cache.invalidate()
    return len(stale)


def warm_up() -> None:
    """Load the model and backfill in the background so the first chat is fast."""
    def run():
        try:
            n = backfill()
            if enabled():
                _embedder.embed_query("warm up")
            log.info("Semantic memory ready (%d notes indexed)", n)
        except Exception:
            log.exception("Semantic memory unavailable; falling back to keyword search")
            set_embedder(None)
    threading.Thread(target=run, daemon=True).start()


# ---------- note operations (keep the index in sync) ----------

def save_note(title: str, body: str = "", tags: str = "") -> dict:
    note = db.add_note(title, body, tags)
    index_note(note)
    return note


def edit_note(note_id: int, title=None, body=None, tags=None) -> dict | None:
    note = db.update_note(note_id, title, body, tags)
    if note:
        index_note(note)
    return note


def remove_note(note_id: int) -> bool:
    ok = db.delete_note(note_id)
    if ok and enabled():
        forget_note(note_id)
    return ok


# ---------- search ----------

def semantic_search(query: str, limit: int = 10) -> list[tuple[int, float, str]]:
    """Return (note_id, similarity, best_chunk) sorted best first, one entry per note."""
    if not enabled() or not query.strip():
        return []
    _ensure_schema()
    matrix, rows = _cache.get()
    if not rows:
        return []
    scores = matrix @ _embedder.embed_query(query)
    best: dict[int, tuple[float, str]] = {}
    for i in np.argsort(-scores):
        nid = rows[i]["note_id"]
        if nid not in best:
            best[nid] = (float(scores[i]), rows[i]["text"])
        if len(best) >= limit:
            break
    return [(nid, s, t) for nid, (s, t) in best.items()]


def search(query: str, limit: int = 10) -> list[dict]:
    """Hybrid keyword + meaning search. Each result has `match`: keyword, meaning or both."""
    if not query.strip():
        return db.list_notes(limit)
    keyword = db.search_notes(query, limit * 2)
    meaning = [(nid, s, t) for nid, s, t in semantic_search(query, limit * 2)]
    kw_ids = {n["id"] for n in keyword}
    meaning = keep_strong(meaning, lambda m: m[1], kw_ids)
    fused = rrf([n["id"] for n in keyword], [m[0] for m in meaning])

    by_id = {n["id"]: n for n in keyword}
    sim = {nid: (s, t) for nid, s, t in meaning}
    results = []
    for nid in sorted(fused, key=fused.get, reverse=True)[:limit]:
        note = by_id.get(nid) or db.get_note(nid)
        if not note:
            continue
        note = dict(note)
        in_kw, in_sem = nid in kw_ids, nid in sim
        note["match"] = "both" if in_kw and in_sem else ("keyword" if in_kw else "meaning")
        if in_sem:
            note["similarity"] = round(sim[nid][0], 3)
            note.setdefault("snippet", sim[nid][1][:160])
        results.append(note)
    return results


def recall(query: str, limit: int = 3, min_similarity: float = 0.5) -> list[dict]:
    """Strongly related notes to hand Claude automatically with each message."""
    hits = [h for h in semantic_search(query, limit) if h[1] >= min_similarity]
    return [n for n in (db.get_note(nid) for nid, _, _ in hits) if n]
