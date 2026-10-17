# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS: may a launcher (.desktop file) on the Desktop run directly?

A .desktop file is a program: its Exec= line runs any command. One that
arrives from a download, an e-mail or an archive must not run with a
double-click (or by dropping a file on it) just because it sits on the
Desktop. The rule is the one of GNOME and the file managers:

  - a launcher runs directly when it is executable by the user AND marked
    as trusted (metadata::trusted = "true", the GIO attribute GNOME uses).
    The shortcuts ZETA RAYS creates ("Add to Desktop", programs dropped on
    the Desktop, App Shortcut…) are written that way (applications.py);
  - a link to an entry of the system ("Send to › Desktop" of an app in
    /usr/share/applications or of a program installed in /opt by root) is
    trusted: the user could not have written that file;
  - anything else asks first ("Trust and Launch"); trusting sets the
    executable bit and the attribute, so it asks only once.

The executable bit alone is not enough: archives (tar, zip from Linux) keep
it, so an extracted launcher would run without a question.
"""
from __future__ import annotations

import os
import stat

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

TRUSTED = "metadata::trusted"
GROUP = "Desktop Entry"
# keys only ZETA RAYS writes into the shortcuts it creates (applications.py)
OWN_KEYS = ("X-ZETA-App", "X-ZETA-Origin")


def _system_entry(real_path: str, st) -> bool:
    """Owned by root and not writable by the user, nor its folder."""
    return (st.st_uid == 0 and os.getuid() != 0
            and not os.access(real_path, os.W_OK)
            and not os.access(os.path.dirname(real_path), os.W_OK))


def has_trust_mark(path: str) -> bool:
    try:
        info = Gio.File.new_for_path(path).query_info(TRUSTED, Gio.FileQueryInfoFlags.NONE, None)
    except GLib.Error:
        return False
    return info.get_attribute_string(TRUSTED) == "true"


def is_trusted(path: str) -> bool:
    """True if the launcher at path (or the entry it links to) may run
    without asking."""
    real_path = os.path.realpath(path)
    try:
        st = os.stat(real_path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if _system_entry(real_path, st):
        return True
    if not st.st_mode & stat.S_IXUSR or not os.access(real_path, os.X_OK):
        return False
    return has_trust_mark(path)


def mark_trusted(path: str) -> None:
    """The user chose "Trust and Launch": executable bit (on the user's own
    file) and the trust attribute. Raises OSError or GLib.Error."""
    real_path = os.path.realpath(path)
    st = os.stat(real_path)
    if not st.st_mode & stat.S_IXUSR:
        if st.st_uid != os.getuid():
            raise PermissionError(1, os.strerror(1), real_path)
        os.chmod(real_path, st.st_mode | stat.S_IXUSR)
    Gio.File.new_for_path(path).set_attribute_string(
        TRUSTED, "true", Gio.FileQueryInfoFlags.NONE, None)


def created_by_zeta(path: str) -> bool:
    """A launcher written by ZETA RAYS itself (a regular file of the user
    with the X-ZETA-App or X-ZETA-Origin key)."""
    if os.path.islink(path):
        return False
    try:
        if os.stat(path).st_uid != os.getuid():
            return False
    except OSError:
        return False
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(path, GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return False
    for key in OWN_KEYS:
        try:
            if kf.get_string(GROUP, key):
                return True
        except GLib.Error:
            continue
    return False


def trust_own_shortcuts(folder: str) -> bool:
    """One-time migration: the shortcuts ZETA RAYS created before this check
    existed (some lost the executable bit when the app registry rewrote
    them) keep starting without a question. True if every one was marked."""
    try:
        names = os.listdir(folder)
    except OSError:
        return True
    ok = True
    for n in names:
        p = os.path.join(folder, n)
        if not n.endswith(".desktop") or not created_by_zeta(p) or is_trusted(p):
            continue
        try:
            mark_trusted(p)
        except (OSError, GLib.Error):
            ok = False
    return ok


def exec_line(path: str) -> str:
    """The Exec= command of the launcher, to show the user what would run."""
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(os.path.realpath(path), GLib.KeyFileFlags.NONE)
        return kf.get_string(GROUP, "Exec") or ""
    except GLib.Error:
        return ""
