#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find process matches that can hit the wrong program.

    tools/check-process-names.py

`pgrep -f` / `pkill -f` match a regular expression anywhere in the command
line. A pattern such as "/usr/local/bin/zeta-desktop" also matches
"/usr/local/bin/zeta-desktop-session", and killing that one ends the whole
graphical session. A pattern that names a ZETA RAYS program must not be a
plain prefix of another program's name: anchor it ("...zeta-desktop$",
"...zeta-desktop( |$)") or name the longer program exactly.

Exit code 1 when a risky pattern is found.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROOT = os.path.join(ROOT, "live-build", "config", "includes.chroot")
BIN_DIRS = ("usr/local/bin", "usr/libexec", "usr/local/libexec")
# pgrep/pkill with -f, in shell or in a Python argument list
CALL = re.compile(r"""(?:\b(?:pgrep|pkill)\b[^\n|;&]*?\s-[a-zA-Z]*f[a-zA-Z]*\s+(?:-[a-zA-Z]+\s+\S+\s+)*(['"])(.*?)\1)"""
                  r"""|(?:\[\s*["'](?:pgrep|pkill)["'][^\]]*?["']-f["'],\s*(?:[^,\]]+,\s*)*?["']([^"']+)["'])""")


def programs():
    names = set()
    for d in BIN_DIRS:
        p = os.path.join(CHROOT, d)
        if os.path.isdir(p):
            names.update(n for n in os.listdir(p) if n.startswith("zeta"))
    return names


def risky(pattern, names):
    """Names the pattern would match besides the one it meant."""
    hits = []
    for longer in names:
        for shorter in names:
            if shorter == longer or not longer.startswith(shorter + "-"):
                continue
            # the pattern names `shorter` and is not anchored right after it
            m = re.search(re.escape(shorter) + r"(?![-\w])(.?)", pattern)
            if m and m.group(1) not in ("$", "(", " ", "\\"):
                try:
                    if re.search(pattern, "/usr/bin/python3 /usr/local/bin/" + longer):
                        hits.append(longer)
                except re.error:
                    hits.append(longer)
    return sorted(set(hits))


def main():
    names = programs()
    problems = 0
    for base in (CHROOT, os.path.join(ROOT, "live-build", "config", "hooks"), os.path.join(ROOT, "tools")):
        for d, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", "ollama")]
            for f in files:
                path = os.path.join(d, f)
                try:
                    text = open(path, encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    continue
                if "pgrep" not in text and "pkill" not in text:
                    continue
                for m in CALL.finditer(text):
                    pattern = m.group(2) or m.group(3)
                    if not pattern or "zeta" not in pattern:
                        continue
                    hits = risky(pattern, names)
                    if hits:
                        line = text.count("\n", 0, m.start()) + 1
                        print("%s:%d: %r also matches %s" % (os.path.relpath(path, ROOT), line,
                                                              pattern, ", ".join(hits)))
                        problems += 1
    print("process names: %s (%d problem(s))" % ("OK" if not problems else "FAILED", problems),
          file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
