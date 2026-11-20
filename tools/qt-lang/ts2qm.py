#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile a Qt .ts file into a .qm file without Qt (for the Mac).

    python3 tools/qt-lang/ts2qm.py IN.ts OUT.qm
    python3 tools/qt-lang/ts2qm.py --check IN.ts EXISTING.qm

Writes the same bytes as `lrelease -silent` (Qt 6) for the files of this
folder: plain messages (no plurals), one context, no disambiguation
comments. Anything else is refused, so a .ts that needs more features fails
loudly instead of producing a wrong file; then use lrelease (build.sh).
Unfinished and obsolete translations are left out, as lrelease does.

Format (QTranslator): magic, then tagged blocks: language (0xa7), hash
table (0x42: elfHash(source + comment) -> offset, sorted), messages (0x69:
translation as UTF-16BE, empty comment, source and context as UTF-8, end
tag), numerus rules (0x88).
"""
import struct
import sys
import xml.etree.ElementTree as ET

MAGIC = bytes.fromhex("3cb86418caef9c95cd211cbf60a1bddd")
TAG_END, TAG_TRANSLATION, TAG_SOURCE, TAG_CONTEXT, TAG_COMMENT = 1, 3, 6, 7, 8
# numerus rules of the languages shipped (from Qt's numerus.cpp)
NUMERUS = {"it": b"\x01\x01", "en": b"\x01\x01"}


def elf_hash(data):
    h = 0
    for c in data:
        h = ((h << 4) + c) & 0xFFFFFFFF
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
        h &= ~g & 0xFFFFFFFF
    return h or 1


def read_ts(path):
    root = ET.parse(path).getroot()
    language = root.get("language") or ""
    messages = []
    for ctx in root.findall("context"):
        name = ctx.findtext("name") or ""
        for m in ctx.findall("message"):
            if m.get("numerus") == "yes" or m.find("comment") is not None:
                raise SystemExit("ts2qm: plurals and comments need lrelease (%s)" % path)
            tr = m.find("translation")
            if tr is None or tr.get("type") in ("unfinished", "vanished", "obsolete"):
                continue
            messages.append((name, m.findtext("source") or "", tr.text or ""))
    return language, messages


def block(tag, data):
    return struct.pack(">BI", tag, len(data)) + data


def compile_qm(language, messages):
    # lrelease keeps the messages ordered by (context, source, comment)
    msgs = sorted(((c.encode(), s.encode(), t) for c, s, t in messages),
                  key=lambda m: (m[0], m[1]))
    body, hashes = b"", []
    for ctx, src, trans in msgs:
        hashes.append((elf_hash(src), len(body)))
        body += block(TAG_TRANSLATION, trans.encode("utf-16-be"))
        body += block(TAG_COMMENT, b"")
        body += block(TAG_SOURCE, src)
        body += block(TAG_CONTEXT, ctx)
        body += bytes([TAG_END])
    table = b"".join(struct.pack(">II", h, o) for h, o in sorted(hashes))
    lang = language.split("_")[0]
    if lang not in NUMERUS:
        raise SystemExit("ts2qm: no numerus rules for %r: use lrelease" % language)
    return (MAGIC + block(0xA7, language.encode("latin-1")) + block(0x42, table)
            + block(0x69, body) + block(0x88, NUMERUS[lang]))


def main(argv):
    check = argv[1:2] == ["--check"]
    args = argv[2:] if check else argv[1:]
    if len(args) != 2:
        print(__doc__.strip().splitlines()[2:4], file=sys.stderr)
        return 2
    data = compile_qm(*read_ts(args[0]))
    if check:
        same = open(args[1], "rb").read() == data
        print("%s: %s" % (args[1], "up to date" if same else "DIFFERENT"))
        return 0 if same else 1
    with open(args[1], "wb") as f:
        f.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
