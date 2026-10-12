# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — folder accent colors (like Finder's folder colors on macOS).

A color is stored as GIO metadata of the folder itself, kept by gvfsd-metadata
in ~/.local/share/gvfs-metadata: it survives restarts, works with any folder
name (spaces, accents, symbols) and never touches the folder's contents, name,
dates or permissions.

Two attributes are written:
  metadata::zeta-folder-color   the color key, read by the ZETA RAYS Desktop,
                                which draws the folder icon in that color
  metadata::emblems             emblem-zeta-folder-<key>, which the file
                                manager (Thunar) draws as a colored dot on the
                                folder icon; other emblems are kept

Thunar has no per-folder icon support, so there the color is the dot.
"""
from __future__ import annotations

import os

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

KEY = "metadata::zeta-folder-color"
EMBLEMS = "metadata::emblems"
EMBLEM_PREFIX = "emblem-zeta-folder-"
FOLDER_ICONS = "/usr/share/zeta/folders"

# key -> (fill color, English name). White has a grey outline in the artwork
# so that it stays visible on light backgrounds.
COLORS = {
    "red": ("#C8102E", "Red"),
    "white": ("#FFFFFF", "White"),
    "green": ("#4CC94A", "Green"),
    "blue": ("#3A8DFF", "Blue"),
    "purple": ("#A855F7", "Purple"),
}


def name(key: str) -> str:
    """Translated color name (the strings are spelled out for tools/i18n.py)."""
    from i18n import tr
    return {"red": tr("Red"), "white": tr("White"), "green": tr("Green"),
            "blue": tr("Blue"), "purple": tr("Purple")}.get(key, key)


def _info(gfile: Gio.File) -> Gio.FileInfo:
    return gfile.query_info("%s,%s,standard::type" % (KEY, EMBLEMS),
                            Gio.FileQueryInfoFlags.NONE, None)


def get(path: str) -> str | None:
    """The color key of a folder, or None."""
    try:
        value = _info(Gio.File.new_for_path(path)).get_attribute_string(KEY)
    except GLib.Error:
        return None
    return value if value in COLORS else None


def icon_path(key: str | None) -> str | None:
    """The colored folder icon (SVG) for the Desktop, if the color is valid."""
    if key not in COLORS:
        return None
    p = os.path.join(FOLDER_ICONS, "folder-%s.svg" % key)
    return p if os.path.isfile(p) else None


def set_color(path: str, key: str | None) -> tuple[bool, str]:
    """Give a folder a color, or reset it with key None. (ok, error message)"""
    if key is not None and key not in COLORS:
        return False, "unknown color: %s" % key
    gfile = Gio.File.new_for_path(path)
    try:
        info = _info(gfile)
    except GLib.Error as e:
        return False, e.message
    if info.get_file_type() != Gio.FileType.DIRECTORY:
        return False, "not a folder: %s" % path
    emblems = [e for e in (info.get_attribute_stringv(EMBLEMS) or [])
               if not e.startswith(EMBLEM_PREFIX)]
    if key is not None:
        emblems.append(EMBLEM_PREFIX + key)
    try:
        if key is None:
            gfile.set_attribute(KEY, Gio.FileAttributeType.INVALID, None,
                                Gio.FileQueryInfoFlags.NONE, None)
        else:
            gfile.set_attribute_string(KEY, key, Gio.FileQueryInfoFlags.NONE, None)
        if emblems:
            # PyGObject cannot pass a string list to set_attribute(): go
            # through a FileInfo, which can
            new = Gio.FileInfo()
            new.set_attribute_stringv(EMBLEMS, emblems)
            gfile.set_attributes_from_info(new, Gio.FileQueryInfoFlags.NONE, None)
        else:
            gfile.set_attribute(EMBLEMS, Gio.FileAttributeType.INVALID, None,
                                Gio.FileQueryInfoFlags.NONE, None)
    except (GLib.Error, TypeError, ValueError) as e:
        return False, getattr(e, "message", str(e))
    _announce(path)
    return True, ""


def _announce(path: str) -> None:
    """Let open file manager windows redraw the folder at once.

    Thunar does not watch GIO metadata. Writing the folder's own access and
    modification times back unchanged raises an "attributes changed" event
    (inotify IN_ATTRIB) and Thunar reloads the folder's information; the
    visible dates, contents and permissions stay exactly the same. A folder
    the user cannot write keeps its color all the same: it shows up the next
    time the file manager reads the folder."""
    try:
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        pass
