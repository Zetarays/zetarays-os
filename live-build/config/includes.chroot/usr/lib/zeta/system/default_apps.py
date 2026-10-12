# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — default applications (browser, mail, files, terminal...).

The choice is written where every program reads it, not in a file of our own:
  - for file types and addresses (browser, mail, files, editor, video,
    images, PDF) in ~/.config/mimeapps.list, through the GIO functions: it is
    used by xdg-open, gio open, Firefox, Thunar and the Desktop;
  - for the terminal, which has no file type, in
    ~/.config/xdg-terminals.list (the xdg-terminal-exec standard, also used
    by GLib for "terminal" apps); the ZETA RAYS shortcuts go through
    "zeta-default-app terminal", which reads the same file.
After every write the value is read back: we only say "done" if the system
really answers with the chosen app.
"""
from __future__ import annotations

import os

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from i18n import tr  # noqa: E402

TERMINALS_LIST = os.path.expanduser("~/.config/xdg-terminals.list")

# category: (title, types to set, preferred .desktop category, fallback app)
CATEGORIES = {
    "browser": (tr("Browser"), ["x-scheme-handler/https", "x-scheme-handler/http", "text/html",
                            "application/xhtml+xml"], "WebBrowser", "firefox-esr.desktop"),
    "mail": (tr("Mail"), ["x-scheme-handler/mailto", "message/rfc822"], "Email", "thunderbird.desktop"),
    "file": (tr("File Manager"), ["inode/directory"], "FileManager", "thunar.desktop"),
    "terminal": (tr("Terminal"), [], "TerminalEmulator", "foot.desktop"),
    "editor": (tr("Text Editor"), ["text/plain", "text/markdown", "text/x-python", "application/x-shellscript",
                                   "application/json", "text/csv"], "TextEditor", "org.gnome.TextEditor.desktop"),
    "video": (tr("Music and Video"), ["video/mp4", "video/x-matroska", "video/webm", "video/quicktime",
                                 "video/x-msvideo", "audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav",
                                 "audio/mp4", "audio/aac"], "Player", "mpv.desktop"),
    "images": (tr("Images"), ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
                              "image/tiff", "image/svg+xml"], "Viewer", "org.gnome.eog.desktop"),
    "pdf": ("PDF", ["application/pdf"], "Viewer", "org.gnome.Evince.desktop"),
}
ORDER = ["browser", "mail", "file", "terminal", "editor", "video", "images", "pdf"]
# helper apps that claim to handle the type but are not a sensible choice
EXCLUDED = {"footclient.desktop", "foot-server.desktop", "zeta-desktop.desktop", "zeta-text-capture.desktop",
           "thunar-bulk-rename.desktop", "thunar-settings.desktop", "display-im6.q16.desktop"}


# The apps' proper names: here the user chooses between programs, and the
# dock's short names («File», «Documenti») described the role, not the app.
PROPER_NAMES = {
    "firefox-esr.desktop": "Firefox", "thunderbird.desktop": "Thunderbird", "thunar.desktop": "Thunar",
    "foot.desktop": "Foot", "org.gnome.TextEditor.desktop": tr("GNOME Text Editor"),
    "mpv.desktop": "mpv", "org.gnome.eog.desktop": "Eye of GNOME", "org.gnome.Evince.desktop": "Evince",
    "org.xfce.mousepad.desktop": "Mousepad", "debian-xterm.desktop": "XTerm", "debian-uxterm.desktop": "UXTerm",
    "chromium.desktop": "Chromium", "org.gnome.Nautilus.desktop": "Nautilus", "vlc.desktop": "VLC",
}


def app_name(aid: str, app=None) -> str:
    if aid in PROPER_NAMES:
        return PROPER_NAMES[aid]
    app = app or Gio.DesktopAppInfo.new(aid)
    return (app.get_name() or app.get_display_name()) if app else aid


def _categories(app) -> list:
    return [c for c in (app.get_categories() or "").split(";") if c]


def candidates(cat: str) -> list:
    """The installed apps that can do that job: [(id, name, icon)]."""
    _t, types, preferred, _r = CATEGORIES[cat]
    seen, out = set(), []
    if cat == "terminal":
        all_apps = [a for a in Gio.AppInfo.get_all() if "TerminalEmulator" in _categories(a)]
    else:
        all_apps = Gio.AppInfo.get_all_for_type(types[0])
        if cat == "mail":
            all_apps = [a for a in all_apps if "Email" in _categories(a) or a.get_id() == "thunderbird.desktop"]
    for a in all_apps:
        aid = a.get_id() or ""
        if aid in seen or aid in EXCLUDED or not a.should_show():
            continue
        seen.add(aid)
        icon = a.get_icon().to_string() if a.get_icon() else ""
        out.append((aid, app_name(aid, a), icon, preferred in _categories(a)))
    # apps made for that job first (a browser before an editor)
    out.sort(key=lambda x: (not x[3], x[1].lower()))
    return [(i, n, ic) for i, n, ic, _p in out]


def _chosen_terminal() -> str | None:
    try:
        with open(TERMINALS_LIST) as f:
            for line in f:
                line = line.split("#")[0].strip()
                if line.endswith(".desktop") and Gio.DesktopAppInfo.new(line) is not None:
                    return line
    except OSError:
        pass
    return None


def current(cat: str) -> str | None:
    """The .desktop id of the default app for the category (None if none)."""
    if cat == "terminal":
        return _chosen_terminal() or (CATEGORIES[cat][3] if Gio.DesktopAppInfo.new(CATEGORIES[cat][3]) else None)
    a = Gio.AppInfo.get_default_for_type(CATEGORIES[cat][1][0], False)
    return a.get_id() if a else None


def set_default(cat: str, app_id: str) -> tuple:
    """(ok, message). Write the choice and verify it by reading it back."""
    if cat not in CATEGORIES:
        return False, tr("Unknown category: {category}").format(category=cat)
    app = Gio.DesktopAppInfo.new(app_id)
    if app is None:
        return False, tr("The application {app} is not installed.").format(app=app_id)
    title = CATEGORIES[cat][0]
    app_label = app_name(app_id, app)
    if cat == "terminal":
        try:
            os.makedirs(os.path.dirname(TERMINALS_LIST), exist_ok=True)
            tmp = TERMINALS_LIST + ".tmp"
            with open(tmp, "w") as f:
                f.write("# chosen in Settings › Default Apps\n%s\n" % app_id)
            os.replace(tmp, TERMINALS_LIST)
        except OSError as e:
            return False, tr("Could not save the choice: {error}").format(error=e.strerror or e)
        ok = _chosen_terminal() == app_id
    else:
        supported = set(app.get_supported_types() or [])
        types = CATEGORIES[cat][1]
        errors = []
        for t in types:
            # only the types the app can open (the http scheme always goes with the browser)
            if t != types[0] and supported and t not in supported and not t.startswith("x-scheme-handler/"):
                continue
            try:
                app.set_as_default_for_type(t)
            except Exception as e:  # noqa: BLE001 - GLib.Error
                errors.append("%s (%s)" % (t, e))
        verify = Gio.AppInfo.get_default_for_type(types[0], False)
        ok = bool(verify and verify.get_id() == app_id) and not errors
    if ok:
        return True, tr("{app} is now the default app for: {category}.").format(app=app_label, category=title)
    return False, tr("Could not make {app} the default app for: {category}.").format(
        app=app_label, category=title)


def launch(cat: str, arguments=()) -> tuple:
    """Open the category's default app (with files or addresses)."""
    aid = current(cat) or CATEGORIES.get(cat, ("", [], "", ""))[3]
    app = Gio.DesktopAppInfo.new(aid) if aid else None
    if app is None:
        return False, tr("No default app for {category}.").format(category=CATEGORIES.get(cat, (cat,))[0])
    uris = []
    for a in arguments:
        if "://" in a or a.startswith(("mailto:", "data:")):
            uris.append(a)
        else:
            uris.append(Gio.File.new_for_path(os.path.abspath(a)).get_uri())
    try:
        ok = app.launch_uris(uris, None)
    except Exception as e:  # noqa: BLE001 - GLib.Error
        return False, tr("Could not open {app}: {error}").format(app=app.get_display_name(), error=e)
    return bool(ok), app.get_display_name()
