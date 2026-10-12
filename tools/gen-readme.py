#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the release README.txt from the docs/README-2.0.txt.in template.

Sizes and SHA-256 sums are read from the images and the .sha256 files in the
release folder, and the kernel version from the build log: nothing is copied
by hand.

  tools/gen-readme.py RELEASE_FOLDER
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = ["amd64.iso", "arm64.iso", "amd64.ova", "arm64.ova"]


def main(dest):
    text = open(os.path.join(ROOT, "docs", "README-2.0.txt.in"), encoding="ascii").read()
    for name in IMAGES:
        f = os.path.join(dest, "zetarays-2.0-%s" % name)
        n = os.path.getsize(f)
        text = text.replace("{SIZE_%s}" % name, "{:,} bytes ({:.2f} GB)".format(n, n / 1e9))
        sha = open(f + ".sha256").read().split()[0]
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            sys.exit("invalid checksum in %s.sha256" % f)
        text = text.replace("{SHA_%s}" % name, sha)
    log = open(os.path.join(ROOT, "out", "run-arm64.log"), errors="replace").read()
    m = re.findall(r"linux-image-(\d+\.\d+\.\d+)\+deb13", log)
    if not m:
        sys.exit("kernel version not found in the build log")
    text = text.replace("{KERNEL}", m[-1])
    rest = re.findall(r"\{[A-Za-z_0-9.]+\}", text)
    if rest:
        sys.exit("unfilled placeholders: %s" % rest)
    for i, line in enumerate(text.split("\n"), 1):
        if len(line) > 79 or any(ord(c) > 127 for c in line):
            sys.exit("line %d is not ASCII or is longer than 79" % i)
    open(os.path.join(dest, "README.txt"), "w", encoding="ascii").write(text)
    print("README.txt written (kernel %s)" % m[-1])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Desktop/ZETA RAYS 2.0"))
