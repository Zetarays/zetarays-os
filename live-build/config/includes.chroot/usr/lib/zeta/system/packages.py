# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — what apt can actually install, as reported by apt itself.

An "Install" button only makes sense if apt knows the package. Here apt is
asked, in a single call and without network access (it reads the indexes
already downloaded), for each package: the installed version and the
installable one. If a package has no candidate we explain why, instead of
leaving it to Synaptic to say "does not exist".
"""
import glob
import os
import subprocess
import time

from i18n import ntr, tr

APT_LISTS_DIR = "/var/lib/apt/lists"
STALE_AGE = 7 * 24 * 3600          # indexes older than a week: need updating

# Well-known packages that Debian 13 does not have. The Kali repositories are
# not added to get them: mixing Kali and Debian breaks both at the first
# upgrade (Kali says so itself), and the system stops updating.
REASONS = {
    "radare2": tr("Not in the system's software sources: its authors release new versions so "
                  "often that a stable release couldn't guarantee its security fixes."),
    "theharvester": tr("Only available in the Kali Linux repositories. Mixing them with the system's "
                       "software sources breaks updates, so ZETA RAYS doesn't do it."),
}


def availability(packages, timeout=20):
    """{package: {"installed": version|None, "candidate": version|None}}.

    A single apt-cache call for all of them. On error every package comes out
    as unknown (None, None): better no button than a false one.
    """
    result = {p: {"installed": None, "candidate": None} for p in packages}
    if not packages:
        return result
    try:
        r = subprocess.run(["apt-cache", "policy", "--"] + list(packages),
                           capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C.UTF-8", LANG="C.UTF-8"))
    except (OSError, subprocess.SubprocessError):
        return result
    current = None
    for line in r.stdout.splitlines():
        if line and not line[0].isspace() and line.endswith(":"):
            current = line[:-1]
            if current not in result:           # e.g. "pkg:arm64"
                current = current.split(":")[0]
            continue
        if current not in result:
            continue
        s = line.strip()
        if s.startswith("Installed:"):
            v = s.split(":", 1)[1].strip()
            result[current]["installed"] = None if v == "(none)" else v
        elif s.startswith("Candidate:"):
            v = s.split(":", 1)[1].strip()
            result[current]["candidate"] = None if v == "(none)" else v
    return result


def index_age():
    """Seconds since the last successful "apt update", None if there are no indexes."""
    index_files = glob.glob(os.path.join(APT_LISTS_DIR, "*_InRelease")) + glob.glob(os.path.join(APT_LISTS_DIR, "*_Release"))
    if not index_files:
        return None
    try:
        return max(0, time.time() - max(os.path.getmtime(f) for f in index_files))
    except OSError:
        return None


def describe_age(sec):
    if sec is None:
        return tr("never downloaded")
    days = int(sec // 86400)
    if days == 0:
        hours = int(sec // 3600)
        if not hours:
            return tr("just updated")
        return ntr("updated {n} hour ago", "updated {n} hours ago", hours).format(n=hours)
    return ntr("{n} day old", "{n} days old", days).format(n=days)


def stale_indexes():
    e = index_age()
    return e is None or e > STALE_AGE


def why_missing(package):
    """Explanation for a package with no candidate."""
    if package in REASONS:
        return REASONS[package]
    if stale_indexes():
        age = index_age()
        if age is None:
            return tr("Not found: the package list has never been downloaded. Update it and try again.")
        return tr("Not found in the package list, which is {age}: update it and try again.").format(
            age=describe_age(age))
    return tr("Not in the configured software sources.")


def repository():
    """The active "deb" lines, from sources.list, .list and .sources (deb822 format)."""
    lines = []
    for f in ["/etc/apt/sources.list"] + sorted(glob.glob("/etc/apt/sources.list.d/*.list")):
        try:
            for r in open(f, encoding="utf-8", errors="replace"):
                r = r.strip()
                if r.startswith("deb ") or r.startswith("deb-src "):
                    lines.append((os.path.basename(f), r))
        except OSError:
            pass
    for f in sorted(glob.glob("/etc/apt/sources.list.d/*.sources")):
        try:
            blocks = open(f, encoding="utf-8", errors="replace").read().split("\n\n")
        except OSError:
            continue
        for b in blocks:
            fields = {}
            for r in b.splitlines():
                if ":" in r and not r.startswith((" ", "#")):
                    k, v = r.split(":", 1)
                    fields[k.strip().lower()] = v.strip()
            if fields.get("enabled", "yes").lower() == "no" or "uris" not in fields:
                continue
            lines.append((os.path.basename(f), "%s %s %s %s" % (
                fields.get("types", "deb"), fields["uris"], fields.get("suites", ""),
                fields.get("components", ""))))
    return lines
