# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS: open files with a chosen app (Open With, drop onto an app icon).

Everything goes through GIO, exactly like the file manager, so the Desktop
and Thunar always agree:
  - which apps can open a type comes from the MimeType= key of the installed
    .desktop files (Gio.AppInfo.get_all_for_type, parent types included:
    a text editor that declares text/plain also opens a .py file);
  - the default app comes from mimeapps.list, and "Always use this app"
    writes ~/.config/mimeapps.list with Gio.AppInfo.set_as_default_for_type;
  - the launch is done by Gio.DesktopAppInfo, which expands the Exec= field
    codes (%f %F %u %U) itself and starts the program without a shell, so
    names with spaces, quotes, "$" or accents arrive intact.
There is no association list of our own.

No user-visible text here: the callers (zeta-desktop) word the messages.
"""
from __future__ import annotations

import os
import subprocess

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

# Entries that declare file types but are not a sensible choice for the
# user: the Desktop itself and ImageMagick's X11 viewer.
EXCLUDED = {"zeta-desktop.desktop", "display-im6.q16.desktop", "display-im7.q16.desktop"}

# MimeType= values some apps use to say "any file" (not in the standard,
# but GNOME and KDE apps ship them)
_ANY = {"all/all", "all/allfiles", "*/*", "*"}

FALLBACK_TYPE = "application/octet-stream"


def content_type(path: str) -> str:
    """The content type of a file (following symbolic links), as the file
    manager sees it: "inode/directory" for a folder."""
    try:
        info = Gio.File.new_for_path(path).query_info(
            "standard::content-type,standard::fast-content-type",
            Gio.FileQueryInfoFlags.NONE, None)
        return (info.get_content_type()
                or info.get_attribute_string("standard::fast-content-type")
                or FALLBACK_TYPE)
    except GLib.Error:
        guessed, _uncertain = Gio.content_type_guess(path, None)
        return guessed or FALLBACK_TYPE


def can_open(app, ctype: str) -> bool:
    """True if the app declares (MimeType=) this type, an alias of it or a
    type it derives from (text/x-python is a text/plain; every file that is
    not a folder is an application/octet-stream)."""
    for declared in app.get_supported_types() or []:
        declared = declared.strip()
        if not declared:
            continue
        if declared in _ANY:
            if declared == "all/allfiles" and ctype == "inode/directory":
                continue
            return True
        if Gio.content_type_equals(ctype, declared) or Gio.content_type_is_a(ctype, declared):
            return True
    return False


def split(app, paths) -> tuple:
    """(paths the app can open, paths it cannot), keeping the order."""
    good, bad = [], []
    for p in paths:
        (good if can_open(app, content_type(p)) else bad).append(p)
    return good, bad


def visible(app) -> bool:
    """Listed in "Open With": the same rule as the file manager. NoDisplay=
    entries stay (they hide file-type helpers from the app menu, not from
    "Open With"); OnlyShowIn=/NotShowIn= are honored."""
    if (app.get_id() or "") in EXCLUDED:
        return False
    if isinstance(app, Gio.DesktopAppInfo):
        return bool(app.get_show_in(None))
    return True


def default_for(ctype: str):
    return Gio.AppInfo.get_default_for_type(ctype, False)


def apps_for(types) -> list:
    """Apps that can open every one of the given content types, as
    [(app, is_default)]: the default app of the first type first, then the
    others in GIO's order (recommended ones, then those that only declare a
    parent type). Like Thunar's "Open With" submenu."""
    types = list(dict.fromkeys(t for t in types if t))
    if not types:
        return []
    default = default_for(types[0])
    candidates = ([default] if default is not None else []) + list(Gio.AppInfo.get_all_for_type(types[0]))
    # the other types: only apps that can open those too
    allowed = None
    for t in types[1:]:
        ids = {a.get_id() for a in Gio.AppInfo.get_all_for_type(t)}
        allowed = ids if allowed is None else allowed & ids
    out, seen = [], set()
    for a in candidates:
        aid = a.get_id() or a.get_name()
        if aid in seen or not visible(a):
            continue
        seen.add(aid)
        if allowed is not None and a.get_id() not in allowed:
            continue
        out.append((a, default is not None and a.equal(default)))
    return out


def all_apps() -> list:
    """Every app that can be chosen in "Other Application…" (the menu's
    apps: NoDisplay= entries are left out here, as there is no file type to
    justify them), sorted by name."""
    apps = [a for a in Gio.AppInfo.get_all()
            if a.should_show() and (a.get_id() or "") not in EXCLUDED]
    return sorted(apps, key=lambda a: (a.get_display_name() or a.get_name() or "").casefold())


def user_apps_folder() -> str:
    return os.path.join(GLib.get_user_data_dir(), "applications")


def refresh_mime_cache(folder: str | None = None) -> bool:
    """Rebuild mimeinfo.cache in the user's applications folder when an
    entry there is newer than it. GLib (2.84, Debian 13) finds the apps for
    a file type only through that cache, not by reading MimeType= of each
    entry (tested): without it an AppImage or a program in /opt was missing
    from "Open With" in the file manager and on the Desktop, even though it
    declares the type. True if the cache was rebuilt."""
    folder = folder or user_apps_folder()
    cache = os.path.join(folder, "mimeinfo.cache")
    try:
        cache_time = os.stat(cache).st_mtime
    except OSError:
        cache_time = None
    try:
        times = [e.stat().st_mtime for e in os.scandir(folder)
                 if e.name.endswith(".desktop") and e.is_file()]
    except OSError:
        return False
    if not times and cache_time is None:
        return False
    if times and cache_time is not None and max(times) <= cache_time:
        return False
    try:
        r = subprocess.run(["update-desktop-database", "-q", folder], timeout=30,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def app_from_keyfile(kf):
    """A Gio.DesktopAppInfo from a GLib.KeyFile (a Desktop launcher with its
    paths already resolved), or None if GIO refuses it."""
    if kf is None:
        return None
    try:
        return Gio.DesktopAppInfo.new_from_keyfile(kf)
    except (GLib.Error, TypeError):
        return None


def launch(app, paths, context=None) -> tuple:
    """Open the files with the app. GIO expands the field codes: %f/%u start
    one instance per file, %F/%U one for all, and an Exec= without codes
    gets the file appended. (ok, error message)."""
    files = [Gio.File.new_for_path(os.path.abspath(p)) for p in paths]
    try:
        ok = app.launch(files, context)
    except GLib.Error as e:
        return False, e.message
    return bool(ok), ""


def set_default(app, ctype: str) -> tuple:
    """Make the app the default for this type (in ~/.config/mimeapps.list),
    then read it back: (ok, error message)."""
    if not app.get_id():
        return False, "no application id"
    try:
        app.set_as_default_for_type(ctype)
    except GLib.Error as e:
        return False, e.message
    now = default_for(ctype)
    if now is not None and now.get_id() == app.get_id():
        return True, ""
    return False, "not saved"
