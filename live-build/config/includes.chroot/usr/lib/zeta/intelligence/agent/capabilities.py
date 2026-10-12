# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA Core capabilities: real actions, each one with its own verification.

Every capability has:
  - a name (open_application, create_folder, ...) and its parameters;
  - a risk level: «read» (read-only, just looks), «normal» (changes
    something that is easy to undo: opening, moving, changing the volume) and
    «confirm» (must be asked first: deleting, shutting down, installing);
  - a function that runs the action AND checks the real state afterwards.
The result tells the truth: ok=True only if the verification confirmed it.

Adding a capability = writing a function and registering it below: the local
understanding, the model and the online services see it right away.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import Callable

from i18n import ntr, tr

from . import state as S


@dataclass
class Outcome:
    ok: bool
    message: str
    data: dict = field(default_factory=dict)


@dataclass
class Capability:
    name: str
    description: str
    parameters: dict                  # name -> description
    required: list
    risk: str                     # read | normal | confirm
    execute: Callable[[dict], Outcome]
    preview: Callable[[dict], str] | None = None
    # before the confirmation: None if we can proceed, otherwise the Outcome to
    # return right away (never ask "confirm?" for something that doesn't exist)
    check: Callable[[dict], "Outcome | None"] | None = None


REGISTRY: dict[str, Capability] = {}


def capabilities(name, description, parameters=None, required=(), risk="normal", preview=None,
             check=None):
    def dec(fn):
        REGISTRY[name] = Capability(name, description, parameters or {}, list(required),
                                  risk, fn, preview, check)
        return fn
    return dec


# What is missing, as told to the user ("I'm missing some information: ...").
# The parameter descriptions further below are meant for the models (in English).
def label(parameter):
    return {
        "app": tr("the app name (e.g. firefox, mail, terminal, settings)"),
        "name": tr("the name"),
        "item": tr("the file or folder"),
        "new_name": tr("the new name"),
        "destination": tr("the destination folder"),
        "text": tr("what to search for"),
        "folder": tr("the folder"),
        "url": tr("the address"),
        "theme": tr("light or dark"),
        "image": tr("the image or wallpaper"),
        "network": tr("the network name"),
        "role": tr("the role (browser, mail, files, terminal, editor, video, images or pdf)"),
        "device": tr("the device name"),
        "package": tr("the package name"),
    }.get(parameter, parameter)


def _sel(w):
    return "address:%s" % w["address"]


# ================================================================ APP
def _app_or_error(args):
    name = (args.get("app") or "").strip()
    if not name:
        return None, Outcome(False, tr("Which app?"))
    a = S.find_app(name)
    if a is None:
        return None, Outcome(False, tr("I can't find “{name}” among the installed apps.").format(name=name))
    return a, None


def _why_not():
    """The most common reason a window won't move: the screen is locked."""
    rc, _o, _e = S.run(["pgrep", "-x", "hyprlock"], timeout=3)
    return tr(" (the screen is locked: unlock it and try again)") if rc == 0 else ""


def _bring_forward(w):
    ws = str((w.get("workspace") or {}).get("name", ""))
    if ws.startswith("special:"):
        import sys
        sys.path.insert(0, "/usr/lib/zeta")
        from system import windows
        return windows.restore(w["address"])
    return S.dispatch('hl.dsp.focus({ window = "%s" })' % _sel(w))


@capabilities("open_application", "Opens an app (or brings it to the front if it is already open).",
          {"app": "app name, e.g. firefox, mail, terminal, settings"}, ["app"])
def open_application(args):
    # several installations of the same app: never pick one at random
    choice, question = choose_installation(args.get("app") or "")
    if question:
        return Outcome(False, question)
    if choice is not None:
        if _programs_module().reg.launch(choice):
            return Outcome(True, tr("I started {app} ({source}).").format(
                app=choice.name, source=_programs_module().reg.SOURCES.get(choice.source, choice.source)))
        return Outcome(False, tr("I can't start {app}.").format(app=choice.name))
    a, err = _app_or_error(args)
    if err:
        return err
    existing = S.windows_of(a)
    if existing:
        _bring_forward(existing[0])
        # actually check it: it used to claim success even with the screen locked
        if S.wait(lambda: (S.active_window() or {}).get("address") == existing[0]["address"], 3):
            return Outcome(True, tr("{app} was already open: I brought it to the front.").format(app=a.name))
        return Outcome(False, tr("{app} is open but I couldn't bring it to the front{reason}.").format(
            app=a.name, reason=_why_not()))
    if not a.argv or not shutil.which(a.argv[0]):
        return Outcome(False, tr("{app} appears to be installed but its program ({program}) is missing.").format(
            app=a.name, program=a.argv[:1]))
    try:
        S.launch(a.argv)
    except OSError as e:
        return Outcome(False, tr("I can't start {app}: {error}").format(app=a.name, error=e))
    if not S.desktop_active():
        return Outcome(True, tr("I started {app}.").format(app=a.name))
    # verification: one of its windows appears (Firefox, Thunderbird: a few seconds)
    if S.wait(lambda: S.windows_of(a), 25):
        return Outcome(True, tr("{app} is open.").format(app=a.name))
    if S.processes_of(a):
        return Outcome(True, tr("{app} has started; its window is still on the way.").format(app=a.name))
    return Outcome(False, tr("I tried to open {app} but it didn't start.").format(app=a.name))


def _close_windows(a, seconds=10):
    ww = S.windows_of(a)
    for w in ww:
        S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    return S.wait(lambda: not S.windows_of(a), seconds)


@capabilities("close_application", "Closes an app normally (it may ask to save).",
          {"app": "app name"}, ["app"])
def close_application(args):
    a, err = _app_or_error(args)
    if err:
        return err
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import windows
    ww = S.windows_of(a)
    if not ww:
        pids = S.processes_of(a)
        if not pids:
            return Outcome(True, tr("{app} isn't open.").format(app=a.name), {"already": True})
        # no windows (e.g. running in the background): ask it to quit (TERM),
        # never forcibly (KILL): that is "force quit", which needs confirmation
        for pid in pids:
            if not windows.is_protected(pid):
                windows.force_quit(pid, wait=4.0, force=False)
        ok = S.wait(lambda: not S.processes_of(a), 5)
        if ok:
            return Outcome(True, tr("{app} is closed.").format(app=a.name))
        return Outcome(False, tr("{app} didn't close by itself. If it's stuck, say “force quit {name}”.").format(
            app=a.name, name=a.name.lower()))
    if any(windows.is_protected(int(w.get("pid") or 0)) for w in ww):
        return Outcome(False, tr("{app} is part of the desktop: I won't close it.").format(app=a.name))
    if _close_windows(a, 10):
        # last window closed: the process exits by itself (Firefox saves the session)
        S.wait(lambda: not S.processes_of(a), 6)
        return Outcome(True, tr("{app} is closed.").format(app=a.name))
    remaining_windows = S.windows_of(a)
    titles = ", ".join((w.get("title") or "")[:40] for w in remaining_windows[:2])
    return Outcome(False, tr("{app} didn't close: it's probably asking something ({titles}). "
                           "If it's stuck, say “force quit {name}”.").format(
                               app=a.name, titles=titles, name=a.name.lower()),
                 {"open_windows": len(remaining_windows)})


@capabilities("force_close_application", "Force quits a frozen app, together with its child processes.",
          {"app": "app name"}, ["app"], risk="confirm",
          preview=lambda a: tr("Force quit {app} (unsaved work will be lost)").format(app=a.get("app", "")))
def force_close_application(args):
    a, err = _app_or_error(args)
    if err:
        return err
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import windows
    pids = {int(w["pid"]) for w in S.windows_of(a) if w.get("pid")} | set(S.processes_of(a))
    if not pids:
        return Outcome(True, tr("{app} isn't open.").format(app=a.name))
    for pid in pids:
        if windows.is_protected(pid):
            return Outcome(False, tr("{app} is part of the desktop: I won't close it.").format(app=a.name))
        windows.force_quit(pid, wait=3.0)
    ok = S.wait(lambda: not S.processes_of(a) and not S.windows_of(a), 5)
    return Outcome(ok, (tr("{app} was force quit.") if ok else
                      tr("{app} won't close even this way.")).format(app=a.name))


@capabilities("restart_application", "Closes and reopens an app.", {"app": "app name"}, ["app"])
def restart_application(args):
    a, err = _app_or_error(args)
    if err:
        return err
    if S.windows_of(a) or S.processes_of(a):
        c = close_application({"app": a.id})
        if not c.ok:
            return Outcome(False, tr("I didn't restart it: {reason}").format(reason=c.message))
        S.wait(lambda: not S.processes_of(a), 5)
    o = open_application({"app": a.id})
    return Outcome(o.ok, tr("{app} has been restarted.").format(app=a.name) if o.ok else o.message)


# ================================================================ WINDOWS
def _target_window(args):
    """The window of the given app, or else the active one."""
    if (args.get("app") or "").strip():
        a, err = _app_or_error(args)
        if err:
            return None, None, err
        ww = S.windows_of(a)
        if not ww:
            return a, None, Outcome(False, tr("{app} isn't open.").format(app=a.name))
        return a, ww[0], None
    w = S.active_window()
    if not w:
        return None, None, Outcome(False, tr("There's no active window."))
    return S.app_of_window(w), w, None


def _display_name(a, w):
    return a.name if a else (w.get("class") or tr("the window"))


@capabilities("focus_application", "Brings an open app to the front (switches to that app).",
          {"app": "app name"}, ["app"])
def focus_application(args):
    a, w, err = _target_window(args)
    if err:
        return err
    _bring_forward(w)
    ok = S.wait(lambda: (S.active_window() or {}).get("address") == w["address"], 3)
    return Outcome(ok, tr("You're now on {app}.").format(app=_display_name(a, w)) if ok else
                 tr("I couldn't switch to {app}{reason}.").format(app=_display_name(a, w), reason=_why_not()))


@capabilities("minimize_window", "Minimizes an app (or the active window).", {"app": "app name (optional)"})
def minimize_window(args):
    a, w, err = _target_window(args)
    if err:
        return err
    # same as the title bar button: snapshot for the bar, plus the animation
    S.run(["zeta-minimize", "minimize", w["address"]], timeout=10)
    ok = S.wait(lambda: any(x["address"] == w["address"] and
                               str(x["workspace"]["name"]).startswith("special:") for x in S.windows()), 3)
    return Outcome(ok, tr("{app} is minimized.").format(app=_display_name(a, w)) if ok else
                 tr("I couldn't minimize {app}{reason}.").format(app=_display_name(a, w), reason=_why_not()))


def _screen_state(w_addr):
    for x in S.windows():
        if x["address"] == w_addr:
            return x.get("fullscreen", 0)
    return None


@capabilities("maximize_window", "Maximizes (or restores) an app or the active window.",
          {"app": "app name (optional)"})
def maximize_window(args):
    a, w, err = _target_window(args)
    if err:
        return err
    before = _screen_state(w["address"])
    _bring_forward(w)
    S.dispatch('hl.dsp.window.fullscreen({ mode = "maximized", window = "%s" })' % _sel(w))
    ok = S.wait(lambda: _screen_state(w["address"]) != before, 3)
    now = _screen_state(w["address"])
    if not ok:
        return Outcome(False, tr("I couldn't maximize {app}.").format(app=_display_name(a, w)))
    return Outcome(True, (tr("{app} is maximized.") if now else
                        tr("{app} is back to its normal size.")).format(app=_display_name(a, w)))


@capabilities("fullscreen_window", "Toggles full screen for an app or the active window.",
          {"app": "app name (optional)"})
def fullscreen_window(args):
    a, w, err = _target_window(args)
    if err:
        return err
    before = _screen_state(w["address"])
    _bring_forward(w)
    S.dispatch('hl.dsp.window.fullscreen({ window = "%s" })' % _sel(w))
    ok = S.wait(lambda: _screen_state(w["address"]) != before, 3)
    now = _screen_state(w["address"])
    if not ok:
        return Outcome(False, tr("I couldn't toggle full screen for {app}.").format(app=_display_name(a, w)))
    return Outcome(True, (tr("{app} is in full screen.") if now else
                        tr("{app} is no longer in full screen.")).format(app=_display_name(a, w)))


@capabilities("close_window", "Closes the active window (not the whole app).", {})
def close_window(args):
    w = S.active_window()
    if not w:
        return Outcome(False, tr("There's no active window."))
    a = S.app_of_window(w)
    S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    ok = S.wait(lambda: all(x["address"] != w["address"] for x in S.windows()), 6)
    return Outcome(ok, (tr("I closed the {app} window.") if ok else
                      tr("The {app} window didn't close: it may be asking you to save.")).format(app=_display_name(a, w)))


@capabilities("list_running_applications", "Lists the apps that are open right now.", {}, risk="read")
def list_running_applications(args):
    names = []
    for w in S.windows():
        a = S.app_of_window(w)
        n = a.name if a else (w.get("class") or "?")
        minimized = str((w.get("workspace") or {}).get("name", "")).startswith("special:")
        n = tr("{app} (minimized)").format(app=n) if minimized else n
        if n not in names:
            names.append(n)
    if not names:
        return Outcome(True, tr("No apps are open."), {"app": []})
    return Outcome(True, tr("Open: {apps}.").format(apps=", ".join(names)), {"app": names})


@capabilities("list_installed_applications", "Lists the installed apps.", {}, risk="read")
def list_installed_applications(args):
    names = sorted({a.name for a in S.installed_apps() if not a.is_hidden}, key=str.lower)
    return Outcome(True, ntr("{n} app: {apps}.", "{n} apps: {apps}.", len(names)).format(
        n=len(names), apps=", ".join(names)), {"app": names})


@capabilities("is_installed", "Tells whether an app or a program is installed.",
          {"app": "name"}, ["app"], risk="read")
def is_installed(args):
    name = (args.get("app") or "").strip()
    a = S.find_app(name)
    if a:
        return Outcome(True, tr("Yes, {app} is installed.").format(app=a.name))
    if shutil.which(name):
        return Outcome(True, tr("Yes, the {command} command is installed ({path}).").format(
            command=name, path=shutil.which(name)))
    return Outcome(True, tr("No, “{name}” isn't installed. You can look for it with “install {name}”.").format(
        name=name), {"installed": False})


def _programs_module():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import programs
    return programs


@capabilities("where_is_program",
          "Tells where an installed program is and how to start it: every installation (APT, Flatpak, "
          "AppImage, /opt...), launch command, executable path, desktop entry, package and version; "
          "also command-line tools (nmap, git, python3) and system services.",
          {"app": "program or command name"}, ["app"], risk="read")
def where_is_program(args):
    name = (args.get("app") or "").strip()
    if not name:
        return Outcome(False, tr("Which program?"))
    found = _programs_module().find(name, services_too=True)
    if not found:
        return Outcome(True, tr("Nothing called “{name}” is installed.").format(name=name), {"found": []})
    lines = []
    for r in found[:8]:
        if r["kind"] == "app":
            lines.append(tr("{name} — app, {source}").format(name=r["name"], source=r["source_label"]))
            lines.append("  " + tr("start: {command}").format(command=r["launch"]))
            if r["path"]:
                lines.append("  " + tr("program: {path}").format(path=_short(r["path"])))
            lines.append("  " + tr("desktop entry: {path}").format(path=_short(r["desktop"])))
            if r["flatpak_id"]:
                lines.append("  " + tr("Flatpak ID: {id}").format(id=r["flatpak_id"]))
            if r["package"]:
                lines.append("  " + tr("package: {name} {version}").format(name=r["package"], version=r["version"]))
            elif r["version"]:
                lines.append("  " + tr("version: {version}").format(version=r["version"]))
        elif r["kind"] == "command":
            lines.append(tr("{name} — command").format(name=r["name"]))
            lines.append("  " + tr("path: {path}").format(path=_short(r["path"])))
            if not r["in_path"]:
                lines.append("  " + tr("not in your PATH: run it as {path}").format(path=r["path"]))
            if r["package"]:
                lines.append("  " + tr("package: {name} {version}").format(name=r["package"], version=r["version"]))
        elif r["kind"] == "service":
            lines.append(tr("{name} — system service ({state})").format(name=r["name"], state=r["active"]))
    return Outcome(True, "\n".join(lines), {"found": found})


@capabilities("list_appimages", "Lists the AppImages on this computer and whether they are in the app menu.",
          {}, risk="read")
def list_appimages(args):
    listing = _programs_module().appimages()
    if not listing:
        return Outcome(True, tr("There are no AppImages on this computer. Put them in the Applications "
                              "or Downloads folder and they join the app menu by themselves."), {"appimage": []})
    lines = [ntr("{n} AppImage:", "{n} AppImages:", len(listing)).format(n=len(listing))]
    for r in listing:
        state = tr("in the menu") if r["in_menu"] else tr("not in the menu")
        lines.append("  %s — %s (%s)" % (r["name"], _short(r["path"]), state))
    return Outcome(True, "\n".join(lines), {"appimage": listing})


# the same app installed more than once (APT, Flatpak, AppImage): which one
# i18n-data-begin: Italian and English words for an installation source
_SOURCE_WORDS = {"flatpak": "flatpak", "appimage": "appimage", "apt": "apt", "debian": "apt",
                 "deb": "apt", "opt": "opt", "user": "user", "utente": "user", "local": "local",
                 "locale": "local"}
# i18n-data-end
# the word to say for each source (the first word above that selects it)
_SOURCE_WORD = {"apt": "APT", "flatpak": "Flatpak", "appimage": "AppImage", "opt": "opt",
                 "user": "user", "local": "local"}


def choose_installation(name):
    """(app of the registry, "") for the one installation the user means;
    (None, question) when several installations match and the request does
    not say which; (None, "") when the registry has no such app."""
    programs = _programs_module()
    words = name.casefold().split()
    source = next((_SOURCE_WORDS[p] for p in words if p in _SOURCE_WORDS), "")
    rest = " ".join(p for p in words if p not in _SOURCE_WORDS and p not in ("version", "versione"))  # i18n-data
    exact_matches = [r for r in programs.apps(rest) if r["name"].casefold() == rest]
    if source:
        exact_matches = [r for r in exact_matches if r["source"] == source]
    if len(exact_matches) <= 1:
        if exact_matches and source:
            return programs.reg.find(exact_matches[0]["id"]), ""
        return None, ""
    listing = ", ".join("%s (%s)" % (r["name"], r["source_label"]) for r in exact_matches)
    with_word = [r for r in exact_matches if r["source"] in _SOURCE_WORD] or exact_matches
    example = "%s %s" % (with_word[0]["name"], _SOURCE_WORD.get(with_word[0]["source"], ""))
    return None, tr("There are {n} installations: {list}. Which one? For example: “open {example}”.").format(
        n=len(exact_matches), list=listing, example=example)


# ================================================================ FILES AND FOLDERS
# i18n-data-begin: Italian and English names of the well-known folders
PLACES = {
    "scrivania": "DESKTOP", "desktop": "DESKTOP",
    "documenti": "DOCUMENTS", "documents": "DOCUMENTS",
    "download": "DOWNLOAD", "downloads": "DOWNLOAD", "scaricati": "DOWNLOAD",
    "immagini": "PICTURES", "foto": "PICTURES", "pictures": "PICTURES",
    "musica": "MUSIC", "music": "MUSIC",
    "video": "VIDEOS", "filmati": "VIDEOS", "videos": "VIDEOS",
    "modelli": "TEMPLATES", "pubblici": "PUBLICSHARE",
    "home": "HOME", "casa": "HOME", "cartella personale": "HOME", "personale": "HOME",
    # English names
    "photos": "PICTURES", "templates": "TEMPLATES", "public": "PUBLICSHARE",
    "home folder": "HOME", "personal folder": "HOME",
}
# i18n-data-end
_XDG = {}


def folder_of(place: str) -> str | None:
    """«desktop» -> /home/zeta/Desktop; a path -> the path itself."""
    if not place:
        return None
    l = S.norm(place)
    l = re.sub(r"^(la|il|lo|le|i|gli|nella|nel|nei|negli|sulla|sul|in|su|alla|al)\s+", "", l)  # i18n-data
    l = re.sub(r"^(?:(?:in|on|to|into|inside|from)\s+)?(?:(?:the|my)\s+)?", "", l)
    l = l.replace("cartella ", "") if l.startswith("cartella ") and l[9:] in PLACES else l  # i18n-data: «cartella documenti»
    l = l[:-7] if l.endswith(" folder") and l[:-7] in PLACES else l       # «documents folder»
    if l in PLACES:
        k = PLACES[l]
        if k == "HOME":
            return S.HOME
        if k not in _XDG:
            rc, out, _ = S.run(["xdg-user-dir", k], timeout=3)
            _XDG[k] = out if rc == 0 and out and os.path.isdir(out) else None
        return _XDG[k]
    p = os.path.expanduser(place.strip())
    if os.path.isabs(p) and os.path.isdir(p):
        return p
    # a folder by name, searched for like any other item
    found_folders = search_items(place, folders_only=True, limit=2)
    return found_folders[0] if len(found_folders) == 1 else None


_EXCLUDED = {".cache", ".local", ".config", ".mozilla", ".thunderbird", "node_modules", ".git", ".var"}


def search_items(name: str, location: str | None = None, folders_only=False, limit=20) -> list[str]:
    """Files or folders with that name (exact match, ignoring case and the
    extension), first in the usual places, then in the whole home folder."""
    name = name.strip().strip("«»\"'")
    p = os.path.expanduser(name)
    if os.path.isabs(p):
        return [p] if os.path.exists(p) else []
    wanted = name.lower()

    def matches(n, full_path):
        if folders_only and not os.path.isdir(full_path):
            return False
        low = n.lower()
        return low == wanted or os.path.splitext(low)[0] == wanted
    found = []
    roots = [location] if location else [folder_of(x) for x in ("desktop", "documents", "downloads",
                                                               "pictures", "music", "videos")] + [S.HOME]
    for r in [x for x in roots if x]:
        try:
            for n in os.listdir(r):
                full_path = os.path.join(r, n)
                if matches(n, full_path) and full_path not in found:
                    found.append(full_path)
        except OSError:
            continue
    if found:
        return found[:limit]
    base = location or S.HOME
    for dirpath, below, files in os.walk(base):
        depth = dirpath[len(base):].count(os.sep)
        below[:] = [d for d in below if not d.startswith(".") and d not in _EXCLUDED] if depth < 6 else []
        for n in (below if folders_only else below + files):
            full_path = os.path.join(dirpath, n)
            if matches(n, full_path):
                found.append(full_path)
                if len(found) >= limit:
                    return found
    return found


def _inside_home(p: str) -> bool:
    """Writes are allowed only in the home folder and on user-mounted drives."""
    r = os.path.realpath(p)
    return any(r == b or r.startswith(b + os.sep) for b in
               (os.path.realpath(S.HOME), "/media", "/run/media", "/mnt"))


def _single_item(name, location=None, folders_only=False):
    """(path, None), or (None, error Outcome) if it is missing or ambiguous."""
    if os.path.isabs(name or "") and os.path.exists(name) and \
            (not folders_only or os.path.isdir(name)):
        return name, None                   # already an exact path
    d = folder_of(location) if location else None
    if location and not d:
        return None, Outcome(False, tr("I can't find the folder “{folder}”.").format(folder=location))
    t = search_items(name, d, folders_only=folders_only, limit=6)
    if not t:
        if location:
            return None, Outcome(False, tr("I can't find “{name}” in {folder}.").format(name=name, folder=location))
        return None, Outcome(False, tr("I can't find “{name}”.").format(name=name))
    if len(t) > 1:
        listing = "; ".join(_short(x) for x in t[:5])
        return None, Outcome(False, tr("There's more than one “{name}”: {list}. Which one? "
                                     "Tell me the folder too.").format(name=name, list=listing),
                           {"ambiguous": t})
    return t[0], None


def _short(p):
    return p.replace(S.HOME, "~", 1)


def _unique_name(folder, name):
    dest = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(folder, "%s (%d)%s" % (base, n, ext))
        n += 1
    return dest


@capabilities("create_folder", "Creates a folder.", {"name": "name of the new folder",
          "location": "where to create it: desktop, documents, downloads... or a path (default: home folder)"},
          ["name"])
def create_folder(args):
    name = (args.get("name") or "").strip().strip("«»\"'")
    if not name or "/" in name:
        return Outcome(False, tr("That folder name isn't valid."))
    base = folder_of(args.get("location") or "home")
    if not base:
        return Outcome(False, tr("I can't find the folder “{folder}”.").format(folder=args.get("location")))
    dest = os.path.join(base, name)
    if not _inside_home(dest):
        return Outcome(False, tr("I only create folders in your home folder or on external drives."))
    if os.path.isdir(dest):
        return Outcome(True, tr("The folder {path} already exists.").format(path=_short(dest)), {"path": dest})
    try:
        os.makedirs(dest)
    except OSError as e:
        return Outcome(False, tr("I couldn't create {path}: {error}").format(path=_short(dest), error=e.strerror))
    return Outcome(os.path.isdir(dest), tr("I created the folder {path}.").format(path=_short(dest)),
                 {"path": dest})


@capabilities("create_file", "Creates a text file, optionally with some content.",
          {"name": "file name, e.g. notes.txt", "location": "folder (default: documents)",
           "text": "content (optional)"}, ["name"])
def create_file(args):
    name = (args.get("name") or "").strip().strip("«»\"'")
    if not name or "/" in name:
        return Outcome(False, tr("That file name isn't valid."))
    base = folder_of(args.get("location") or "documents")
    if not base:
        return Outcome(False, tr("I can't find the folder “{folder}”.").format(folder=args.get("location")))
    dest = os.path.join(base, name)
    if not _inside_home(dest):
        return Outcome(False, tr("I only create files in your home folder or on external drives."))
    if os.path.exists(dest):
        return Outcome(False, tr("{path} already exists: I won't overwrite it.").format(path=_short(dest)))
    try:
        with open(dest, "x", encoding="utf-8") as f:
            f.write(args.get("text") or "")
    except OSError as e:
        return Outcome(False, tr("I couldn't create {path}: {error}").format(path=_short(dest), error=e.strerror))
    return Outcome(os.path.isfile(dest), tr("I created {path}.").format(path=_short(dest)), {"path": dest})


@capabilities("rename_item", "Renames a file or a folder.",
          {"item": "file or folder to rename", "new_name": "the new name",
           "location": "folder it is in (optional)"},
          ["item", "new_name"])
def rename_item(args):
    src, err = _single_item(args.get("item", ""), args.get("location"))
    if err:
        return err
    new = (args.get("new_name") or "").strip().strip("«»\"'")
    if not new or "/" in new:
        return Outcome(False, tr("That new name isn't valid."))
    if "." not in new and os.path.isfile(src) and os.path.splitext(src)[1]:
        new += os.path.splitext(src)[1]          # "rename note.txt to memo" keeps .txt
    dest = os.path.join(os.path.dirname(src), new)
    if not _inside_home(src):
        return Outcome(False, tr("I only rename things in your home folder or on external drives."))
    if os.path.exists(dest):
        return Outcome(False, tr("{path} already exists.").format(path=_short(dest)))
    try:
        os.rename(src, dest)
    except OSError as e:
        return Outcome(False, tr("I couldn't rename it: {error}").format(error=e.strerror))
    ok = os.path.exists(dest) and not os.path.exists(src)
    return Outcome(ok, tr("I renamed {old} to {new}.").format(old=os.path.basename(src), new=new),
                 {"path": dest})


def _destination(args):
    d = args.get("destination") or args.get("target") or ""
    base = folder_of(d) if d else None
    if not base:
        return None, Outcome(False, tr("I can't find the destination folder “{folder}”.").format(folder=d))
    if not _inside_home(base):
        return None, Outcome(False, tr("I only write to your home folder or to external drives."))
    return base, None


@capabilities("copy_item", "Copies a file or a folder into another folder.",
          {"item": "file or folder", "destination": "destination folder (desktop, documents, ... or a path)",
           "location": "folder it is in (optional)"}, ["item", "destination"])
def copy_item(args):
    src, err = _single_item(args.get("item", ""), args.get("location"))
    if err:
        return err
    base, err = _destination(args)
    if err:
        return err
    dest = _unique_name(base, os.path.basename(src))
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)
    except (OSError, shutil.Error) as e:
        return Outcome(False, tr("Copy failed: {error}").format(error=e))
    ok = os.path.exists(dest) and (os.path.isdir(src) or os.path.getsize(dest) == os.path.getsize(src))
    return Outcome(ok, tr("I copied {name} to {path}.").format(name=os.path.basename(src), path=_short(dest)),
                 {"path": dest})


@capabilities("move_item", "Moves a file or a folder into another folder.",
          {"item": "file or folder", "destination": "destination folder",
           "location": "folder it is in now (optional)"},
          ["item", "destination"])
def move_item(args):
    src, err = _single_item(args.get("item", ""), args.get("location"))
    if err:
        return err
    base, err = _destination(args)
    if err:
        return err
    if not _inside_home(src):
        return Outcome(False, tr("I only move files from your home folder or from external drives."))
    if os.path.dirname(os.path.realpath(src)) == os.path.realpath(base):
        return Outcome(True, tr("{name} is already in {path}.").format(name=os.path.basename(src), path=_short(base)))
    dest = _unique_name(base, os.path.basename(src))
    try:
        shutil.move(src, dest)
    except (OSError, shutil.Error) as e:
        return Outcome(False, tr("Move failed: {error}").format(error=e))
    ok = os.path.exists(dest) and not os.path.exists(src)
    return Outcome(ok, tr("I moved {name} to {path}.").format(name=os.path.basename(src), path=_short(base)),
                 {"path": dest})


# i18n-data-begin: vague Italian and English words that never name one item
_VAGUE = {"tutto", "tutti", "tutte", "ogni cosa", "qualcosa", "tutto quanto", "tutti i file", "questo", "quello",
          "everything", "all", "all of it", "all files", "all the files", "all my files", "every file",
          "anything", "something", "this", "that", "it", "them", "these", "those", "stuff", "all of them",
          "files", "my files", "the files", "every thing"}
# i18n-data-end


def _check_delete(args):
    """The item to delete: exactly one, existing, not protected."""
    if S.norm(args.get("item", "")) in _VAGUE:
        return Outcome(False, tr("I won't delete “{name}”: tell me the name of the file or folder.").format(
            name=args["item"]))
    src, err = _single_item(args.get("item", ""), args.get("location"))
    if err:
        return err
    if not _inside_home(src) or os.path.realpath(src) in (os.path.realpath(S.HOME),) or \
            os.path.realpath(src) in {folder_of(x) for x in PLACES if PLACES[x] != "HOME"}:
        return Outcome(False, tr("{path} can't be deleted from here.").format(path=_short(src)))
    args["_path"] = src
    return None


@capabilities("delete_item", "Moves a file or a folder to the trash (it can be restored).",
          {"item": "file or folder", "location": "folder it is in (optional)"}, ["item"],
          risk="confirm", check=_check_delete,
          preview=lambda a: tr("Move {name} to the trash").format(
              name=_short(a["_path"]) if a.get("_path") else "«%s»" % a.get("item", "")))
def delete_item(args):
    err = _check_delete(args)
    if err:
        return err
    src = args["_path"]
    rc, _o, e = S.run(["gio", "trash", "--", src], timeout=30)
    ok = rc == 0 and not os.path.exists(src)
    return Outcome(ok, tr("I moved {name} to the trash (it can be restored).").format(name=os.path.basename(src))
                 if ok else tr("I couldn't delete it: {error}").format(error=e or tr("error")))


@capabilities("search_files", "Searches files and folders by name.",
          {"text": "part of the name, or *.pdf", "location": "folder to search in (default: the whole home folder)"},
          ["text"], risk="read")
def search_files(args):
    q = (args.get("text") or "").strip().strip("«»\"'")
    if not q:
        return Outcome(False, tr("What should I search for?"))
    base = folder_of(args["location"]) if args.get("location") else S.HOME
    if not base:
        return Outcome(False, tr("I can't find the folder “{folder}”.").format(folder=args.get("location")))
    fd = shutil.which("fdfind") or shutil.which("fd")
    if fd:
        cmd = [fd, "--max-results", "30", "--ignore-case"]
        cmd += (["--glob", q] if any(c in q for c in "*?") else ["--fixed-strings", q])
        # given an absolute folder, fd returns absolute paths
        _rc, out, _e = S.run(cmd + [base], timeout=20)
        found = [x for x in out.splitlines() if x]
    else:
        found = [p for p in search_items(q, base, limit=30)]
    if not found:
        if base == S.HOME:
            return Outcome(True, tr("No files or folders matching “{text}”.").format(text=q), {"found": []})
        return Outcome(True, tr("No files or folders matching “{text}” in {folder}.").format(
            text=q, folder=_short(base)), {"found": []})
    listing = "\n".join("  " + _short(x) for x in found[:15])
    if len(found) > 15:
        header = tr("Found {n} (and more):").format(n=len(found))
    else:
        header = tr("Found {n}:").format(n=len(found))
    return Outcome(True, header + "\n" + listing, {"found": found})


def _open_and_verify(cmd, what, seconds=15):
    before = {w["address"] for w in S.windows()}
    try:
        S.launch(cmd)
    except OSError as e:
        return Outcome(False, tr("I can't open {item}: {error}").format(item=what, error=e))
    if not S.desktop_active():
        return Outcome(True, tr("I opened {item}.").format(item=what))
    new = S.wait(lambda: {w["address"] for w in S.windows()} - before, seconds)
    return Outcome(bool(new), tr("I opened {item}.").format(item=what) if new else
                 tr("I asked to open {item} but no window appeared.").format(item=what))


@capabilities("open_file", "Opens a file with its default app.",
          {"item": "file to open", "location": "folder (optional)"}, ["item"])
def open_file(args):
    src, err = _single_item(args.get("item", ""), args.get("location"))
    if err:
        return err
    if os.path.isdir(src):
        return open_folder({"folder": src})
    return _open_and_verify(["xdg-open", src], os.path.basename(src))


@capabilities("open_folder", "Opens a folder in the file manager.",
          {"folder": "desktop, documents, downloads, pictures, music, videos, home, trash, or a path/name"},
          ["folder"])
def open_folder(args):
    c = (args.get("folder") or "home").strip()
    if S.norm(c) in ("cestino", "il cestino", "trash", "the trash", "trash can", "recycle bin"):  # i18n-data
        return _open_and_verify(["zeta-default-app", "file", "trash:///"], tr("the trash"))
    d = folder_of(c)
    if not d:
        d_, err = _single_item(c, folders_only=True)
        if err:
            return err
        d = d_
    return _open_and_verify(["zeta-default-app", "file", d], tr("the folder {path}").format(path=_short(d)))


@capabilities("show_location", "Shows the folder a file is in.",
          {"item": "file or folder"}, ["item"])
def show_location(args):
    src, err = _single_item(args.get("item", ""), args.get("location"))
    if err:
        return err
    r = _open_and_verify(["zeta-default-app", "file", os.path.dirname(src)],
                         tr("the folder containing {name}").format(name=os.path.basename(src)))
    if r.ok:
        r.message = tr("{name} is in {folder}: I opened the folder.").format(
            name=os.path.basename(src), folder=_short(os.path.dirname(src)))
    return r


@capabilities("download_file", "Downloads a file from the internet into a folder.",
          {"url": "http(s) address", "location": "folder (default: downloads)"}, ["url"])
def download_file(args):
    import urllib.parse
    import urllib.request
    url = (args.get("url") or "").strip()
    if not re.match(r"^https?://", url):
        return Outcome(False, tr("I need an address that starts with http:// or https://."))
    base = folder_of(args.get("location") or "downloads")
    if not base or not _inside_home(base):
        return Outcome(False, tr("Invalid destination folder."))
    anonymous = tr("download")                # file name when the address has none
    name = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path)) or anonymous
    dest = _unique_name(base, name)
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZETA-RAYS/2.0"})
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            cd = r.headers.get("Content-Disposition", "")
            m = re.search(r'filename="?([^";]+)"?', cd)
            if m and name == anonymous:
                dest = _unique_name(base, os.path.basename(m.group(1)))
            shutil.copyfileobj(r, f, 1 << 20)
        os.replace(tmp, dest)
    except Exception as e:  # noqa: BLE001 - network, disk, address: report what happened
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return Outcome(False, tr("Download failed: {error}").format(error=e))
    ok = os.path.isfile(dest) and os.path.getsize(dest) > 0
    return Outcome(ok, tr("I downloaded {name} to {folder} ({size} MB).").format(
        name=os.path.basename(dest), folder=_short(base), size="%.1f" % (os.path.getsize(dest) / 1e6)),
        {"path": dest})


# ================================================================ SYSTEM
# Words for a Settings page -> the page id that zeta-settings accepts.
# i18n-data-begin: Italian and English names of the Settings pages
PAGES = {"aspetto": "appearance", "tema": "appearance", "colori": "appearance", "sfondo": "appearance",
          "dock": "dock", "barra": "dock", "schermo": "lock-screen", "blocco": "lock-screen",
          "display": "lock-screen", "luminosita": "lock-screen", "monitor": "lock-screen",
          "notifiche": "notifications", "rete": "network", "wifi": "network", "wi-fi": "network",
          "internet": "network",
          "bluetooth": "bluetooth", "audio": "audio", "suono": "audio", "volume": "audio",
          "stampanti": "printers", "stampante": "printers", "stampa": "printers",
          "ai": "ai", "intelligenza": "ai", "intelligenza artificiale": "ai", "zeta": "ai",
          "informazioni": "info", "info": "info", "sistema": "info",
          "app predefinite": "default-apps", "applicazioni predefinite": "default-apps",
          "predefinite": "default-apps",
          # English names
          "appearance": "appearance", "theme": "appearance", "colors": "appearance", "colours": "appearance",
          "wallpaper": "appearance", "background": "appearance", "bar": "dock", "taskbar": "dock",
          "panel": "dock",
          "screen": "lock-screen", "lock screen": "lock-screen", "brightness": "lock-screen",
          "notifications": "notifications", "network": "network", "sound": "audio",
          "printers": "printers", "printer": "printers", "printing": "printers",
          "artificial intelligence": "ai", "assistant": "ai", "about": "info", "information": "info",
          "system": "info", "default apps": "default-apps", "default applications": "default-apps"}
SETTINGS_APPS = {"sicurezza": "zeta-security", "firewall": "zeta-security",
                    "pacchetti": "synaptic", "security": "zeta-security", "packages": "synaptic"}
# i18n-data-end


def _page_name(page):
    """The display name of a Settings page."""
    return {"appearance": tr("Appearance"), "dock": tr("Dock"), "lock-screen": tr("Display"),
            "notifications": tr("Notifications"), "network": tr("Network"), "bluetooth": "Bluetooth",
            "audio": tr("Sound"), "printers": tr("Printers"), "ai": "AI", "info": tr("About"),
            "default-apps": tr("Default Apps")}.get(page, page)


@capabilities("open_settings", "Opens Settings, optionally on a page (appearance, dock, display, notifications, "
          "network, bluetooth, sound, printers, ai, about, default apps).", {"page": "optional"})
def open_settings(args):
    p = S.norm(args.get("page") or "")
    p = re.sub(r"^(di |del |della |dello |dei |delle |per |su |sul |sulla )", "", p)  # i18n-data
    p = re.sub(r"^(?:(?:of|for|on|about)\s+)?(?:(?:the|my)\s+)?", "", p)
    if p in SETTINGS_APPS:
        return open_application({"app": SETTINGS_APPS[p]})
    a = S.find_app("settings")
    if a:
        for w in S.windows_of(a):          # only one Settings window at a time
            S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
        S.wait(lambda: not S.windows_of(a), 3)
    page = PAGES.get(p)
    if p and not page:
        # an app's settings: open the app itself (its preferences are inside it)
        app = S.find_app(p)
        if app:
            r = open_application({"app": app.id})
            if r.ok:
                r.message += " " + tr("Its settings are in its own menu.")
            return r
        return Outcome(False, tr("I don't know the Settings page “{page}”.").format(page=p))
    r = _open_and_verify(["zeta-settings"] + ([page] if page else []),
                         tr("Settings › {page}").format(page=_page_name(page)) if page
                         else tr("the Settings app"))
    return r


def _volume():
    rc, out, _ = S.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=4, c_locale=True)
    if rc != 0:
        return None, None
    m = re.search(r"Volume:\s*([\d.]+)", out)
    return (round(float(m.group(1)) * 100) if m else None), ("MUTED" in out)


@capabilities("set_volume", "Sets the volume (0-100), raises/lowers it by a step, or mutes it.",
          {"level": "0-100 (optional)", "change": "+N or -N (optional)",
           "mute": "true to mute, false to unmute (optional)"})
def set_volume(args):
    vol, muted = _volume()
    if vol is None:
        return Outcome(False, tr("I can't find the audio output."))
    if "mute" in args and args["mute"] is not None:
        want_mute = bool(args["mute"]) if not isinstance(args["mute"], str) else \
            args["mute"].lower() in ("true", "si", "sì", "yes", "1")  # i18n-data
        S.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if want_mute else "0"])
        _, m2 = _volume()
        S.run(["pkill", "-RTMIN+11", "-x", "waybar"])
        return Outcome(m2 == want_mute, tr("Sound muted.") if want_mute else tr("Sound unmuted."))
    if args.get("level") is not None:
        try:
            target_level = int(float(str(args["level"]).rstrip("%")))
        except ValueError:
            return Outcome(False, tr("Invalid volume level."))
    elif args.get("change") is not None:
        try:
            target_level = vol + int(float(str(args["change"]).rstrip("%")))
        except ValueError:
            return Outcome(False, tr("Invalid volume change."))
    else:
        return Outcome(True, (tr("The volume is at {level}% (muted).") if muted else
                            tr("The volume is at {level}%.")).format(level=vol), {"volume": vol})
    target_level = max(0, min(100, target_level))
    S.run(["zeta-volume", "set", str(target_level)])
    if muted and target_level > 0:
        S.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
    now, _ = _volume()
    return Outcome(now is not None and abs(now - target_level) <= 1, tr("Volume at {level}%.").format(level=now or 0),
                 {"volume": now})


def _backlight():
    import glob
    for d in sorted(glob.glob("/sys/class/backlight/*")):
        try:
            cur = int(open(d + "/brightness").read())
            mx = int(open(d + "/max_brightness").read()) or 1
            return os.path.basename(d), round(cur * 100 / mx)
        except (OSError, ValueError):
            continue
    return None, None


@capabilities("set_brightness", "Sets the screen brightness (0-100) or changes it by a step.",
          {"level": "0-100 (optional)", "change": "+N or -N (optional)"})
def set_brightness(args):
    dev, now = _backlight()
    if dev is None:
        return Outcome(False, tr("This screen's brightness can't be adjusted from the computer "
                               "(this happens with external monitors and virtual machines): "
                               "use the monitor's buttons."))
    if args.get("level") is not None:
        target_level = int(float(str(args["level"]).rstrip("%")))
    elif args.get("change") is not None:
        target_level = now + int(float(str(args["change"]).rstrip("%")))
    else:
        return Outcome(True, tr("Brightness is at {level}%.").format(level=now), {"brightness": now})
    target_level = max(1, min(100, target_level))
    rc, _o, e = S.run(["brightnessctl", "-d", dev, "set", "%d%%" % target_level], timeout=5)
    _d, after = _backlight()
    ok = rc == 0 and after is not None and abs(after - target_level) <= 2
    return Outcome(ok, tr("Brightness at {level}%.").format(level=after) if ok else
                 tr("I couldn't change the brightness: {error}").format(error=e or tr("error")))


def _power():
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import power
    return power


@capabilities("lock_screen", "Locks the screen.", {})
def lock_screen(args):
    _power().lock()
    ok = S.wait(lambda: S.run(["pgrep", "-x", "hyprlock"])[0] == 0, 4)
    return Outcome(ok, tr("Screen locked.") if ok else tr("I couldn't lock the screen."))


@capabilities("suspend_system", "Puts the computer to sleep (suspend).", {})
def suspend_system(args):
    p = _power()
    p.suspend()
    return Outcome(True, tr("Putting the computer to sleep.") if p.can_suspend() else
                 tr("Sleep isn't safe here: I locked the screen and I'm turning it off."))


@capabilities("logout", "Logs out of the session (closes all apps).", {}, risk="confirm",
          preview=lambda a: tr("Log out: all apps will be closed"))
def logout(args):
    ok = S.dispatch("hl.dsp.exit()")          # Hyprland's "ok" reply
    return Outcome(ok, tr("Logging out.") if ok else tr("Hyprland didn't accept the logout."))


@capabilities("restart_system", "Restarts the computer.", {}, risk="confirm",
          preview=lambda a: tr("Restart the computer: open apps will be closed"))
def restart_system(args):
    return _power_action("reboot", tr("The computer is restarting."))


@capabilities("shutdown_system", "Shuts down the computer.", {}, risk="confirm",
          preview=lambda a: tr("Shut down the computer: open apps will be closed"))
def shutdown_system(args):
    return _power_action("poweroff", tr("The computer is shutting down."))


def _power_action(operation, message):
    """Restart and shutdown: wait for systemd's answer. The command used to
    be fired off and ZETA said "Restarting the computer" even when the system
    refused (seen in practice: from a non-local session the reboot never
    started and ZETA claimed it had done it)."""
    rc, out, err = S.run(["systemctl", operation, "--no-ask-password"], timeout=20)
    if rc == 0:
        return Outcome(True, message)
    reason = (err or out or "").strip().splitlines()
    reason = reason[-1][:160] if reason else tr("unknown reason")
    if "authentication" in reason.lower() or "autenticazione" in reason.lower():  # i18n-data
        reason = tr("you need to be in the computer's local session (or have the administrator password)")
    return Outcome(False, tr("The system refused: {reason}.").format(reason=reason))


@capabilities("set_theme", "Light or dark theme.", {"theme": "light or dark"}, ["theme"])
def set_theme(args):
    t = "light" if S.norm(args.get("theme", "")).startswith(("chiar", "light")) else "dark"  # i18n-data
    S.run(["zeta-appearance", "set", "theme", t], timeout=40)      # also applies it
    try:
        now = open(os.path.join(S.HOME, ".config/zeta/theme")).read().strip()
    except OSError:
        now = ""
    if now != t:
        return Outcome(False, tr("The theme didn't change."))
    return Outcome(True, tr("Light theme on.") if t == "light" else tr("Dark theme on."))


@capabilities("set_wallpaper", "Changes the wallpaper to an image, to one of the ZETA RAYS wallpapers "
          "(Blue waves, Green circuits, Red waves, Terminal, Blue/green/red/white logo) "
          "or back to the ZETA RAYS default.",
          {"image": "image file, name of a ZETA RAYS wallpaper, or \"default\""}, ["image"])
def set_wallpaper(args):
    name = (args.get("image") or "").strip()
    # i18n-data-begin: Italian and English words for the default wallpaper
    if S.norm(name) in ("predefinito", "originale", "zeta", "zeta rays", "di zeta rays",
                        "default", "the default", "the default one", "original", "the original",
                        "the original one", "zeta rays default"):
        # i18n-data-end
        rc, _o, e = S.run(["zeta-wallpaper", "reset"], timeout=30)
        return Outcome(rc == 0, tr("The ZETA RAYS wallpaper is back.") if rc == 0 else
                     tr("That didn't work: {error}").format(error=e))
    # first the ZETA RAYS wallpapers by name («onde rosse»), then the user's files
    from system import wallpapers
    official = wallpapers.search(name)
    if official:
        rc, _o, e = S.run(["zeta-wallpaper", "set", official], timeout=30)
        # verification: zeta-wallpaper must report back the chosen wallpaper
        _r, now, _e = S.run(["zeta-wallpaper", "get"])
        ok = rc == 0 and now.split("\n")[0].strip() == official
        return Outcome(ok, tr("Wallpaper changed: {name}.").format(name=wallpapers.name_of(official)) if ok
                     else tr("That didn't work: {error}").format(error=e or tr("the wallpaper didn't change")))
    src, err = _single_item(name, args.get("location"))
    if err:
        return err
    rc, _o, e = S.run(["zeta-wallpaper", "set", src], timeout=30)
    return Outcome(rc == 0, tr("Wallpaper changed: {name}.").format(name=os.path.basename(src)) if rc == 0
                 else tr("That didn't work: {error}").format(error=e))


# ================================================================ NETWORK
def _wifi_radio():
    # the output is parsed and compared: force English (in Italian it said «abilitato»)
    rc, out, _ = S.run(["nmcli", "-t", "radio", "wifi"], timeout=5, c_locale=True)
    return out.strip() == "enabled" if rc == 0 else None


def _wifi_dev():
    rc, out, _ = S.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=5, c_locale=True)
    for r in out.splitlines():
        p = r.split(":")
        if len(p) >= 4 and p[1] == "wifi":
            return {"device": p[0], "state": p[2], "connection": p[3]}
    return None


@capabilities("wifi_on", "Turns Wi-Fi on.", {})
def wifi_on(args):
    if _wifi_dev() is None:
        return Outcome(False, tr("This computer has no Wi-Fi adapter."))
    S.run(["nmcli", "radio", "wifi", "on"], timeout=10)
    ok = S.wait(lambda: _wifi_radio() is True, 5)
    return Outcome(ok, tr("Wi-Fi is on.") if ok else tr("I couldn't turn Wi-Fi on."))


@capabilities("wifi_off", "Turns Wi-Fi off.", {})
def wifi_off(args):
    if _wifi_dev() is None:
        return Outcome(False, tr("This computer has no Wi-Fi adapter."))
    S.run(["nmcli", "radio", "wifi", "off"], timeout=10)
    ok = S.wait(lambda: _wifi_radio() is False, 5)
    return Outcome(ok, tr("Wi-Fi is off.") if ok else tr("I couldn't turn Wi-Fi off."))


@capabilities("wifi_list", "Lists nearby Wi-Fi networks.", {}, risk="read")
def wifi_list(args):
    if _wifi_dev() is None:
        return Outcome(False, tr("This computer has no Wi-Fi adapter."))
    if _wifi_radio() is False:
        return Outcome(False, tr("Wi-Fi is off: say “turn on Wi-Fi”."))
    rc, out, _ = S.run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                        "--rescan", "auto"], timeout=20, c_locale=True)
    networks = []
    for r in out.splitlines():
        p = r.replace("\\:", "\x00").split(":")
        if len(p) >= 4 and p[1]:
            name = p[1].replace("\x00", ":")
            entry = (tr("{name} ({signal}%, open)") if not p[3] else tr("{name} ({signal}%)")).format(
                name=name, signal=p[2])
            networks.append(("● " if p[0] == "*" else "") + entry)
    if not networks:
        return Outcome(True, tr("No Wi-Fi networks found nearby."), {"networks": []})
    return Outcome(True, tr("Wi-Fi networks: {list}.").format(list="; ".join(dict.fromkeys(networks))), {"networks": networks})


@capabilities("wifi_connect", "Connects to a Wi-Fi network (with its password, if needed).",
          {"network": "network name (SSID)", "password": "optional"}, ["network"])
def wifi_connect(args):
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import network
    ssid = (args.get("network") or "").strip().strip("«»\"'")
    if _wifi_dev() is None:
        return Outcome(False, tr("This computer has no Wi-Fi adapter."))
    if _wifi_radio() is False:
        wifi_on({})
    ok, msg, reason = network.connect_wifi_outcome(ssid, args.get("password") or None)
    if ok:
        return Outcome(True, tr("Connected to “{name}”.").format(name=ssid))
    if reason == "password":
        return Outcome(False, tr("The password for “{name}” is wrong (or missing): tell me again, "
                               "e.g. “connect to {name} with password …”.").format(name=ssid),
                     {"reason": "password"})
    if reason == "not_found":
        return Outcome(False, tr("I don't see any network called “{name}” nearby.").format(name=ssid),
                     {"reason": reason})
    return Outcome(False, tr("I didn't connect to “{name}”: {reason}").format(name=ssid, reason=msg),
                 {"reason": reason})


@capabilities("wifi_disconnect", "Disconnects from the current Wi-Fi network (Wi-Fi stays on).", {})
def wifi_disconnect(args):
    d = _wifi_dev()
    if d is None:
        return Outcome(False, tr("This computer has no Wi-Fi adapter."))
    if not d["state"].startswith("connected"):
        return Outcome(True, tr("Wi-Fi isn't connected to any network."))
    S.run(["nmcli", "device", "disconnect", d["device"]], timeout=15)
    ok = S.wait(lambda: not (_wifi_dev() or {}).get("state", "").startswith("connected"), 6)
    return Outcome(ok, tr("Disconnected from “{name}”.").format(name=d["connection"]) if ok else
                 tr("I couldn't disconnect."))


@capabilities("network_status", "Network status: connection, Wi-Fi, IP addresses.", {}, risk="read")
def network_status(args):
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import network
    rc, out, _ = S.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=5, c_locale=True)
    lines = []
    for r in out.splitlines():
        p = r.replace("\\:", "\x00").split(":")
        p = [x.replace("\x00", ":") for x in p]
        if len(p) < 4 or p[1] not in ("ethernet", "wifi") or p[2] == "unmanaged":
            continue                 # unmanaged adapters (e.g. an access point) don't count
        kind = "Wi-Fi" if p[1] == "wifi" else tr("Cable")
        if p[2].startswith("connected"):
            _rc2, ip, _ = S.run(["ip", "-4", "-br", "addr", "show", p[0]], timeout=3)
            addr = ip.split()[2].split("/")[0] if len(ip.split()) > 2 else ""
            name = network.nice_name(p[3], p[1])
            if addr:
                lines.append(tr("{type}: connected to “{name}”, address {ip}").format(type=kind, name=name, ip=addr))
            else:
                lines.append(tr("{type}: connected to “{name}”").format(type=kind, name=name))
        else:
            state = {"disconnected": tr("not connected"), "unavailable": tr("unavailable")}.get(p[2], p[2])
            lines.append("%s: %s" % (kind, state))
    radio = _wifi_radio()
    if radio is False:
        lines.append(tr("Wi-Fi off"))
    rc, gw, _ = S.run(["ip", "route", "show", "default"], timeout=3)
    if gw:
        lines.append(tr("Internet: yes, via {gateway}").format(gateway=gw.split()[2]))
    else:
        lines.append(tr("Internet: no route"))
    return Outcome(True, ". ".join(lines) + ".")


# ================================================================ DEFAULT APPS
def _default_apps_module():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import default_apps
    return default_apps


# roles given in English that are not also app names (those live in S.ROLES)
_ROLES_EN = {"mail": "mail", "email": "mail", "e-mail": "mail", "terminal": "terminal",
             "images": "images", "pictures": "images", "photos": "images", "videos": "video",
             "music": "video", "pdfs": "pdf"}


@capabilities("set_default_app", "Sets the default app for a role (browser, mail, files, terminal, "
          "editor, video, images, pdf).",
          {"role": "browser, mail, file, terminal, editor, video, images or pdf",
           "app": "app name"},
          ["role", "app"])
def set_default_app(args):
    P = _default_apps_module()
    r = S.norm(args.get("role", ""))
    role = S.ROLES.get(r) or _ROLES_EN.get(r, r)
    if role not in P.CATEGORIES:
        return Outcome(False, tr("I don't know the role “{role}”: I can set browser, mail, files, terminal, "
                               "editor, video, images or pdf.").format(role=args.get("role")))
    # here the name refers to an app, not a role: «the text editor» is the
    # app with that name, not whatever the current default editor is
    a = S.find_app(args.get("app", ""), roles=False)
    if a is None:
        return Outcome(False, tr("I can't find “{name}” among the installed apps.").format(name=args.get("app")))
    candidates = [c[0] for c in P.candidates(role)]
    if a.id + ".desktop" not in candidates:
        return Outcome(False, tr("{app} can't be used for: {role}.").format(app=a.name, role=P.CATEGORIES[role][0]))
    ok, msg = P.set_default(role, a.id + ".desktop")
    return Outcome(ok, msg)


@capabilities("list_default_apps", "Which apps are the defaults (browser, mail, terminal...).", {},
          risk="read")
def list_default_apps(args):
    from gi.repository import Gio
    P = _default_apps_module()
    lines = []
    for c in P.ORDER:
        aid = P.current(c)
        info = Gio.DesktopAppInfo.new(aid) if aid else None
        lines.append("%s: %s" % (P.CATEGORIES[c][0], P.app_name(aid, info) if info else tr("not set")))
    return Outcome(True, tr("Default apps — {list}.").format(list="; ".join(lines)))


# ================================================================ BLUETOOTH
def _bt():
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import bluetooth
    return bluetooth


def _bt_ready():
    bt = _bt()
    a = bt.adapter()
    if a is None:
        return bt, None, Outcome(False, tr("This computer has no Bluetooth (or it's disabled in the BIOS)."))
    return bt, a, None


@capabilities("bluetooth_on", "Turns Bluetooth on.", {})
def bluetooth_on(args):
    bt, a, err = _bt_ready()
    if err:
        return err
    bt.set_power(True)
    ok = S.wait(lambda: (bt.adapter() or {}).get("powered"), 5)
    return Outcome(bool(ok), tr("Bluetooth is on.") if ok else tr("I couldn't turn Bluetooth on."))


@capabilities("bluetooth_off", "Turns Bluetooth off.", {})
def bluetooth_off(args):
    bt, a, err = _bt_ready()
    if err:
        return err
    bt.set_power(False)
    ok = S.wait(lambda: not (bt.adapter() or {}).get("powered", True), 5)
    return Outcome(bool(ok), tr("Bluetooth is off.") if ok else tr("I couldn't turn Bluetooth off."))


@capabilities("bluetooth_devices", "Lists Bluetooth devices (connected, paired, nearby).",
          {}, risk="read")
def bluetooth_devices(args):
    bt, a, err = _bt_ready()
    if err:
        return err
    if not a["powered"]:
        return Outcome(True, tr("Bluetooth is off."))
    bt.scan(6)
    dd = bt.devices()
    if not dd:
        return Outcome(True, tr("No Bluetooth devices found."), {"devices": []})
    lines = [tr("{name} (connected)").format(name=d["name"]) if d["connected"] else
             tr("{name} (paired)").format(name=d["name"]) if d["paired"] else d["name"]
             for d in dd[:12]]
    return Outcome(True, tr("Devices: {list}.").format(list="; ".join(lines)), {"devices": dd})


def _bt_device(name):
    bt = _bt()
    n = S.norm(name)
    dd = bt.devices()
    for d in dd:
        if S.norm(d["name"]) == n or d["mac"].lower() == n:
            return d
    for d in dd:
        if n and n in S.norm(d["name"]):
            return d
    return None


@capabilities("bluetooth_connect", "Connects a Bluetooth device (headphones, mouse, ...).",
          {"device": "device name"}, ["device"])
def bluetooth_connect(args):
    bt, a, err = _bt_ready()
    if err:
        return err
    if not a["powered"]:
        bluetooth_on({})
    d = _bt_device(args.get("device", ""))
    if d is None:
        bt.scan(8)
        d = _bt_device(args.get("device", ""))
    if d is None:
        return Outcome(False, tr("I can't find “{name}”: turn it on and put it in pairing mode.").format(
            name=args.get("device")))
    if d["connected"]:
        return Outcome(True, tr("{name} is already connected.").format(name=d["name"]))
    bt.connect(d["mac"])
    ok = S.wait(lambda: (_bt_device(d["mac"]) or {}).get("connected"), 10)
    return Outcome(bool(ok), (tr("{name} connected.") if ok else
                            tr("I couldn't connect {name}.")).format(name=d["name"]))


@capabilities("bluetooth_disconnect", "Disconnects a Bluetooth device.", {"device": "name"}, ["device"])
def bluetooth_disconnect(args):
    bt, a, err = _bt_ready()
    if err:
        return err
    d = _bt_device(args.get("device", ""))
    if d is None:
        return Outcome(False, tr("I can't find the device “{name}”.").format(name=args.get("device")))
    if not d["connected"]:
        return Outcome(True, tr("{name} isn't connected.").format(name=d["name"]))
    bt.disconnect(d["mac"])
    ok = S.wait(lambda: not (_bt_device(d["mac"]) or {}).get("connected", True), 8)
    return Outcome(bool(ok), (tr("{name} disconnected.") if ok else
                            tr("I couldn't disconnect {name}.")).format(name=d["name"]))


# ================================================================ DOCK
def _dock():
    import sys
    sys.path.insert(0, "/usr/lib/zeta")
    from system import dock
    return dock


@capabilities("dock_add", "Adds an app to the dock.", {"app": "app name"}, ["app"])
def dock_add(args):
    a, err = _app_or_error(args)
    if err:
        return err
    _dock()                                  # puts /usr/lib/zeta on sys.path
    from system import applications as reg   # same registry as the menu
    r = reg.find(a.id)
    if r is None:
        return Outcome(False, tr("I can't find the menu entry for {app}.").format(app=a.name))
    # already in the dock: check the state, not the message text (which
    # now depends on the language)
    if reg.in_dock(r):
        return Outcome(True, tr("{app} is already in the dock.").format(app=a.name))
    ok, msg = reg.add_to_dock(r)
    return Outcome(ok and reg.in_dock(r), tr("I added {app} to the dock.").format(app=a.name) if ok else msg)


@capabilities("dock_remove", "Removes an app from the dock (doesn't uninstall it).", {"app": "app name"}, ["app"])
def dock_remove(args):
    name = (args.get("app") or "").strip()
    a = S.find_app(name)
    d = _dock()
    if a is not None:
        from system import applications as reg
        r = reg.find(a.id)
        if r is not None and reg.in_dock(r):
            ok, msg = reg.remove_from_dock(r)
            return Outcome(ok, tr("I removed {app} from the dock.").format(app=r.name) if ok else msg)
    entries = d.load_dock()
    kept = [v for v in entries if not (S.norm(v.get("name", "")) in {S.norm(name), S.norm(a.name) if a else ""}
                                       or (a and v.get("cmd", "").split()[:1] == [a.binary]))]
    if len(kept) == len(entries):
        return Outcome(True, tr("“{app}” isn't in the dock.").format(app=name))
    d.save_dock(kept)
    d.apply(kept)
    return Outcome(len(d.load_dock()) == len(kept),
                 tr("I removed {app} from the dock.").format(app=a.name if a else name))


# ================================================================ PROCESSES AND STATUS
@capabilities("system_status", "CPU, memory, disk and battery usage.", {"what": "cpu, ram, disk, battery or all"},
          risk="read")
def system_status(args):
    import psutil
    what = S.norm(args.get("what") or "all")
    # i18n-data-begin: Italian and English words for each part
    what = {"tutto": "all", "everything": "all", "processor": "cpu", "processore": "cpu", "memory": "ram",
            "memoria": "ram", "disco": "disk", "storage": "disk", "space": "disk", "spazio": "disk",
            "batteria": "battery"}.get(what, what)
    # i18n-data-end
    pieces = []
    if what in ("all", "cpu"):
        pieces.append(tr("CPU at {percent}% (load {load} on {cores} cores)").format(
            percent=int(psutil.cpu_percent(0.4)), load="%.1f" % os.getloadavg()[0], cores=psutil.cpu_count() or 1))
    if what in ("all", "ram"):
        vm = psutil.virtual_memory()
        pieces.append(tr("memory {used} GB used of {total} ({percent}%), {free} GB free").format(
            used="%.1f" % ((vm.total - vm.available) / 1e9), total="%.1f" % (vm.total / 1e9),
            percent=int(vm.percent), free="%.1f" % (vm.available / 1e9)))
    if what in ("all", "disk"):
        du = psutil.disk_usage(S.HOME)
        pieces.append(tr("disk {free} GB free of {total} ({percent}% used)").format(
            free="%.0f" % (du.free / 1e9), total="%.0f" % (du.total / 1e9), percent=int(du.percent)))
    if what in ("all", "battery"):
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if b:
            pieces.append((tr("battery at {percent}%, charging") if b.power_plugged else
                          tr("battery at {percent}%")).format(percent=int(b.percent)))
        elif what == "battery":
            pieces.append(tr("no battery (desktop computer or virtual machine)"))
    t = "; ".join(pieces)
    return Outcome(True, t[:1].upper() + t[1:] + ".")


@capabilities("list_processes", "The programs using the most CPU or memory.", {"by": "cpu or memory"},
          risk="read")
def list_processes(args):
    import psutil
    by_mem = S.norm(args.get("by") or "").startswith(("mem", "ram"))
    procs = list(psutil.process_iter(["name", "memory_info", "cmdline"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(0.6)
    totals = {}
    for p in procs:
        try:
            n = S.program_name(p.info["cmdline"] or [p.info["name"] or "?"]) or p.info["name"]
            c, r = totals.get(n, (0.0, 0))
            totals[n] = (c + p.cpu_percent(None), r + (p.info["memory_info"].rss if p.info["memory_info"] else 0))
        except psutil.Error:
            continue
    # only real consumers: kernel processes sitting at zero tell us nothing
    totals = {n: v for n, v in totals.items() if (v[1] > 20e6 if by_mem else v[0] >= 0.5)}
    if not totals:
        return Outcome(True, tr("No program is using the CPU significantly: the computer is idle."))
    ord_ = sorted(totals.items(), key=lambda kv: -(kv[1][1] if by_mem else kv[1][0]))[:6]
    lines = ["%s %s" % (n, ("%.0f MB" % (r / 1e6)) if by_mem else ("%.0f%% CPU" % c)) for n, (c, r) in ord_]
    return Outcome(True, (tr("Using the most memory: {list}.") if by_mem else
                        tr("Using the most CPU: {list}.")).format(list=", ".join(lines)))


# ================================================================ SOFTWARE
def _package(name):
    """a plausible package name: letters, digits and + - . (no options)"""
    n = S.norm(name).replace(" ", "-")
    return n if re.fullmatch(r"[a-z0-9][a-z0-9+.\-]{0,80}", n) else None


def _apt_in_terminal(operation, pkg):
    """apt in a terminal (pkexec asks for the password, the user sees what it
    does); at the end a notification tells how it really went (dpkg).
    The texts arrive already translated, as arguments ($3...$8)."""
    if operation == "install":
        texts = [tr("ZETA — Installing {package}").format(package=pkg),
                 tr("Installed: {package}").format(package=pkg), tr("You can open it now."),
                 tr("{package} was not installed").format(package=pkg),
                 tr("The installation failed or was canceled.")]
    else:
        texts = [tr("ZETA — Removing {package}").format(package=pkg),
                 tr("Removed: {package}").format(package=pkg), "",
                 tr("{package} is still installed").format(package=pkg),
                 tr("The removal failed or was canceled.")]
    title, ok_t, ok_c, no_t, no_c = texts
    script = r'''
foot -e sh -c 'printf "\033[1;34m%s\033[0m\n\n" "$3"; pkexec apt-get "$1" -y -- "$2"; printf "\n%s" "$4"; read _' _ "$1" "$2" "$3" "$4"
if dpkg-query -W -f='${Status}' "$2" 2>/dev/null | grep -q "install ok installed"; then st=installed; else st=absent; fi
if [ "$1" = install ] && [ "$st" = installed ]; then notify-send -a ZETA -i zeta-ai "$5" "$6";
elif [ "$1" = install ]; then notify-send -a ZETA -i dialog-warning "$7" "$8";
elif [ "$st" = absent ]; then notify-send -a ZETA -i zeta-ai "$5" "$6";
else notify-send -a ZETA -i dialog-warning "$7" "$8"; fi
'''
    S.launch(["sh", "-c", script, "_", operation, pkg, title, tr("Press Enter to close."), ok_t, ok_c, no_t, no_c])


def _packages_module():
    import sys
    if "/usr/lib/zeta" not in sys.path:
        sys.path.insert(0, "/usr/lib/zeta")
    from system import packages
    return packages


_PROTECTED = {"hyprland", "systemd", "sudo", "network-manager", "zeta", "calamares", "linux-image-amd64",
             "linux-image-arm64", "sddm", "waybar", "python3", "bash", "dbus", "apt", "dpkg"}


def _check_install(args):
    pkg = _package(args.get("package", ""))
    if not pkg:
        return Outcome(False, tr("“{name}” isn't a valid package name.").format(name=args.get("package")))
    p = _packages_module()
    d = p.availability([pkg])[pkg]
    if d["installed"]:
        return Outcome(True, tr("{package} is already installed (version {version}).").format(
            package=pkg, version=d["installed"]))
    if not d["candidate"]:
        return Outcome(False, tr("{package} can't be installed: {reason}").format(package=pkg, reason=p.why_missing(pkg)))
    args["_pkg"] = pkg
    return None


def _check_remove(args):
    pkg = _package(args.get("package", ""))
    if not pkg:
        return Outcome(False, tr("“{name}” isn't a valid package name.").format(name=args.get("package")))
    if not _packages_module().availability([pkg])[pkg]["installed"]:
        return Outcome(True, tr("{package} isn't installed: there's nothing to uninstall.").format(package=pkg))
    if pkg in _PROTECTED:
        return Outcome(False, tr("{package} is needed by the system: I won't uninstall it.").format(package=pkg))
    args["_pkg"] = pkg
    return None


@capabilities("install_package", "Installs a program from the repositories (asks for the password).",
          {"package": "package name"}, ["package"], risk="confirm", check=_check_install,
          preview=lambda a: tr("Install the package “{package}” (password required)").format(
              package=a.get("_pkg", a.get("package", ""))))
def install_package(args):
    err = _check_install(args)
    if err:
        return err
    pkg = args["_pkg"]
    _apt_in_terminal("install", pkg)
    return Outcome(True, tr("Installation of {package} started in the terminal: it will ask for your password, "
                          "and a notification will tell you whether it succeeded.").format(package=pkg),
                 {"in_progress": True})


@capabilities("remove_package", "Uninstalls a program (asks for the password).",
          {"package": "package name"}, ["package"], risk="confirm", check=_check_remove,
          preview=lambda a: tr("Uninstall the package “{package}” (password required)").format(
              package=a.get("_pkg", a.get("package", ""))))
def remove_package(args):
    err = _check_remove(args)
    if err:
        return err
    pkg = args["_pkg"]
    _apt_in_terminal("remove", pkg)
    return Outcome(True, tr("Uninstallation of {package} started in the terminal; "
                          "a notification will tell you how it went.").format(package=pkg),
                 {"in_progress": True})


# ================================================================ MISCELLANEOUS
@capabilities("current_time", "What time / what day it is.", {}, risk="read")
def current_time(args):
    days = (tr("Monday"), tr("Tuesday"), tr("Wednesday"), tr("Thursday"), tr("Friday"), tr("Saturday"),
              tr("Sunday"))
    months = (tr("January"), tr("February"), tr("March"), tr("April"), tr("May"), tr("June"), tr("July"),
            tr("August"), tr("September"), tr("October"), tr("November"), tr("December"))
    t = time.localtime()
    return Outcome(True, tr("It's {time} on {weekday}, {month} {day}, {year}.").format(
        time="%02d:%02d" % (t.tm_hour, t.tm_min), weekday=days[t.tm_wday], day=t.tm_mday,
        month=months[t.tm_mon - 1], year=t.tm_year))


@capabilities("screenshot", "Saves a screenshot to the Pictures folder.", {})
def screenshot(args):
    base = folder_of("pictures") or S.HOME
    dest = os.path.join(base, tr("Screenshot {date}.png").format(date=time.strftime("%Y-%m-%d %H-%M-%S")))
    rc, _o, e = S.run(["grim", dest], timeout=15)
    ok = rc == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 0
    return Outcome(ok, tr("Screenshot saved to {path}.").format(path=_short(dest)) if ok else
                 tr("Screenshot failed: {error}").format(error=e),
                 {"path": dest})


@capabilities("close_all_windows", "Closes all open windows.", {}, risk="confirm",
          preview=lambda a: tr("Close all windows (each app may ask to save)"))
def close_all_windows(args):
    ww = S.windows()
    for w in ww:
        S.dispatch('hl.dsp.window.close({ window = "%s" })' % _sel(w))
    remaining_windows = []
    S.wait(lambda: not S.windows(), 10)
    remaining_windows = S.windows()
    if not remaining_windows:
        return Outcome(True, ntr("I closed {n} window.", "I closed all {n} windows.", len(ww)).format(n=len(ww)))
    return Outcome(False, ntr("{n} is still open (it may be asking to save): {list}.",
                            "{n} are still open (they may be asking to save): {list}.", len(remaining_windows)).format(
        n=len(remaining_windows), list=", ".join((w.get("class") or "?") for w in remaining_windows[:4])))


@capabilities("open_url", "Opens a website in the browser.", {"url": "address, e.g. www.example.org"}, ["url"])
def open_url(args):
    url = (args.get("url") or "").strip()
    if not url:
        return Outcome(False, tr("Which website?"))
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if re.search(r"\s", url) or not re.match(r"^https?://[\w.-]+\.[a-z]{2,}(?:[:/?#]|$)", url, re.I):
        return Outcome(False, tr("“{address}” doesn't look like a website address.").format(address=args.get("url")))
    # the default browser the user chose, not just any browser
    _rc, current_default, _e = S.run(["xdg-mime", "query", "default", "x-scheme-handler/https"], timeout=5)
    a = next((x for x in S.installed_apps() if x.id == current_default.strip().removesuffix(".desktop")), None) \
        or S.find_app("browser")
    try:
        S.launch(["xdg-open", url])
    except OSError as e:
        return Outcome(False, tr("I can't open the website: {error}").format(error=e))
    if not a or not S.desktop_active():
        return Outcome(True, tr("I opened {item}.").format(item=url))
    ok = S.wait(lambda: S.windows_of(a), 20)
    return Outcome(bool(ok), tr("I opened {address} in the browser.").format(address=url) if ok else
                 tr("The browser didn't open."))
