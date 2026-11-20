# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS: Do Not Disturb and the notification history (mako).

No GTK here (zeta-selftest uses it too). The D-Bus calls are made by the
panel (ui/notification_view.py) with Gio, asynchronously.

mako keeps the last notifications in memory (max-history in its config) but
has no "clear history" command. "Clear" therefore remembers, for this mako
process, the newest notification id at that moment, and the panel hides the
older ones. A new mako process (after a restart) starts with an empty
history and ids from 1 again: the mark of the old process no longer applies.
"""
import json
import os

DND_FILE = os.path.expanduser("~/.config/zeta/do-not-disturb")
DND_MODE = "do-not-disturb"
BUS_NAME = "org.freedesktop.Notifications"
MAKO_PATH = "/fr/emersion/Mako"
MAKO_IFACE = "fr.emersion.Mako"


def _marker():
    run = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return os.path.join(run, "zeta", "notifications-cleared")


def cleared_mark():
    """(mako pid, newest id when "Clear" was pressed) or (0, 0)."""
    try:
        with open(_marker()) as f:
            d = json.load(f)
        return int(d.get("pid", 0)), int(d.get("id", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0, 0


def mark_cleared(pid, newest_id):
    path = _marker()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"pid": int(pid), "id": int(newest_id)}, f)


def not_cleared(items, pid):
    """The notifications (dicts with "id") still to show, newest first."""
    mark_pid, mark_id = cleared_mark()
    keep = [n for n in items
            if not (pid and mark_pid == pid and int(n.get("id", 0)) <= mark_id)]
    return sorted(keep, key=lambda n: int(n.get("id", 0)), reverse=True)


def dnd_saved():
    """The saved choice (what the session applies at login)."""
    try:
        with open(DND_FILE) as f:
            return f.read().strip() == "1"
    except OSError:
        return False
