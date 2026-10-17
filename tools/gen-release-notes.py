#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write the text of a GitHub release: the newest section of CHANGELOG.md
followed by the downloads table (links, sizes, SHA-256 checksums).

    tools/gen-release-notes.py CHANGELOG.md DELIVERY_DIR OUTPUT.md

DELIVERY_DIR holds the four images and their .sha256 files, as written by
tools/build-all.sh deliver. The version comes from the VERSION file; the
newest changelog section must be the one of that version.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://download.zetarays.org/releases"
IMAGES = [("amd64", "iso"), ("amd64", "ova"), ("arm64", "iso"), ("arm64", "ova")]


def newest_section(text):
    m = re.search(r"^## .*?(?=^## |\Z)", text, re.S | re.M)
    if not m:
        sys.exit("no '## ' section in the changelog")
    return m.group(0).rstrip() + "\n"


def read_version():
    v = open(os.path.join(ROOT, "VERSION"), encoding="ascii").read().strip()
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", v):
        sys.exit("VERSION does not hold a version number: %r" % v)
    return v


def version_of(section):
    m = re.match(r"## (\S+)", section)
    return m.group(1) if m else ""


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__)
    changelog, delivery, output = argv[1:]
    section = newest_section(open(changelog, encoding="utf-8").read())
    version = read_version()
    if version_of(section) != version:
        sys.exit("the newest changelog section is %r, VERSION is %s"
                 % (version_of(section), version))
    if "(filled at release)" in section or re.match(r"## .*XX", section):
        sys.exit("the changelog section of %s still has placeholders (date or list)" % version)
    rows = []
    for arch, kind in IMAGES:
        name = "zetarays-%s-%s.%s" % (version, arch, kind)
        path = os.path.join(delivery, name)
        try:
            digest = open(path + ".sha256").read().split()[0]
        except (OSError, IndexError):
            sys.exit("missing checksum: %s.sha256" % path)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            sys.exit("not a SHA-256 checksum in %s.sha256" % path)
        size = os.path.getsize(path) / 1e9
        rows.append("| [`%s`](%s/%s/%s/%s/%s) | %.2f GB | `%s` |"
                    % (name, BASE, version, arch, kind, name, size, digest))
    text = (section + "\n### Downloads\n\n| File | Size | SHA-256 |\n|---|---|---|\n"
            + "\n".join(rows) + "\n\nVerify a download with `sha256sum -c FILE.sha256` (Linux), "
            "`shasum -a 256 -c FILE.sha256` (macOS) or `Get-FileHash FILE -Algorithm SHA256` "
            "(Windows PowerShell).\n")
    with open(output, "w", encoding="utf-8") as f:
        f.write(text)
    print("release notes written: %s (%d lines)" % (output, text.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
