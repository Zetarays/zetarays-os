#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the emoji list of the emoji picker (zeta-emoji).

    tools/gen-emoji-data.py [EMOJI_TEST_TXT] [OUTPUT_JSON]

Input: Unicode's emoji-test.txt, as shipped by Debian's `unicode-data`
package (/usr/share/unicode/emoji/emoji-test.txt, version 15.1 in trixie;
also at https://sources.debian.org/data/main/u/unicode-data/15.1.0-1/emoji/emoji-test.txt).
Output (default live-build/config/includes.chroot/usr/share/zeta/emoji.json):

    {"version": "15.1", "groups": [["Smileys & Emotion", "😀 grinning face\\n..."], ...]}

Only fully-qualified emoji are kept, in CLDR order. The "Component" group
and the skin tone variants are left out to keep the file small: the picker
shows the default (yellow) form, like the first page of a phone keyboard.
Each group is one string, one "emoji name" pair per line: much smaller and
faster to load than a list of objects.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IN = "/usr/share/unicode/emoji/emoji-test.txt"
DEFAULT_OUT = os.path.join(ROOT, "live-build/config/includes.chroot/usr/share/zeta/emoji.json")
SKIN_TONES = {0x1F3FB, 0x1F3FC, 0x1F3FD, 0x1F3FE, 0x1F3FF}
LINE = re.compile(r"^([0-9A-F ]+?)\s*;\s*([a-z-]+)\s*#\s*(\S+)\s+E[0-9.]+\s+(.+)$")


def parse(text):
    version = ""
    groups = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# Version:"):
            version = line.split(":", 1)[1].strip()
            continue
        if line.startswith("# group:"):
            groups.append((line.split(":", 1)[1].strip(), []))
            continue
        m = LINE.match(line)
        if not m or not groups:
            continue
        codes, status, _shown, name = m.groups()
        if status != "fully-qualified":
            continue
        cps = [int(c, 16) for c in codes.split()]
        if SKIN_TONES & set(cps):
            continue
        groups[-1][1].append(("".join(chr(c) for c in cps), name.strip()))
    groups = [(g, items) for g, items in groups if g != "Component" and items]
    return version, groups


def main(argv):
    src = argv[1] if len(argv) > 1 else DEFAULT_IN
    out = argv[2] if len(argv) > 2 else DEFAULT_OUT
    with open(src, encoding="utf-8") as f:
        version, groups = parse(f.read())
    if not groups:
        print("no emoji found in %s" % src, file=sys.stderr)
        return 1
    data = {"version": version,
            "groups": [[g, "\n".join("%s %s" % (e, n) for e, n in items)] for g, items in groups]}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    total = sum(len(items) for _g, items in groups)
    print("%s: %d emoji in %d groups (Unicode %s), %d bytes"
          % (out, total, len(groups), version, os.path.getsize(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
