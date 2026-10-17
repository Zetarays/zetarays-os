# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — content index for the universal search.

Builds an SQLite FTS5 index of the text in the user's documents, so search
finds files by what they contain, not only by name:

  • plain text (.txt .md .csv .log …)      → read directly
  • PDF                                     → text extracted with pdftotext (poppler)
  • images (.png .jpg .tiff .webp …)        → OCR with Tesseract (Italian+English)

File names are already searched quickly by plocate: only the CONTENT is
indexed here. The index is incremental (a file is re-read only if it changed),
skips system/cache folders and respects permissions. OCR is capped so it does
not use too much CPU. If a tool is missing, that file type is indexed by name
only, without ever blocking indexing.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from i18n_data import load

HOME = Path(os.path.expanduser("~"))
CACHE = HOME / ".cache" / "zeta"
DB = CACHE / "index.db"

# XDG user folders to index (content): the real names are those in
# ~/.config/user-dirs.dirs, which change with the system language
_XDG_KEYS = ("XDG_DOCUMENTS_DIR", "XDG_DESKTOP_DIR", "XDG_DOWNLOAD_DIR",
             "XDG_PICTURES_DIR", "XDG_TEMPLATES_DIR", "XDG_PUBLICSHARE_DIR")


def _xdg_user_dirs() -> list:
    """The user folders declared in user-dirs.dirs (xdg-user-dirs format:
    XDG_DOCUMENTS_DIR="$HOME/<localized name>")."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
    out = []
    try:
        with open(config / "user-dirs.dirs", encoding="utf-8", errors="replace") as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if not sep or key not in _XDG_KEYS:
                    continue
                value = value.strip().strip('"')
                if value.startswith("$HOME"):
                    value = str(HOME) + value[len("$HOME"):]
                if value.startswith("/"):
                    out.append(Path(value))
    except OSError:
        pass
    return out


# folders to index (content) — user data only: the XDG ones, then the default
# English names and the Italian ones from i18n-data/indexer.json (if they
# exist; duplicates are skipped in _iter_files)
ROOTS = [d for d in _xdg_user_dirs() if d != HOME]
ROOTS += [HOME / d for d in ("Documents", "Desktop", "Downloads", "Pictures",
                             "Templates", "Public",
                             *load("indexer")["user_folders"])]
# also index the top-level files in the home directory
ROOTS.append(HOME)

EXCLUDE_NAMES = {".git", "node_modules", "__pycache__", ".cache", ".local",
                 ".config", "snap", ".venv", "venv", ".npm", ".mozilla",
                 ".thumbnails", ".steam", ".rustup", ".cargo"}

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".conf", ".cfg",
            ".ini", ".json", ".yaml", ".yml", ".xml", ".html", ".htm", ".py",
            ".sh", ".c", ".h", ".cpp", ".js", ".ts", ".css", ".rst", ".tex"}
PDF_EXT = {".pdf"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp", ".gif"}

MAX_TEXT_BYTES = 2 * 1024 * 1024          # do not read huge text files
MAX_IMG_BYTES = 8 * 1024 * 1024           # OCR only on reasonably sized images
MAX_CONTENT_CHARS = 60000                 # text stored per file
MAX_DEPTH = 8
OCR_BUDGET = 40                           # max images to OCR per run


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
            from system import ocr
            out = subprocess.run(["tesseract", str(path), "-", "-l", ocr.languages(), "--psm", "3"],
                                 capture_output=True, text=True, timeout=45)
            return out.stdout[:MAX_CONTENT_CHARS]
    except (OSError, subprocess.SubprocessError):
        return ""
    return ""


def _kind(ext: str) -> str:
    if ext in PDF_EXT:
        return "pdf"
    if ext in IMG_EXT:
        return "image"
    if ext in TEXT_EXT:
        return "text"
    return "file"


def _utf8(name: str) -> bool:
    """Non-UTF-8 names (old zip files, Windows disks) become Python strings
    with «surrogates» that SQLite and GTK reject: they are skipped instead of
    stopping the whole indexing run."""
    try:
        name.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _iter_files():
    seen_roots = set()
    home = HOME.resolve()
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
                           if not d.startswith(".") and d not in EXCLUDE_NAMES and _utf8(d)]
            # the home directory itself: only top-level files, not every subfolder
            if root == home and depth == 0:
                dirnames[:] = []
            for name in filenames:
                if name.startswith(".") or not _utf8(name):
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
        try:
            content = _extract_text(path, ext, ocr_left)
            db.execute("DELETE FROM docs WHERE path = ?", (sp,))
            db.execute("INSERT INTO docs (path, name, kind, content) VALUES (?,?,?,?)",
                       (sp, path.name, _kind(ext), content))
            db.execute("INSERT OR REPLACE INTO meta (path, mtime, size) VALUES (?,?,?)",
                       (sp, st.st_mtime, st.st_size))
        except (sqlite3.Error, UnicodeError, ValueError) as e:
            # one odd file must not stop indexing of all the others
            print("index: skipping %r: %s" % (sp, e), file=sys.stderr)
            continue
        if prev:
            updated += 1
        else:
            added += 1
    # remove files that disappeared from the index
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
    """Search the indexed content. Returns [{path, name, kind, snippet}]."""
    if not DB.exists() or not query.strip():
        return []
    try:
        db = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
    except sqlite3.Error:
        return []
    # FTS query: every word as a prefix
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
