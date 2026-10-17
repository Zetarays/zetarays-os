#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find Italian left in the source: prose, identifiers, values, file names.

    tools/check-italian.py [--summary] [--all] [--only KIND,...] [PATH...]
                                        (default: the whole repository)

The project's source code, comments and developer documentation are written in
English. Four kinds of findings are reported:

  prose       a comment, docstring or documentation line written in Italian
  identifier  a name in code made of Italian words: variables, functions,
              classes, shell variables, f-string fields, CSS classes and ids,
              unit and config keys, or a dashed/underscored/file name quoted
              in a comment
  string      a string literal (or an unquoted shell word) containing Italian
  filename    a file or directory whose name is made of Italian words

Code files (Python, shell, Lua, QML/JS, CSS, systemd units, live-build hooks,
tools and tests) contain no Italian at all: any Italian word in their code,
strings, docstrings or comments is a finding, and no marker exempts it. Italian
words and phrases the system must recognize, say or show are data: they live
in JSON files (usr/share/zeta/i18n-data/*.json in the image, data/*.json next
to a build tool) and the code loads them.

Italian is allowed only in data files, where it is deliberate localization:

- po/*.po, the compiled translations, JSON files and the Calamares .ts catalogs;
- `Name[it]=`, `Comment[it]=`, Calamares `name[it]:`, `xml:lang="it"` and similar
  in configuration, desktop and markup files;
- bilingual pages (HTML): lines with a `data-en` attribute;
- Italian editions of documents (`*.it.md`) and plain-text word lists or
  documents with the marker `i18n-data-file` in their first lines;
- in documents and configuration files (not code), a line marked with the
  comment `i18n-data` or a block between `i18n-data-begin` and `i18n-data-end`.

The Italian vocabulary (function words and other words) is the word list
tools/check-italian-words.txt. In prose (documents, configuration comments) a
line is reported when it reads as Italian rather than English; in code a
single Italian word is enough. Paths ignored by the repository's .gitignore
(local drafts, the separate website repository) are skipped unless --all is
given; pass a path explicitly to check it anyway. --summary prints only the
number of findings per area and kind.
Exit code 1 when something is found.
"""
import fnmatch
import io
import keyword
import os
import re
import sys
import tokenize
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WORDS_FILE = os.path.join(HERE, "check-italian-words.txt")

ENGLISH = set("""
the and is are of to with for not this that when from it be on in an by or if
as at was which only has have can does do into its than then there these those
so but no all any one we you they their our will would should must may how
what why where who each every other here also just more most out up
""".split())

# never descended into
HARD_SKIP = {".git", "out", "cache", ".cache", "__pycache__", "node_modules", "po",
             "locale", "ollama", "piper-cache", "vosk-cache", ".DS_Store"}
# file names are checked, contents are not: generated or third-party material
CONTENT_SKIP = {"brand", "design", "kerno-design", "start", "hyprland-patched", "localsend"}
SKIP_EXT = (".png", ".jpg", ".jpeg", ".svg", ".pf2", ".mo", ".po", ".pot", ".ttf", ".otf",
            ".woff", ".woff2", ".gz", ".zst", ".onnx", ".tar", ".ico", ".webp", ".so", ".bin",
            ".zip", ".json", ".xcf", ".wav", ".mp3", ".qm", ".ts", ".deb", ".iso", ".ova",
            ".vmdk", ".pdf", ".ai", ".csv", ".pyc", ".sqlite")
PROSE_EXT = (".md", ".txt", ".rst")
HASH_EXT = (".sh", ".bash", ".py", ".conf", ".cfg", ".yml", ".yaml", ".nft", ".rules",
            ".service", ".timer", ".socket", ".target", ".path", ".mount", ".desktop",
            ".chroot", ".binary", ".pref", ".list", ".toml", ".ini", ".override",
            ".sources", ".theme", ".hook", ".preset", ".env", ".pkla")
SLASH_EXT = (".js", ".mjs", ".qml", ".css", ".script", ".c", ".h", ".cpp", ".hpp", ".jsonc",
             ".scss", ".vala", ".java", ".go", ".rs")
MARKUP_EXT = (".html", ".htm", ".xml", ".ui", ".policy", ".plist", ".xsl")

WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")
QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”|`[^`]*`|‘[^’]*’")
NAMEISH = re.compile(r"[A-Za-z_$][\w$]*(?:[-.][A-Za-z_]\w*)*")
ID_IN_TEXT = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+(?:\.[A-Za-z0-9]+)?"
                        r"|[A-Za-z0-9]+\.[a-z]{1,5}\b|[a-z]+[A-Z][A-Za-z0-9]*")
SH_VAR = re.compile(r"\$\{?([A-Za-z_]\w*)")
FIELD = re.compile(r"(?<!\{)\{([A-Za-z_]\w*)")


def load_words():
    """The sections of the word list: {"strong": set, "weak": set, "words": set}."""
    sections = {"strong": set(), "weak": set(), "words": set()}
    current = "words"
    try:
        for line in open(WORDS_FILE, encoding="utf-8"):
            s = line.strip()
            if s.startswith("#"):
                continue
            if s.startswith("[") and s.endswith("]"):
                current = s[1:-1]
                sections.setdefault(current, set())
                continue
            sections[current].update(w.lower() for w in s.split())
    except OSError:
        sys.exit("check-italian: %s is missing" % WORDS_FILE)
    return sections


_SECTIONS = load_words()
STRONG = _SECTIONS["strong"]     # function words that make a line Italian
WEAK = _SECTIONS["weak"]         # short function words, Italian only next to others
LEXICON = _SECTIONS["words"] | STRONG


# ------------------------------------------------------------------ scoring
def prose_score(text):
    it = en = 0.0
    for w in WORD.findall(QUOTED.sub(" ", text)):
        if len(w) > 1 and w.isupper():
            continue                       # acronyms (POI, IL, LAN...)
        lw = w.lower()
        if lw in ENGLISH:
            en += 1
        elif lw in STRONG or re.search(r"[àèìòù]$", lw):
            it += 1
        elif lw in LEXICON and not w[0].isupper():
            it += 1                        # capitalized: a name quoted in English
        elif lw in WEAK:
            it += 0.5
    return it, en


def is_prose(text, minimum=2):
    it, en = prose_score(text)
    return it >= minimum and it > en


def name_parts(name):
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return [p.lower() for p in re.split(r"[^A-Za-z]+", name) if p]


def italian_parts(name):
    return [p for p in name_parts(name) if len(p) >= 4 and p in LEXICON]


ESCAPE = re.compile(r"\\[A-Za-z]")              # \b, \s, \n... in regexes and strings
# a word ending with the only accented vowel it has (not a character range like
# a-zà-ÿ), or with a grave accent inside (Italian phonetic respellings)
ACCENTED = re.compile(r"[a-z]{2,}[àèìòù]|[a-z]+[àèìòù][a-z]+")


def italian_words(text):
    """Every Italian word of a code comment or string, in order.

    A word is Italian when it is an Italian function word, is in the
    vocabulary or ends with an accented vowel; the short function words count
    only next to another Italian word. Acronyms are skipped."""
    found, weak = [], []
    for token in WORD.findall(ESCAPE.sub(" ", text)):
        for w in re.sub(r"([a-zà-ÿ])([A-Z])", r"\1 \2", token).split():
            if len(w) > 1 and w.isupper():
                continue
            lw = w.lower()
            if lw in STRONG or (len(lw) >= 3 and lw in LEXICON) or ACCENTED.fullmatch(lw):
                found.append(w)
            elif lw in WEAK:
                weak.append(w)
    return found + weak if found else []


# the markers as words: a path or command name containing them (the data folder
# usr/share/zeta/i18n-data, /usr/libexec/zeta-i18n-data) is not a marker
MARKER = re.compile(r"(?<![\w/.-])i18n-data(?:-(begin|end|file))?(?![\w/.-])")


def marker(line, kind=None):
    """The line carries the i18n-data marker (kind None) or i18n-data-<kind>."""
    return any(m.group(1) == kind for m in MARKER.finditer(line))


def exempt(line, code=False):
    """Deliberate localization in data and configuration files. Code files
    (see is_code) have no exemptions: their language data lives in JSON."""
    if code:
        return False
    return bool(marker(line) or "xml:lang" in line or re.search(r"\bdata-en\s*=", line)
                or re.search(r"\[(it|it_IT)\]\s*[=:]", line))


# ------------------------------------------------------------------ findings
class Report:
    def __init__(self, kinds):
        self.kinds = kinds
        self.items = []
        self.code = False          # the file being scanned is code (is_code)

    def add(self, kind, path, n, text):
        if self.kinds and kind not in self.kinds:
            return
        self.items.append((path, n, kind, text.strip()[:120]))


def word_finding(rep, kind, path, n, text):
    """Code files: any Italian word is a finding."""
    words = italian_words(text)
    if words:
        rep.add(kind, path, n, "%s: %s" % (", ".join(dict.fromkeys(words)), text.strip()))
    return bool(words)


def comment_text(rep, path, n, text):
    """A comment line: Italian prose, or Italian names quoted in English prose."""
    if rep.code:
        if not word_finding(rep, "prose", path, n, text):
            bad = [t for t in ID_IN_TEXT.findall(text) if italian_parts(t)]
            if bad:
                rep.add("identifier", path, n, "in comment: " + ", ".join(sorted(set(bad))))
        return
    if exempt(text) or len(text.strip()) < 6:
        return
    if is_prose(text):
        rep.add("prose", path, n, text)
        return
    bad = [t for t in ID_IN_TEXT.findall(QUOTED.sub(" ", text)) if italian_parts(t)]
    if bad:
        rep.add("identifier", path, n, "in comment: " + ", ".join(sorted(set(bad))))


def string_value(rep, path, n, s):
    t = s.strip()
    if rep.code:
        word_finding(rep, "string", path, n, t)
        return
    if not t or exempt(t):
        return
    tokens = t.split()
    if len(tokens) <= 3 and all(re.fullmatch(r"[-\w./:=@+${}~*]+", x) for x in tokens):
        bad = sorted({x for x in tokens if italian_parts(x)})
        if bad:
            rep.add("string", path, n, "%r" % t[:80])
        return
    if len(t) >= 15 and is_prose(t, 3):
        rep.add("string", path, n, "%r" % t[:80])


def names(rep, path, n, found):
    bad = sorted({x for x in found if italian_parts(x) and not keyword.iskeyword(x)})
    if bad:
        rep.add("identifier", path, n, ", ".join(bad))
    return bool(bad)


# ------------------------------------------------------------------ line state
class Lines:
    """Line numbers excluded by i18n-data markers (never in code files)."""

    def __init__(self, lines, code=False):
        self.skip = set()
        if code:
            return
        inside = False
        for n, line in enumerate(lines, 1):
            if marker(line, "begin"):
                inside = True
            if inside or exempt(line):
                self.skip.add(n)
            if marker(line, "end"):
                inside = False


# ------------------------------------------------------------------ python
def scan_python(rep, path, text, lines, state):
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return scan_generic(rep, path, lines, state, "#")
    prev = None
    for i, tok in enumerate(toks):
        kind, value, (row, _col), (erow, _ec), _line = tok
        if row in state.skip:
            prev = tok if kind not in (tokenize.NL, tokenize.COMMENT) else prev
            continue
        if kind == tokenize.COMMENT:
            comment_text(rep, path, row, value.lstrip("#"))
        elif kind == tokenize.NAME:
            names(rep, path, row, [value])
        elif kind == tokenize.STRING or kind == getattr(tokenize, "FSTRING_MIDDLE", -1):
            nxt = toks[i + 1][0] if i + 1 < len(toks) else tokenize.ENDMARKER
            standalone = kind == tokenize.STRING and (
                prev is None or prev[0] in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)) \
                and nxt in (tokenize.NEWLINE, tokenize.ENDMARKER)
            body = re.sub(r"^[A-Za-z]*('''|\"\"\"|'|\")|('''|\"\"\"|'|\")$", "", value) \
                if kind == tokenize.STRING else value
            if standalone and rep.code:                     # docstring
                for k, line in enumerate(body.splitlines()):
                    word_finding(rep, "prose", path, row + k, line)
            elif standalone:
                for k, line in enumerate(body.splitlines()):
                    if row + k not in state.skip and len(line.strip()) >= 6 and is_prose(line):
                        rep.add("prose", path, row + k, line)
            elif row == erow or "\n" not in body:
                string_value(rep, path, row, body)
                if kind == tokenize.STRING and re.match(r"^[rRbB]*[fF]", value):
                    names(rep, path, row, FIELD.findall(body))
            else:
                for k, line in enumerate(body.splitlines()):
                    if rep.code:
                        word_finding(rep, "string", path, row + k, line)
                    elif row + k not in state.skip and len(line.strip()) >= 15 and is_prose(line, 3):
                        rep.add("string", path, row + k, line)
        if kind not in (tokenize.NL, tokenize.COMMENT):
            prev = tok


# ------------------------------------------------------------------ other code
STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`')


def split_trailing(code, marker):
    """Code and trailing comment (marker outside quotes, after a blank)."""
    quote = None
    i = 0
    while i < len(code):
        c = code[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif code.startswith(marker, i) and (i == 0 or code[i - 1] in " \t;"):
            if marker == "//" and code[max(0, i - 1):i] == ":":
                i += 1
                continue
            return code[:i], code[i + len(marker):]
        i += 1
    return code, None


def code_line(rep, path, n, code, shell):
    found = []
    for m in STRING_RE.finditer(code):
        s = m.group(0)
        inner = s[1:-1]
        if s[0] in "\"`":
            found += SH_VAR.findall(inner)
        string_value(rep, path, n, re.sub(r"\$\{?\w+\}?", "", inner) if shell else inner)
    rest = STRING_RE.sub(" ", code)
    if not shell:
        rest = re.sub(r"(?<=\w)-(?=\w)", " - ", rest)        # a-b is a subtraction
    found += NAMEISH.findall(rest)
    if not names(rep, path, n, [f.lstrip("$") for f in found]) and shell and rep.code:
        word_finding(rep, "string", path, n, rest)       # unquoted shell words


def scan_generic(rep, path, lines, state, marker, block=None):
    shell = marker == "#"
    in_block = False
    for n, line in enumerate(lines, 1):
        if n in state.skip:
            continue
        s = line.strip()
        if block:
            start, end = block
            if in_block or s.startswith(start):
                body = s
                if s.startswith(start):
                    body = s[len(start):]
                    in_block = True
                if end in body:
                    body = body[:body.index(end)]
                    in_block = False
                comment_text(rep, path, n, body.lstrip("*").strip())
                continue
        if s.startswith(marker) or (marker == "//" and s.startswith("*")):
            comment_text(rep, path, n, s.lstrip(marker[0]).lstrip(marker).lstrip("*"))
            continue
        if not s:
            continue
        code, comment = split_trailing(line, marker)
        if comment:
            comment_text(rep, path, n, comment)
        code_line(rep, path, n, code, shell)


def scan_markup(rep, path, lines, state):
    """HTML/XML: comments, class/id names, and the code in <style>/<script>."""
    in_comment = False
    section = None
    for n, line in enumerate(lines, 1):
        if n in state.skip:
            continue
        low = line.lower()
        if "<!--" in line or in_comment:
            body = line.split("<!--", 1)[-1]
            in_comment = "-->" not in body
            comment_text(rep, path, n, body.split("-->")[0])
            if in_comment or "-->" in line and not line.split("-->", 1)[1].strip():
                continue
        for m in re.finditer(r'\b(?:class|id|for|name)="([^"]*)"', line):
            names(rep, path, n, m.group(1).split())
        if "<style" in low:
            section = "style"
        elif "<script" in low and "src=" not in low:
            section = "script"
        if section and not re.match(r"\s*</?(style|script)", low):
            code, comment = split_trailing(line, "//")
            if comment:
                comment_text(rep, path, n, comment)
            code = re.sub(r"/\*.*?\*/", " ", code)
            if section == "style":
                names(rep, path, n, re.findall(r"[.#]([A-Za-z_][\w-]*)", re.sub(r"\{[^}]*\}?", "", code)))
            else:
                code_line(rep, path, n, code, False)
        if "</style" in low or "</script" in low:
            section = None


# ------------------------------------------------------------------ files
def language(path, head):
    base = os.path.basename(path)
    name = base[:-3] if base.endswith(".in") else base
    if name.endswith(".py") or re.match(r"#!.*python", head):
        return "python"
    if name.endswith(PROSE_EXT) or (base.isupper() and "." not in base):
        return "prose"
    if name.endswith(".lua"):
        return "lua"
    if name.endswith(SLASH_EXT):
        return "slash"
    if name.endswith(MARKUP_EXT):
        return "markup"
    if name.endswith(HASH_EXT) or head.startswith("#") or "." not in name:
        return "hash"
    return None


SHELL_EXT = (".sh", ".bash", ".service", ".timer", ".socket", ".target", ".path", ".mount",
             ".hook", ".hook.chroot", ".hook.binary")


def is_code(path, lang, head):
    """Code (Python, shell, Lua, QML/JS, CSS, systemd units, live-build hooks,
    tools): no Italian at all, not even marked. Everything else (documents,
    configuration, markup, word lists) may hold deliberate localization."""
    if lang in ("python", "lua", "slash"):
        return not path.endswith(".jsonc")
    if lang != "hash":
        return False
    base = os.path.basename(path)
    return (base.endswith(SHELL_EXT) or head.startswith("#!")
            or os.sep + "hooks" + os.sep in path)


def scan_file(rep, path):
    try:
        if os.path.getsize(path) > 3_000_000:
            return
        text = open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, OSError):
        return
    lines = text.splitlines()
    head = lines[0] if lines else ""
    lang = language(path, head)
    rep.code = is_code(path, lang, head)
    if not rep.code and (path.endswith(".it.md") or any(marker(x, "file") for x in lines[:5])):
        return
    state = Lines(lines, rep.code)
    if lang == "python":
        scan_python(rep, path, text, lines, state)
    elif lang == "prose":
        in_code = False
        for n, line in enumerate(lines, 1):
            if line.strip().startswith("```"):
                in_code = not in_code
            if n in state.skip or in_code or len(line.strip()) < 12:
                continue
            if is_prose(line):
                rep.add("prose", path, n, line)
    elif lang == "lua":
        scan_generic(rep, path, lines, state, "--", ("--[[", "]]"))
    elif lang == "slash":
        scan_generic(rep, path, lines, state, "//", ("/*", "*/"))
    elif lang == "markup":
        scan_markup(rep, path, lines, state)
    elif lang == "hash":
        scan_generic(rep, path, lines, state, "#")


def check_name(rep, path, seen):
    base = os.path.basename(path.rstrip("/"))
    stem = re.sub(r"(\.[A-Za-z0-9]{1,8})+$", "", base) or base
    if stem in seen:
        return
    if italian_parts(stem):
        seen.add(stem)
        rep.add("filename", path, 0, base)


def gitignore():
    """The repository's .gitignore as (pattern, anchored, dir_only) triples."""
    out = []
    try:
        lines = open(os.path.join(REPO, ".gitignore"), encoding="utf-8").read().splitlines()
    except OSError:
        return out
    for line in lines:
        s = line.strip()
        if not s or s.startswith(("#", "!")):
            continue
        dir_only = s.endswith("/")
        anchored = s.startswith("/") or "/" in s.rstrip("/")
        out.append((s.strip("/"), anchored, dir_only))
    return out


def ignored(path, is_dir, patterns):
    rel = os.path.relpath(os.path.abspath(path), REPO)
    if rel.startswith(".."):
        return False
    for pat, anchored, dir_only in patterns:
        if dir_only and not is_dir:
            continue
        if fnmatch.fnmatch(rel if anchored else os.path.basename(rel), pat):
            return True
    return False


def walk(rep, paths, patterns):
    seen = set()
    for p in paths:
        if os.path.isfile(p):
            check_name(rep, p, seen)
            scan_file(rep, p)
            continue
        for d, dirs, files in os.walk(p):
            dirs[:] = sorted(x for x in dirs if x not in HARD_SKIP
                             and not ignored(os.path.join(d, x), True, patterns))
            files = [f for f in files if not ignored(os.path.join(d, f), False, patterns)]
            for x in dirs:
                check_name(rep, os.path.join(d, x) + "/", seen)
            skip_content = any(part in CONTENT_SKIP for part in d.split(os.sep))
            for f in sorted(files):
                if f in HARD_SKIP or f.endswith(".pyc"):
                    continue
                full = os.path.join(d, f)
                check_name(rep, full, seen)
                if not skip_content and not f.endswith(SKIP_EXT) and not os.path.islink(full):
                    scan_file(rep, full)


def area(path):
    p = os.path.normpath(path).split(os.sep)
    if p and p[0] == ".":
        p = p[1:]
    chroot = ["live-build", "config", "includes.chroot"]
    if p[:3] == chroot:
        q = p[3:]
        depth = 3 if q[:1] == ["usr"] else 2
        return "~/" + "/".join(q[:depth]) if len(q) > depth else "~/" + "/".join(q[:-1] or q)
    if p[:2] == ["live-build", "config"] and len(p) > 3:
        return "/".join(p[:3])
    return p[0] if len(p) > 1 else "(top)"


def main(argv):
    args = argv[1:]
    summary = "--summary" in args
    kinds = set()
    if "--only" in args:
        i = args.index("--only")
        kinds = set(args[i + 1].split(","))
        del args[i:i + 2]
    patterns = [] if "--all" in args else gitignore()
    paths = [a for a in args if a not in ("--summary", "--all")] or ["."]
    rep = Report(kinds)
    walk(rep, paths, patterns)
    if summary:
        per = Counter((area(p), k) for p, _n, k, _t in rep.items)
        width = max([len(a) for a, _k in per] + [10])
        for a in sorted({a for a, _k in per}):
            counts = ", ".join("%s %d" % (k, per[(a, k)]) for k in
                               ("prose", "identifier", "string", "filename") if per[(a, k)])
            print("%-*s  %s" % (width, a, counts))
    else:
        for path, n, kind, text in rep.items:
            print("%s:%d: [%s] %s" % (path, n, kind, text))
    total = Counter(k for _p, _n, k, _t in rep.items)
    print("%d finding(s): %s" % (len(rep.items), ", ".join("%s %d" % kv for kv in sorted(total.items())) or "none"),
          file=sys.stderr)
    return 1 if rep.items else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
