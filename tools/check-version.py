#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that the release version has a single source: the VERSION file.

    tools/check-version.py [-v]

Checks:
- VERSION exists and holds a version number (e.g. 2.1);
- no stale release version is hard-coded anywhere: image names
  (zetarays-X.Y), download folders (releases/X.Y), product names
  ("ZETA RAYS X.Y", "OS X.Y") and fallbacks such as VERSION_ID", "X.Y"
  must use the version in VERSION (most files read it at build or run time
  and contain no number at all);
- the website links point to releases/<VERSION>/.../zetarays-<VERSION>-*:
  the four images and the two upgrade files (ARCH/upgrade/).

Not checked (history, not the current release):
- CHANGELOG.md below the first section;
- the snapshots of the website as it was published (seo-zetarays/original-live,
  seo-zetarays/seo-optimized) and the SEO audit that describes them;
- the 2.0 settings migration (english-2.0.json, migrated-english-2.0), which
  names that migration, not the release;
- the lines listed in ALLOWED below, each with its reason.

Names and texts in Italian (an archive name, lines of the Italian legal texts,
the Italian word for "version" on the web pages) are in data/check-version.json.

Files regenerated at release time by tools/sync-site.sh (the site's
README.txt and SHA256SUMS, also copied into an SEO build made before the
release step) only produce warnings.

Exit code 1 when a check fails.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "tools", "data", "check-version.json"), encoding="utf-8") as _f:
    DATA = json.load(_f)

SKIP_DIRS = {".git", ".cache", "out", "cache", "node_modules", "__pycache__", "src-2.0-release"}
SKIP_FILES = set(DATA["skip_files"])  # existing archives
# Historical copies, never published
SKIP_PATHS = {"site-zetarays/index-original.html"}
# Snapshots of a website already published (the live site downloaded before
# the SEO work, the optimized copy deployed from it) and the audit that
# describes them: they show the release that was online at the time
SKIP_PREFIXES = ("seo-zetarays/original-live/", "seo-zetarays/seo-optimized/",
                 "seo-zetarays/SEO_AUDIT/")
MAX_SIZE = 4 * 1024 * 1024

# (path relative to the repository, text contained in the line): reason
ALLOWED = {
    ("live-build/config/includes.chroot/usr/share/zeta/legal/PRIVACY.md",
     "Last updated: with ZETA RAYS OS 2.0."):
        "legal text: the version in which the policy last changed",
    ("live-build/config/includes.chroot/usr/share/zeta/legal/TERMS.md", "*ZETA RAYS OS 2.0*"):
        "legal text: the version in which the terms last changed",
    ("live-build/config/includes.chroot/usr/share/zeta/legal/TERMS.it.md", "*ZETA RAYS OS 2.0*"):
        "legal text: the version in which the terms last changed",
    ("live-build/config/includes.chroot/usr/local/bin/zeta-selftest", "ZETA RAYS 1.7, late September"):
        "history: the release in which these tests were added",
    ("tools/check-version.py", ""):
        "this file names old versions on purpose",
    ("docs/MIGRATION-2.5.md", ""):
        "the migration guide names the previous release on purpose",
    ("live-build/config/includes.chroot/usr/share/zeta/docs/MIGRATION-2.5.md", ""):
        "the migration guide names the previous release on purpose",
    ("tools/data/check-version.json", ""):
        "the data of this check names old versions on purpose",
}
ALLOWED.update({(path, text): why for path, text, why in DATA["allowed"]})

# Generated at release time from the delivery folder: warnings only
RELEASE_GENERATED = {"site-zetarays/README.txt", "site-zetarays/SHA256SUMS"}
# ...and their copies in the input and output of an SEO build
# (seo-zetarays/tools/build_optimized.py) made before the release step
RELEASE_GENERATED_COPY = re.compile(r"^seo-zetarays/(original|seo-optimized)-[0-9.]+/(README\.txt|SHA256SUMS)$")

V = r"(\d+\.\d+(?:\.\d+)?)"
PATTERNS = [
    re.compile(r"zetarays-" + V + r"(?![\d.]*\d)"),
    re.compile(r"releases/" + V + r"/"),
    re.compile(r"\bZETA RAYS " + V + r"\b"),
    re.compile(r"\bOS " + V + r"\b"),
    re.compile(r"VERSION_ID\"?,\s*\"" + V + r"\""),
    re.compile(r"ZETA-RAYS/" + V),
]
# Web pages only ("Download · version X.Y"): elsewhere "version X.Y" often
# names other software or licenses
PAGE_PATTERNS = [re.compile(p + V + r"\b") for p in DATA["page_patterns"]]
PAGES = re.compile(r"^(site-zetarays/[^/]+\.html|live-build/config/includes\.chroot/usr/share/zetarays/start/.*\.html)$")
# The 2.0 migration keeps its name (it names that migration, not the release)
MIGRATION = re.compile(r"english-2\.0\.json|migrated-english-2\.0")


def read_version():
    path = os.path.join(ROOT, "VERSION")
    try:
        text = open(path, encoding="ascii").read().strip()
    except (OSError, UnicodeDecodeError):
        return None, "VERSION is missing or unreadable"
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", text):
        return None, "VERSION does not hold a version number: %r" % text
    return text, None


def text_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name in SKIP_FILES:
                continue
            path = os.path.join(base, name)
            if os.path.islink(path) or os.path.getsize(path) > MAX_SIZE:
                continue
            try:
                data = open(path, "rb").read()
            except OSError:
                continue
            if b"\0" in data:
                continue
            rel = os.path.relpath(path, ROOT)
            if rel not in SKIP_PATHS and not rel.startswith(SKIP_PREFIXES):
                yield rel, data.decode("utf-8", "replace")


def current_changelog(text):
    """Only the first '## ' section of the changelog is the current release."""
    heads = [m.start() for m in re.finditer(r"^## ", text, re.M)]
    if len(heads) < 2:
        return text
    return text[:heads[1]]


def allowed(rel, line):
    return any(rel == p and s in line for (p, s) in ALLOWED)


def main(argv):
    verbose = "-v" in argv
    version, err = read_version()
    if err:
        print("version: %s" % err)
        print("version: FAILED (1 problem(s))", file=sys.stderr)
        return 1
    problems, warnings = [], []
    for rel, text in text_files():
        if rel == "CHANGELOG.md":
            text = current_changelog(text)
            first = re.search(r"^## .*$", text, re.M)
            if not first or not re.match(r"## %s\b" % re.escape(version), first.group(0)):
                problems.append("CHANGELOG.md: the first section is not '## %s'" % version)
        for n, line in enumerate(text.split("\n"), 1):
            if allowed(rel, line):
                continue
            clean = MIGRATION.sub("", line)
            pats = PATTERNS + PAGE_PATTERNS if PAGES.match(rel) else PATTERNS
            stale = sorted({m.group(1) for pat in pats for m in pat.finditer(clean)} - {version})
            if stale:
                msg = "%s:%d: stale version %s: %s" % (rel, n, ", ".join(stale), line.strip()[:120])
                generated = rel in RELEASE_GENERATED or RELEASE_GENERATED_COPY.match(rel)
                (warnings if generated else problems).append(msg)

    site = os.path.join(ROOT, "site-zetarays", "index.html")
    if os.path.exists(site):
        links = re.findall(r'href="(https://download\.zetarays\.org/[^"]+)"', open(site, encoding="utf-8").read())
        v = re.escape(version)
        image = re.compile(r"https://download\.zetarays\.org/releases/%s/(amd64|arm64)/(iso|ova)/"
                           r"zetarays-%s-\1\.\2$" % (v, v))
        upgrade = re.compile(r"https://download\.zetarays\.org/releases/%s/(amd64|arm64)/upgrade/"
                             r"zetarays-%s-upgrade-\1\.run$" % (v, v))
        images = [link for link in links if image.match(link)]
        upgrades = [link for link in links if upgrade.match(link)]
        if len(set(images)) != 4:
            problems.append("site-zetarays/index.html: expected 4 image download links, found %d" % len(images))
        if len(set(upgrades)) != 2:
            problems.append("site-zetarays/index.html: expected 2 upgrade download links, found %d"
                            % len(upgrades))
        for link in links:
            if link not in images and link not in upgrades:
                problems.append("site-zetarays/index.html: download link not for %s: %s" % (version, link))

    per_file = {}
    for line in warnings:
        per_file.setdefault(line.split(":", 1)[0], []).append(line)
    for rel, lines in sorted(per_file.items()):
        print("version: warning: %s: %d line(s) with an old version (regenerated by "
              "tools/sync-site.sh at release)" % (rel, len(lines)))
        if verbose:
            for line in lines:
                print("version:   %s" % line)
    for line in problems:
        print("version: %s" % line)
    if verbose:
        for (p, s), why in sorted(ALLOWED.items()):
            print("version: allowed: %s (%s)" % (p, why))
    print("version: %s %s (%d problem(s), %d warning(s))"
          % ("OK" if not problems else "FAILED", version, len(problems), len(per_file)),
          file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
