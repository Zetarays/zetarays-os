# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — the local memory store (one SQLite file).

Everything ZETA remembers lives in ~/.local/share/zeta/memory.db, readable by
the user only, and never leaves the computer:

  turns      the conversation (it used to be history.jsonl). Only the latest
             turns go back to the model (memory.trim_history); older ones are
             deleted after the retention period chosen in Settings › AI.
  facts      long-term memories, only the ones the user asked for ("remember
             that…", or added in Settings › AI › Memory). Nothing is stored
             here by itself. Each question gets at most a few of them, the
             ones that match it, never the whole list.
  knowledge  reference material with its provenance: the verified facts
             shipped with ZETA RAYS (reference.json, with the date they were
             checked), the sources found by the web lookup (address,
             publication and retrieval date), documents the user imported.

Search is SQLite full-text search (FTS5) with the trigram tokenizer: it
matches parts of words, so "presidente", "presidenza" and "president" meet
on "presid" without a stemmer for each language, and it costs a fraction of
a millisecond for thousands of rows. No server, no extra model in memory.

One connection per call: the assistant works in its own thread and Settings
in the window's thread; SQLite in WAL mode lets them read and write without
blocking each other. A damaged file is set aside (memory.db.damaged-<time>)
and a new one is started: ZETA keeps working and says what happened.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from i18n_data import load

STATE_DIR = Path(os.path.expanduser("~/.local/share/zeta"))
DB_FILE = STATE_DIR / "memory.db"
OLD_HISTORY = STATE_DIR / "history.jsonl"          # 2.1 and earlier
REFERENCE_FILE = "/usr/share/zeta/knowledge/reference.json"
SCHEMA = 1

# Retention of the conversation (Settings › AI › Memory)
RETENTION_DAYS = 30
RETENTION_CHOICES = (1, 7, 30, 90, 365)
MAX_TURN_ROWS = 4000              # hard cap whatever the period
MAX_FACTS = 500
MAX_FACT_CHARS = 400
WEB_KNOWLEDGE_DAYS = 30           # web sources older than this are not reused
MAX_WEB_ROWS = 300

_checked: set = set()             # databases already verified in this process


@dataclass
class Fact:
    id: int
    text: str
    created: float
    used: float


@dataclass
class Knowledge:
    id: int
    title: str
    body: str
    url: str
    published: str      # ISO date, "" when unknown
    retrieved: str      # ISO date: when it was checked or fetched
    origin: str         # "reference" | "web" | "document"


# --- opening ---------------------------------------------------------------
def _create(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS turns(
            id INTEGER PRIMARY KEY, t REAL NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, action INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS turns_t ON turns(t);
        CREATE TABLE IF NOT EXISTS facts(
            id INTEGER PRIMARY KEY, text TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
            created REAL NOT NULL, used REAL NOT NULL DEFAULT 0,
            uses INTEGER NOT NULL DEFAULT 0);
        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
            text, content='facts', content_rowid='id', tokenize='trigram');
        CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
            INSERT INTO facts_fts(rowid, text) VALUES (new.id, new.text); END;
        CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
            INSERT INTO facts_fts(facts_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
        CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE OF text ON facts BEGIN
            INSERT INTO facts_fts(facts_fts, rowid, text) VALUES ('delete', old.id, old.text);
            INSERT INTO facts_fts(rowid, text) VALUES (new.id, new.text); END;
        CREATE TABLE IF NOT EXISTS knowledge(
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '', published TEXT NOT NULL DEFAULT '',
            retrieved TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE, added REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS knowledge_origin ON knowledge(origin, added);
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
            title, body, content='knowledge', content_rowid='id', tokenize='trigram');
        CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
            INSERT INTO knowledge_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END;
        CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
            INSERT INTO knowledge_fts(knowledge_fts, rowid, title, body)
            VALUES ('delete', old.id, old.title, old.body); END;
    """)
    db.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA),))


def _set_aside(path: Path) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.rename(Path("%s.damaged-%s%s" % (path, stamp, suffix)))


def connect(path: Path | None = None) -> sqlite3.Connection:
    """A connection to the store, created and checked on first use."""
    path = Path(path or DB_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    new = not path.exists()
    if new:
        # created readable by the user only, before anything is written
        os.close(os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600))
    db = sqlite3.connect(str(path), timeout=5.0)
    try:
        if str(path) not in _checked:
            ok = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            if not ok:
                raise sqlite3.DatabaseError("quick_check failed")
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                _create(db)
            _checked.add(str(path))
            if path == DB_FILE:
                _import_old_history(db)
                _load_reference(db)
        db.execute("PRAGMA synchronous=NORMAL")
        return db
    except sqlite3.DatabaseError:
        db.close()
        _set_aside(path)
        return connect(path)


@contextlib.contextmanager
def opened(path: Path | None = None):
    db = connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def _import_old_history(db: sqlite3.Connection) -> None:
    """history.jsonl (2.1 and earlier) moved into the store, once."""
    if not OLD_HISTORY.exists():
        return
    rows = []
    try:
        with open(OLD_HISTORY, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    rows.append((float(d.get("t") or 0), str(d["role"]), str(d["content"]),
                                 1 if d.get("action") else 0))
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        return
    with db:
        db.executemany("INSERT INTO turns(t, role, content, action) VALUES (?,?,?,?)", rows)
    count = db.execute("SELECT count(*) FROM turns").fetchone()[0]
    if count >= len(rows):                     # all of it is in: the old file can go
        try:
            OLD_HISTORY.unlink()
        except OSError:
            pass


def _load_reference(db: sqlite3.Connection, file: str | None = None) -> None:
    """The verified facts shipped with ZETA RAYS, reloaded when the file changes."""
    try:
        with open(file or REFERENCE_FILE, "rb") as f:
            raw = f.read()
    except OSError:
        return
    digest = hashlib.sha256(raw).hexdigest()
    row = db.execute("SELECT value FROM meta WHERE key='reference'").fetchone()
    if row and row[0] == digest:
        return
    try:
        entries = json.loads(raw.decode("utf-8"))["entries"]
    except (ValueError, KeyError, UnicodeDecodeError):
        return
    with db:
        db.execute("DELETE FROM knowledge WHERE origin='reference'")
        for e in entries:
            db.execute("INSERT OR REPLACE INTO knowledge(title, body, url, published, retrieved, "
                       "origin, key, added) VALUES (?,?,?,?,?,'reference',?,?)",
                       # the keywords (in the languages ZETA speaks) are searched
                       # with the title: an Italian question finds an English entry
                       (" | ".join([e["title"]] + list(e.get("keywords", []))), e["text"],
                        e.get("url", ""), e.get("published", ""), e.get("verified", ""),
                        "ref:" + e["id"], time.time()))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('reference', ?)", (digest,))


# --- search ------------------------------------------------------------------
def _stopwords() -> set:
    data = load("memory").get("stopwords", {})
    return {w for words in data.values() for w in words}


def terms(text: str) -> list[str]:
    """The searchable parts of a question: words of 3+ letters that carry
    meaning, cut to a common stem (the trigram index matches substrings)."""
    stop = _stopwords()
    out = []
    for w in re.findall(r"\w{3,}", (text or "").lower()):
        if w in stop or w.isdigit() and len(w) < 4:
            continue
        stem = w[:max(4, len(w) - 2)] if len(w) > 5 else w
        if stem not in out:
            out.append(stem)
    return out[:12]


def _match(text: str) -> str:
    """An FTS5 query: any of the terms (each one quoted, so no syntax leaks)."""
    return " OR ".join('"%s"' % t.replace('"', "") for t in terms(text))


def _hits(text: str, found: str) -> int:
    low = found.lower()
    return sum(1 for t in terms(text) if t in low)


def _needed(query: str) -> int:
    """How many terms of the question a row must contain: one word in common
    is chance when the question has several ("president of France" must not
    bring back the president of the United States)."""
    return 1 if len(terms(query)) <= 1 else 2


def search_facts(query: str, limit: int = 3, path: Path | None = None) -> list[Fact]:
    """The long-term memories that match a question, best first."""
    q = _match(query)
    if not q:
        return []
    with opened(path) as db:
        rows = db.execute(
            "SELECT f.id, f.text, f.created, f.used FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
            "WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT ?", (q, limit * 3)).fetchall()
        need = _needed(query)
        found = [Fact(*r) for r in rows if _hits(query, r[1]) >= need][:limit]
        if found:
            db.executemany("UPDATE facts SET used=?, uses=uses+1 WHERE id=?",
                           [(time.time(), f.id) for f in found])
    return found


def search_knowledge(query: str, limit: int = 2, origins=("reference", "web", "document"),
                     path: Path | None = None) -> list[Knowledge]:
    """Reference material that matches a question; web sources only while recent."""
    q = _match(query)
    if not q:
        return []
    marks = ",".join("?" * len(origins))
    oldest = time.time() - WEB_KNOWLEDGE_DAYS * 86400
    with opened(path) as db:
        rows = db.execute(
            "SELECT k.id, k.title, k.body, k.url, k.published, k.retrieved, k.origin "
            "FROM knowledge_fts JOIN knowledge k ON k.id = knowledge_fts.rowid "
            "WHERE knowledge_fts MATCH ? AND k.origin IN (%s) "
            "AND (k.origin != 'web' OR k.added >= ?) "
            "ORDER BY bm25(knowledge_fts, 4.0, 1.0) LIMIT ?" % marks,
            (q, *origins, oldest, limit * 3)).fetchall()
    need = _needed(query)
    return [Knowledge(*r) for r in rows if _hits(query, r[1] + " " + r[2]) >= need][:limit]


def fresh(day: str, max_days: int) -> bool:
    """True when an ISO date ("2026-10-24") is at most max_days old."""
    try:
        t = time.mktime(time.strptime(day[:10], "%Y-%m-%d"))
    except (ValueError, TypeError):
        return False
    return 0 <= time.time() - t <= max_days * 86400


# --- facts -------------------------------------------------------------------
def _key(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def _similar(a: str, b: str) -> float:
    """Share of trigrams in common (0..1): "I live in Rome" ~ "I live in Rome now"."""
    def grams(s):
        s = " %s " % _key(s)
        return {s[i:i + 3] for i in range(len(s) - 2)}
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga | gb))


def add_fact(text: str, path: Path | None = None) -> tuple[Fact | None, str]:
    """Store a memory the user asked for. Returns (fact, "added" | "updated" |
    "duplicate" | "empty" | "full")."""
    text = " ".join((text or "").split())[:MAX_FACT_CHARS].strip(" .")
    if len(_key(text)) < 3:
        return None, "empty"
    now = time.time()
    with opened(path) as db:
        key = _key(text)
        row = db.execute("SELECT id, text, created, used FROM facts WHERE key=?", (key,)).fetchone()
        if row:
            return Fact(*row), "duplicate"
        # the same memory said again with a detail more: replace, don't pile up
        q = _match(text)
        if q:
            for fid, old in db.execute(
                    "SELECT f.id, f.text FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
                    "WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts) LIMIT 5", (q,)).fetchall():
                if _similar(old, text) >= 0.6:
                    db.execute("UPDATE facts SET text=?, key=?, created=? WHERE id=?",
                               (text, key, now, fid))
                    return Fact(fid, text, now, 0.0), "updated"
        if db.execute("SELECT count(*) FROM facts").fetchone()[0] >= MAX_FACTS:
            return None, "full"
        cur = db.execute("INSERT INTO facts(text, key, created) VALUES (?,?,?)", (text, key, now))
        return Fact(cur.lastrowid, text, now, 0.0), "added"


def list_facts(path: Path | None = None) -> list[Fact]:
    with opened(path) as db:
        return [Fact(*r) for r in db.execute(
            "SELECT id, text, created, used FROM facts ORDER BY created DESC").fetchall()]


def delete_fact(fact_id: int, path: Path | None = None) -> bool:
    with opened(path) as db:
        return db.execute("DELETE FROM facts WHERE id=?", (fact_id,)).rowcount > 0


def forget_matching(text: str, path: Path | None = None) -> list[str]:
    """Delete the memories that match a description ("forget where I live")."""
    found = search_facts(text, limit=5, path=path)
    with opened(path) as db:
        db.executemany("DELETE FROM facts WHERE id=?", [(f.id,) for f in found])
    return [f.text for f in found]


# --- conversation ------------------------------------------------------------
def save_turn(user_text: str, assistant_text: str, operation: bool = False,
              path: Path | None = None) -> None:
    now = time.time()
    with opened(path) as db:
        db.executemany("INSERT INTO turns(t, role, content, action) VALUES (?,?,?,?)",
                       [(now, "user", user_text, int(operation)),
                        (now, "assistant", assistant_text, int(operation))])


def recent_turns(pairs: int, path: Path | None = None) -> list[tuple[str, str, bool]]:
    """The latest messages, oldest first: (role, content, was_an_action)."""
    with opened(path) as db:
        rows = db.execute("SELECT role, content, action FROM turns ORDER BY id DESC LIMIT ?",
                          (pairs * 2,)).fetchall()
    return [(r, c, bool(a)) for r, c, a in reversed(rows)]


def prune(retention_days: int = RETENTION_DAYS, path: Path | None = None) -> int:
    """Delete the conversation older than the retention period (and beyond
    the row cap), and web sources nobody will reuse. Returns rows deleted."""
    oldest = time.time() - max(1, retention_days) * 86400
    with opened(path) as db:
        n = db.execute("DELETE FROM turns WHERE t < ?", (oldest,)).rowcount
        n += db.execute("DELETE FROM turns WHERE id NOT IN "
                        "(SELECT id FROM turns ORDER BY id DESC LIMIT ?)", (MAX_TURN_ROWS,)).rowcount
        n += db.execute("DELETE FROM knowledge WHERE origin='web' AND id NOT IN "
                        "(SELECT id FROM knowledge WHERE origin='web' ORDER BY added DESC LIMIT ?)",
                        (MAX_WEB_ROWS,)).rowcount
    return n


def clear(what: str = "conversation", path: Path | None = None) -> None:
    """"conversation", "facts" or "everything" (the reference facts stay)."""
    with opened(path) as db:
        if what in ("conversation", "everything"):
            db.execute("DELETE FROM turns")
        if what in ("facts", "everything"):
            db.execute("DELETE FROM facts")
        if what == "everything":
            db.execute("DELETE FROM knowledge WHERE origin != 'reference'")
    with contextlib.closing(connect(path)) as db:
        db.execute("VACUUM")                    # deleted text really leaves the disk file


# --- knowledge ---------------------------------------------------------------
def remember_sources(sources, path: Path | None = None) -> None:
    """Keep the web sources of an answer, with their provenance, so the same
    question asked again soon can be answered from them even offline."""
    now = time.time()
    with opened(path) as db:
        for s in sources:
            url = getattr(s, "url", "")
            if not url:
                continue
            db.execute("DELETE FROM knowledge WHERE key=?", ("web:" + url,))
            db.execute("INSERT INTO knowledge(title, body, url, published, retrieved, origin, key, added) "
                       "VALUES (?,?,?,?,?,'web',?,?)",
                       (getattr(s, "title", "") or url, getattr(s, "snippet", "") or "", url,
                        getattr(s, "published", "") or "", getattr(s, "retrieved", "") or "",
                        "web:" + url, now))


def import_document(title: str, text: str, origin_path: str = "", path: Path | None = None,
                    chunk: int = 1200) -> int:
    """A text the user chose to give ZETA as reference, cut into passages."""
    text = text.replace("\r", "")
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if cur and len(cur) + len(para) > chunk:
            parts.append(cur)
            cur = ""
        cur = (cur + "\n\n" + para).strip()
        while len(cur) > chunk * 2:
            parts.append(cur[:chunk])
            cur = cur[chunk:]
    if cur:
        parts.append(cur)
    day = time.strftime("%Y-%m-%d")
    with opened(path) as db:
        db.execute("DELETE FROM knowledge WHERE origin='document' AND url=?", (origin_path,))
        for i, p in enumerate(parts):
            db.execute("INSERT INTO knowledge(title, body, url, published, retrieved, origin, key, added) "
                       "VALUES (?,?,?,'',?,'document',?,?)",
                       (title, p, origin_path, day, "doc:%s#%d" % (origin_path or title, i), time.time()))
    return len(parts)


def export(dest: str, path: Path | None = None) -> bool:
    """Everything the user's ZETA remembers, as one readable JSON file."""
    with opened(path) as db:
        data = {
            "facts": [{"text": t, "created": c} for t, c in
                      db.execute("SELECT text, created FROM facts ORDER BY created")],
            "conversation": [{"t": t, "role": r, "content": c} for t, r, c in
                             db.execute("SELECT t, role, content FROM turns ORDER BY id")],
            "knowledge": [{"title": a, "url": b, "retrieved": c, "origin": d, "text": e}
                          for a, b, c, d, e in db.execute(
                              "SELECT title, url, retrieved, origin, body FROM knowledge "
                              "WHERE origin != 'reference' ORDER BY added")],
        }
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


def stats(path: Path | None = None) -> dict:
    """Sizes for Settings and the tests."""
    with opened(path) as db:
        count = {name: db.execute("SELECT count(*) FROM %s" % name).fetchone()[0]
                 for name in ("turns", "facts", "knowledge")}
    p = Path(path or DB_FILE)
    count["bytes"] = sum(Path(str(p) + s).stat().st_size for s in ("", "-wal")
                         if Path(str(p) + s).exists())
    return count
