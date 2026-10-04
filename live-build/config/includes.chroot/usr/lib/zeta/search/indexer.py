# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — indice dei contenuti per la ricerca universale.

Costruisce un indice SQLite FTS5 del testo dei documenti dell'utente, così la
ricerca trova i file anche per quello che contengono, non solo per il nome:

  • testo semplice (.txt .md .csv .log …)  → letto direttamente
  • PDF                                     → testo estratto con pdftotext (poppler)
  • immagini (.png .jpg .tiff .webp …)      → OCR con Tesseract (italiano+inglese)

I nomi dei file sono già cercati velocemente da plocate: qui si indicizza solo
il CONTENUTO. L'indice è incrementale (rilegge un file solo se è cambiato),
salta le cartelle di sistema/cache e rispetta i permessi. L'OCR è limitato per
non consumare troppa CPU. Se uno strumento manca, quel tipo di file viene
indicizzato solo per nome, senza mai bloccare l'indicizzazione.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
CACHE = HOME / ".cache" / "zeta"
DB = CACHE / "index.db"

# cartelle da indicizzare (contenuto) — solo dati dell'utente
ROOTS = [HOME / d for d in ("Documenti", "Documents", "Scrivania", "Desktop",
                            "Download", "Downloads", "Immagini", "Pictures",
                            "Modelli", "Templates", "Pubblici", "Public")]
# indicizza anche i file di primo livello nella home
ROOTS.append(HOME)

EXCLUDE_NAMES = {".git", "node_modules", "__pycache__", ".cache", ".local",
                 ".config", "snap", ".venv", "venv", ".npm", ".mozilla",
                 ".thumbnails", ".steam", ".rustup", ".cargo"}

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".conf", ".cfg",
            ".ini", ".json", ".yaml", ".yml", ".xml", ".html", ".htm", ".py",
            ".sh", ".c", ".h", ".cpp", ".js", ".ts", ".css", ".rst", ".tex"}
PDF_EXT = {".pdf"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp", ".gif"}

MAX_TEXT_BYTES = 2 * 1024 * 1024          # non leggere file di testo enormi
MAX_IMG_BYTES = 8 * 1024 * 1024           # OCR solo su immagini ragionevoli
MAX_CONTENT_CHARS = 60000                 # testo salvato per file
MAX_DEPTH = 8
OCR_BUDGET = 40                           # max immagini con OCR per esecuzione


def _connect() -> sqlite3.Connection:
    CACHE.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB), timeout=10)
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5("
               "path UNINDEXED, name, kind UNINDEXED, content, tokenize='unicode61')")
    db.execute("CREATE TABLE IF NOT EXISTS meta (path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    return db


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _extract_text(path: Path, ext: str, ocr_left: list) -> str:
    try:
        if ext in TEXT_EXT:
            if path.stat().st_size > MAX_TEXT_BYTES:
                return ""
            return path.read_text(errors="replace")[:MAX_CONTENT_CHARS]
        if ext in PDF_EXT and _have("pdftotext"):
            out = subprocess.run(["pdftotext", "-q", "-l", "20", str(path), "-"],
                                 capture_output=True, text=True, timeout=30)
            return out.stdout[:MAX_CONTENT_CHARS]
        if ext in IMG_EXT and _have("tesseract") and ocr_left[0] > 0:
            if path.stat().st_size > MAX_IMG_BYTES:
                return ""
            ocr_left[0] -= 1
            out = subprocess.run(["tesseract", str(path), "-", "-l", "ita+eng", "--psm", "3"],
                                 capture_output=True, text=True, timeout=45)
            return out.stdout[:MAX_CONTENT_CHARS]
    except (OSError, subprocess.SubprocessError):
        return ""
    return ""


def _kind(ext: str) -> str:
    if ext in PDF_EXT:
        return "pdf"
    if ext in IMG_EXT:
        return "immagine"
    if ext in TEXT_EXT:
        return "testo"
    return "file"


def _iter_files():
    seen_roots = set()
    for root in ROOTS:
        root = root.resolve()
        if not root.is_dir() or root in seen_roots:
            continue
        seen_roots.add(root)
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = len(Path(dirpath).parts) - base_depth
            if depth > MAX_DEPTH:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d not in EXCLUDE_NAMES]
            # la home stessa: solo i file di primo livello, non tutte le sottocartelle
            if root == HOME and depth == 0:
                dirnames[:] = []
            for name in filenames:
                if name.startswith("."):
                    continue
                yield Path(dirpath) / name


def reindex(full: bool = False) -> dict:
    db = _connect()
    if full:
        db.execute("DELETE FROM docs")
        db.execute("DELETE FROM meta")
    known = {r[0]: (r[1], r[2]) for r in db.execute("SELECT path, mtime, size FROM meta")}
    ocr_left = [OCR_BUDGET]
    added = updated = 0
    present = set()
    for path in _iter_files():
        ext = path.suffix.lower()
        if ext not in TEXT_EXT and ext not in PDF_EXT and ext not in IMG_EXT:
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        sp = str(path)
        present.add(sp)
        prev = known.get(sp)
        if prev and abs(prev[0] - st.st_mtime) < 1 and prev[1] == st.st_size:
            continue
        content = _extract_text(path, ext, ocr_left)
        db.execute("DELETE FROM docs WHERE path = ?", (sp,))
        db.execute("INSERT INTO docs (path, name, kind, content) VALUES (?,?,?,?)",
                   (sp, path.name, _kind(ext), content))
        db.execute("INSERT OR REPLACE INTO meta (path, mtime, size) VALUES (?,?,?)",
                   (sp, st.st_mtime, st.st_size))
        if prev:
            updated += 1
        else:
            added += 1
    # rimuove dall'indice i file spariti
    removed = 0
    for sp in list(known):
        if sp not in present:
            db.execute("DELETE FROM docs WHERE path = ?", (sp,))
            db.execute("DELETE FROM meta WHERE path = ?", (sp,))
            removed += 1
    db.commit()
    db.close()
    return {"added": added, "updated": updated, "removed": removed}


def search(query: str, limit: int = 8) -> list[dict]:
    """Cerca nel contenuto indicizzato. Ritorna [{path, name, kind, snippet}]."""
    if not DB.exists() or not query.strip():
        return []
    try:
        db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
    except sqlite3.Error:
        return []
    # query FTS: ogni parola come prefisso
    terms = " ".join('"%s"*' % w.replace('"', '') for w in query.split() if w)
    if not terms:
        db.close()
        return []
    rows = []
    try:
        cur = db.execute(
            "SELECT path, name, kind, snippet(docs, 3, '', '', '…', 8) "
            "FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?", (terms, limit))
        for path, name, kind, snip in cur:
            rows.append({"path": path, "name": name, "kind": kind,
                         "snippet": (snip or "").strip().replace("\n", " ")})
    except sqlite3.Error:
        pass
    db.close()
    return rows
