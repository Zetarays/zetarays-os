# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS: system snapshots (Timeshift, rsync mode on ext4).

A snapshot is a copy of the system files (not the personal folders) that
Timeshift can bring back if an update or a change breaks something. Taking
one needs the administrator: /usr/libexec/zeta-snapshot does it through
pkexec, with a fixed set of arguments. Reading the list needs no password:
Timeshift keeps each snapshot in /timeshift/snapshots/<date>/ with an
info.json readable by everyone.

Used by Settings > Backup and by Software Update ("Snapshot before each
system update").
"""
import datetime
import json
import os
import shutil
import subprocess

from i18n import language, tr

HELPER = "/usr/libexec/zeta-snapshot"
SNAPSHOT_DIR = "/timeshift/snapshots"
PREF = os.path.expanduser("~/.config/zeta/snapshot-before-update")
LIVE_MEDIUM = "/run/live/medium"
# the description written by the helper: it tells the automatic snapshots
# (kept to the last three) from the ones the user asked for
AUTO_COMMENT = "ZETA RAYS: before update"
MANUAL_COMMENT = "ZETA RAYS: created in Settings"


def is_live():
    return os.path.exists(LIVE_MEDIUM)


def installed():
    return shutil.which("timeshift") is not None and os.access(HELPER, os.X_OK)


def before_update_enabled():
    """The user's choice in Settings > Backup (off unless turned on)."""
    try:
        with open(PREF, encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def set_before_update(on):
    os.makedirs(os.path.dirname(PREF), exist_ok=True)
    with open(PREF, "w", encoding="utf-8") as f:
        f.write("1\n" if on else "0\n")


def before_update_wanted():
    """Software Update takes a snapshot first only when it can work: an
    installed system, Timeshift present and the option turned on."""
    return before_update_enabled() and installed() and not is_live()


def listing():
    """[{"name", "time" (datetime or None), "comment", "auto", "manual"}], newest first.

    Empty when there is no snapshot or the folder cannot be read."""
    out = []
    try:
        names = os.listdir(SNAPSHOT_DIR)
    except OSError:
        return out
    for name in names:
        info = {}
        try:
            with open(os.path.join(SNAPSHOT_DIR, name, "info.json"), encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            pass
        when = None
        try:
            when = datetime.datetime.fromtimestamp(int(info.get("created", "")))
        except (TypeError, ValueError, OverflowError, OSError):
            try:
                when = datetime.datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
            except ValueError:
                pass
        comment = str(info.get("comments", "") or "")
        out.append({"name": name, "time": when, "comment": comment,
                    "auto": comment == AUTO_COMMENT, "manual": comment == MANUAL_COMMENT})
    out.sort(key=lambda s: s["name"], reverse=True)
    return out


def create(kind):
    """Take a snapshot now ("manual" or "before-update"). Blocks: call it in a
    thread. Returns (ok, message); message is None when the user closed the
    password window."""
    if kind not in ("manual", "before-update"):
        return False, tr("Unknown action.")
    if is_live():
        return False, tr("Snapshots need ZETA RAYS installed on the computer.")
    if not installed():
        return False, tr("Timeshift is not installed.")
    try:
        r = subprocess.run(["pkexec", HELPER, "--lang=%s" % language(), "create", kind],
                           capture_output=True, text=True, timeout=3 * 3600)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode == 126:                  # password window closed
        return False, None
    try:
        outcome = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        outcome = {}
    if r.returncode == 0:
        return True, tr("Snapshot created.")
    if r.returncode == 127 and not r.stdout.strip():
        return False, tr("The change needs an administrator's password, and it was not accepted.")
    return False, outcome.get("error") or tr("The snapshot could not be created.")
