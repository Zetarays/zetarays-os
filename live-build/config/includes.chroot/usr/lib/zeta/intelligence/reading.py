# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — read what the user is looking at, or a file.

«What's on my screen?», «translate what I'm looking at», «summarize this
file»: ZETA has no vision model (one that sees images costs gigabytes of
memory), so it reads the TEXT. The window in front is captured (grim) and
its text recognized (tesseract, on this computer); a file's text is read
directly (plain text, PDF with pdftotext, Word and LibreOffice documents
from their XML). The text, cut to what the local model reads in reasonable
time, goes to the local model together with the user's request.

Nothing leaves the computer. The screen capture is deleted at once, and the
text read is not written to ZETA's memory: only the question and the answer
are kept (Assistant.ask saves the request, not the document).

The English request patterns are below; the Italian ones are language data
(i18n-data/reading.json).
"""
from __future__ import annotations

import html
import os
import re
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass

from i18n import tr
from i18n_data import load

from .agent import state as S

_W = load("reading")

# --- what the user asks ------------------------------------------------------
# Matched on the normalized text (lowercase, no accents: state.norm).
_SCREEN_EN = (
    r"\bwhat(?:'s| is|s| do you see| can you see| appears)? on (?:my|the|this) (?:screen|monitor|display)\b",
    r"\bwhat am i (?:looking at|seeing|reading)\b",
    r"\bwhat(?:'s| is|s) (?:in|on) (?:this|the|my) (?:window|page)\b",
    r"\b(?:read|summari[sz]e|sum up|translate|explain|describe|proofread|correct|check|tell me about)\b"
    r".{0,40}\b(?:(?:on )?(?:my|the|this) (?:screen|monitor|display)|"
    r"what i(?:'m| am) (?:looking at|seeing|reading)|"
    r"this (?:window|page)|the (?:current|active|open|front) (?:window|page))\b",
)
# «turn off the screen», «screen brightness», «full screen», «screenshot»:
# other commands (understanding.py), never a reading
_NOT_SCREEN_EN = (r"\bscreen ?(?:shot|saver|resolution|brightness|size|scale|scaling|lock|time|"
                  r"reader|recorder|recording|capture|sharing)\b|\bfull ?screen\b|"
                  r"\block(?:ed)? (?:the )?screen\b|\b(?:turn|switch) (?:off|on)\b|"
                  r"\bscreen (?:off|on)\b|\bsecond (?:screen|monitor)\b")

# Matched on the text as written (paths keep their case), ignoring case.
_FILE_EN = (r"^(?:please\s+)?(?:can you\s+|could you\s+)?(?:summari[sz]e|sum up|give me a summary of|"
            r"explain|translate|read)\s+(?:the |this |my )?(?:file|document|pdf)?\s*"
            r"[“\"«']?(?P<path>[~/][^“”\"«»]*?)[”\"»']?\s*[.?!]?$")
_WHICH_FILE_EN = (r"^(?:please\s+)?(?:can you\s+|could you\s+)?(?:summari[sz]e|sum up)\s+"
                  r"(?:this|a|the|my) (?:file|document|pdf)\s*[.?!]?$")

_SCREEN = [re.compile(p) for p in _SCREEN_EN + tuple(_W["screen"])]
_NOT_SCREEN = re.compile(_NOT_SCREEN_EN + "|" + _W["not_screen"])
_FILE = [re.compile(p, re.I) for p in (_FILE_EN, *_W["file"])]
_WHICH_FILE = [re.compile(p, re.I) for p in (_WHICH_FILE_EN, *_W["which_file"])]


def parse(text: str):
    """What the request asks to read: ("screen", None), ("file", path),
    ("missing", path) for a path that is not a file, ("which_file", None)
    for «summarize this file» without saying which; None otherwise."""
    raw = " ".join((text or "").split())
    if not raw:
        return None
    for p in _FILE:
        m = p.match(raw)
        if m:
            path = os.path.expanduser(m.group("path").strip())
            return ("file", path) if os.path.isfile(path) else ("missing", path)
    if any(p.match(raw) for p in _WHICH_FILE):
        return "which_file", None
    t = S.norm(raw).replace("’", "'")
    if _NOT_SCREEN.search(t):
        return None
    if any(p.search(t) for p in _SCREEN):
        return "screen", None
    return None


# --- the text ----------------------------------------------------------------
class ReadError(Exception):
    """A readable explanation of why the text could not be read."""


@dataclass
class Document:
    kind: str        # "screen" or "file"
    source: str      # the window («Firefox: page title») or the file name
    text: str


# The class of ZETA's own window: asking from it, the window to read is the
# one used before (Hyprland's focus history).
OWN_CLASSES = ("org.zetarays.Core",)
OCR_SECONDS = 60
# Above this many pixels the capture is not doubled (time and memory of the
# text recognition on a slow processor).
DOUBLE_BELOW_PIXELS = 1_600_000


def _visible_workspaces() -> set:
    ids = set()
    for m in S.hypr_json("monitors") or []:
        for key in ("activeWorkspace", "specialWorkspace"):
            ws = m.get(key) or {}
            if ws.get("id"):
                ids.add(ws["id"])
    return ids


def target_window(clients=None, visible=None) -> dict | None:
    """The window the user is looking at: the most recently focused one on a
    visible workspace that is not ZETA itself (None: none, read the screen)."""
    clients = S.windows() if clients is None else clients
    visible = _visible_workspaces() if visible is None else visible
    best = None
    for w in clients or []:
        if not isinstance(w, dict) or w.get("class") in OWN_CLASSES:
            continue
        if w.get("hidden") or w.get("mapped") is False:
            continue
        ws = (w.get("workspace") or {}).get("id")
        if visible and ws not in visible and not w.get("pinned"):
            continue
        size = w.get("size") or [0, 0]
        if size[0] < 50 or size[1] < 30:
            continue
        rank = w.get("focusHistoryID", 99)
        if rank is None or rank < 0:
            rank = 99
        if best is None or rank < best[0]:
            best = (rank, w)
    return best[1] if best else None


def _capture(geometry: str | None, dest: str) -> bool:
    base = ["grim"] + (["-g", geometry] if geometry else [])
    w, h = 0, 0
    if geometry:
        m = re.search(r"(\d+)x(\d+)$", geometry)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
    if geometry and 0 < w * h <= DOUBLE_BELOW_PIXELS:
        # small text is recognized much better at double resolution
        rc, _o, _e = S.run(base[:1] + ["-s", "2"] + base[1:] + [dest], timeout=15)
        if rc == 0:
            return True
    rc, _o, _e = S.run(base + [dest], timeout=15)
    return rc == 0


def _ocr_languages() -> str:
    """The system language and English, plus Italian when installed (the
    languages ZETA speaks), among the installed Tesseract models."""
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    try:
        from system import ocr
        langs = ocr.languages().split("+")
        if "ita" in ocr.installed() and "ita" not in langs:
            langs.append("ita")
        return "+".join(langs[:3])
    except Exception:  # noqa: BLE001 - English is always there
        return "eng"


def ocr(path: str) -> str:
    """Text recognition at low priority, at most two threads (like
    zeta-text-capture): the desktop must stay smooth."""
    env = dict(os.environ, OMP_THREAD_LIMIT="2")
    try:
        r = subprocess.run(["nice", "-n", "10", "tesseract", path, "stdout", "-l", _ocr_languages(),
                            "--psm", "3"], capture_output=True, text=True, timeout=OCR_SECONDS, env=env)
    except FileNotFoundError:
        raise ReadError(tr("Text recognition (tesseract) is not installed.")) from None
    except subprocess.TimeoutExpired:
        raise ReadError(tr("Reading the text on the screen took too long. Try with a smaller "
                           "window.")) from None
    if r.returncode != 0:
        raise ReadError(tr("I couldn't recognize the text on the screen."))
    return r.stdout


def screen_text() -> Document:
    """The text of the window in front (or of the whole screen)."""
    w = target_window()
    geometry, source = None, tr("the screen")
    if w:
        (x, y), (wd, ht) = w.get("at") or (0, 0), w.get("size") or (0, 0)
        geometry = "%d,%d %dx%d" % (x, y, wd, ht)
        title = (w.get("title") or "").strip()
        source = title[:80] or w.get("class") or source
    fd, png = tempfile.mkstemp(prefix="zeta-screen-", suffix=".png")
    os.close(fd)
    try:
        if not (_capture(geometry, png) or (geometry and _capture(None, png))):
            raise ReadError(tr("I couldn't capture the screen."))
        text = ocr(png)
    finally:
        try:
            os.unlink(png)
        except OSError:
            pass
    return Document("screen", source, clean(text))


# Files: how much is read at most (the model reads a few thousand characters
# anyway; the rest would only cost time and memory).
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PDF_PAGES = 40
TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log", ".json", ".xml",
                 ".yaml", ".yml", ".ini", ".conf", ".tex", ".srt", ".vtt", ".py", ".sh", ".c",
                 ".h", ".cpp", ".js", ".ts", ".css", ".java", ".go", ".rs", ".lua", ".sql")
HTML_SUFFIXES = (".html", ".htm", ".xhtml")
# document -> (members to read, in order; a regex for numbered parts)
ZIP_DOCUMENTS = {
    ".docx": ("word/document.xml",),
    ".odt": ("content.xml",),
    ".odp": ("content.xml",),
    ".ods": ("content.xml",),
    ".pptx": (r"ppt/slides/slide(\d+)\.xml",),
}


def _xml_text(xml: str) -> str:
    """The text of an office XML part: paragraphs and line breaks become
    new lines, every tag is dropped, entities are decoded. A regular
    expression, not an XML parser: nothing in the file is interpreted."""
    xml = re.sub(r"<(?:w:br|w:cr|text:line-break|a:br)\b[^>]*/?>", "\n", xml)
    xml = re.sub(r"<(?:w:tab|text:tab)\b[^>]*/?>", "\t", xml)
    xml = re.sub(r"</(?:w:p|text:p|text:h|a:p|p|h\d|li|div|tr|br)>|<br\s*/?>", "\n", xml)
    xml = re.sub(r"<(?:script|style)\b.*?</(?:script|style)>", " ", xml, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _zip_text(path: str, members) -> str:
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        raise ReadError(tr("The file looks damaged: I couldn't open it.")) from None
    with z:
        names = z.namelist()
        chosen = []
        for m in members:
            rx = re.compile(m + r"$")
            hits = [n for n in names if rx.match(n)]
            if rx.groups:                      # slide2 before slide10
                hits.sort(key=lambda n: int(rx.match(n).group(1)))
            chosen += hits
        pieces, used = [], 0
        for n in chosen:
            if used >= MAX_FILE_BYTES:
                break
            try:
                with z.open(n) as f:
                    # never more than the limit, whatever the file claims:
                    # a «zip bomb» cannot fill the memory
                    data = f.read(MAX_FILE_BYTES - used)
            except (OSError, zipfile.BadZipFile, RuntimeError):
                continue
            used += len(data)
            pieces.append(_xml_text(data.decode("utf-8", "replace")))
        return "\n".join(pieces)


def _pdf_text(path: str) -> str:
    try:
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", "-l", str(MAX_PDF_PAGES), path, "-"],
                           capture_output=True, timeout=60)
    except FileNotFoundError:
        raise ReadError(tr("PDF reading (pdftotext) is not installed.")) from None
    except subprocess.TimeoutExpired:
        raise ReadError(tr("Reading the PDF took too long.")) from None
    if r.returncode != 0:
        raise ReadError(tr("I couldn't read this PDF (it may be damaged or protected by a password)."))
    return r.stdout[:MAX_FILE_BYTES].decode("utf-8", "replace")


def file_text(path: str) -> Document:
    name = os.path.basename(path)
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".pdf":
        return Document("file", name, clean(_pdf_text(path)))
    if suffix in ZIP_DOCUMENTS:
        return Document("file", name, clean(_zip_text(path, ZIP_DOCUMENTS[suffix])))
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_FILE_BYTES)
    except OSError as e:
        raise ReadError(tr("I can't read “{name}”: {error}").format(
            name=name, error=e.strerror or e)) from None
    if suffix not in TEXT_SUFFIXES + HTML_SUFFIXES and b"\0" in data[:4096]:
        raise ReadError(tr("I can only read text documents: plain text, PDF, Word and "
                           "LibreOffice files. “{name}” is not one of them.").format(name=name))
    text = data.decode("utf-8", "replace")
    if suffix in HTML_SUFFIXES:
        text = _xml_text(text)
    return Document("file", name, clean(text))


def clean(text: str) -> str:
    """Spaces and empty lines squeezed: they cost tokens and say nothing."""
    text = (text or "").replace("\f", "\n").replace("\r", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if out and not blank:
                out.append("")
            blank = True
            continue
        out.append(ln)
        blank = False
    return "\n".join(out).strip()


def has_words(text: str) -> bool:
    """At least a few real words: text recognition on a picture returns a
    handful of stray letters, which are not text to summarize."""
    return len(re.findall(r"[^\W\d_]{3,}", text or "")) >= 3


# --- how much of it the model reads ----------------------------------------
# On a processor every token is read before the first word of the answer:
# the document gets about READ_SECONDS of reading at the speed measured on
# this computer (resources.prompt_speed), between MIN_TOKENS and MAX_TOKENS,
# and never more than the context window leaves after the fixed prompt, the
# note and the answer.
READ_SECONDS = 25
MIN_TOKENS = 400
MAX_TOKENS = 3000
UNKNOWN_TOKENS = 1200
SYSTEM_TOKENS = 450          # the fixed system prompt (about 310) and a margin
OVERHEAD_TOKENS = 150        # the request, the note, the frame around the text
ANSWER_TOKENS = 450          # a summary or a translation needs room
CHARS_PER_TOKEN = 4          # as memory.approx_tokens


def budget(context: int = 0, answer: int = ANSWER_TOKENS) -> int:
    """Tokens of document text the local model is given."""
    from .resources import prompt_speed
    rate = prompt_speed()
    tokens = int(rate * READ_SECONDS) if rate > 0 else UNKNOWN_TOKENS
    tokens = max(MIN_TOKENS, min(MAX_TOKENS, tokens))
    if context and context > 0:
        room = context - SYSTEM_TOKENS - OVERHEAD_TOKENS - answer
        tokens = min(tokens, max(MIN_TOKENS // 2, room))
    return tokens


def trim(text: str, tokens: int) -> tuple[str, bool]:
    """The beginning of the text that fits `tokens`, cut at a line or
    sentence end when possible; (text, True) when something was left out."""
    limit = max(1, tokens) * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    for sep in ("\n", ". ", " "):
        k = cut.rfind(sep)
        if k > limit * 0.7:
            cut = cut[:k + (1 if sep == ". " else 0)]
            break
    return cut.rstrip(), True


def frame(doc: Document, text: str, cut: bool) -> str:
    """The document as the model reads it (English, like the notes: small
    models follow English instructions better; the answer still follows the
    language of the request)."""
    if doc.kind == "screen":
        head = ("[Text read from the user's screen (window: %s) by text recognition; it may "
                "contain recognition mistakes. You cannot see images, only this text.]" % doc.source)
    else:
        head = "[Text of the file “%s”.]" % doc.source
    tail = "[Only the beginning of the text: the rest was left out.]" if cut else ""
    return "\n".join(x for x in (head, '"""', text, '"""', tail) if x)
