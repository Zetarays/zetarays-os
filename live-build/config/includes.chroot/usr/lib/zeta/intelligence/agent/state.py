# SPDX-License-Identifier: GPL-3.0-or-later
"""The real state of the computer: windows, installed apps, processes.

Everything is read from the system (Hyprland, .desktop files, /proc), nothing
is guessed. The functions are fast (milliseconds) and never block: external
calls always have a timeout.
"""
from __future__ import annotations

import configparser
import glob
import json
import os
import re
import socket
import subprocess
import time
import unicodedata

from i18n import tr, language

HOME = os.path.expanduser("~")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()


def norm(text: str) -> str:
    """lowercase, no accents, single spaces"""
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def run(cmd, timeout=10, input_=None, c_locale=False):
    """(code, stdout, stderr) of a command; never an exception.
    c_locale=True: output always in English (LC_ALL=C), for commands whose
    output is parsed and compared (e.g. «enabled», «Volume: 0.50»)."""
    env = dict(os.environ, LC_ALL="C") if c_locale else None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_, env=env)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 127, "", tr("{cmd} is not installed").format(cmd=cmd[0])
    except subprocess.TimeoutExpired:
        return 124, "", tr("timed out")
    except OSError as e:
        return 1, "", str(e)


def launch(cmd, cwd=None, env=None):
    """Start a program detached from the caller: no inherited stdin/stdout
    (otherwise whoever waits for the output would stay blocked while the
    program is open) and no tie to the ZETA process."""
    p = subprocess.Popen(cmd, cwd=cwd or HOME, env=env, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    reap(p)
    return p


def reap(p):
    """Wait in the background for the program to finish: without this, every
    app opened by ZETA and then closed stayed as a zombie process for as long
    as ZETA was open."""
    import threading
    threading.Thread(target=p.wait, daemon=True).start()


# ------------------------------------------------------------ Hyprland
def _signature():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig and os.path.exists(os.path.join(RUNTIME, "hypr", sig)):
        return sig
    try:
        d = os.path.join(RUNTIME, "hypr")
        return sorted(os.listdir(d), key=lambda x: os.path.getmtime(os.path.join(d, x)))[-1]
    except (OSError, IndexError):
        return None


def hypr(msg: str, timeout: float = 2.0) -> str | None:
    sig = _signature()
    if not sig:
        return None
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(os.path.join(RUNTIME, "hypr", sig, ".socket.sock"))
        s.sendall(msg.encode())
        pieces = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            pieces.append(b)
        return b"".join(pieces).decode(errors="replace")
    except OSError:
        return None
    finally:
        s.close()


def hypr_json(what: str):
    r = hypr("j/" + what)
    try:
        return json.loads(r) if r else None
    except ValueError:
        return None


def dispatch(lua: str) -> bool:
    """Hyprland 0.55 dispatcher (Lua syntax). True if accepted."""
    r = hypr("dispatch " + lua)
    return r is not None and r.strip().lower().startswith("ok")


def windows() -> list[dict]:
    return hypr_json("clients") or []


def active_window() -> dict | None:
    w = hypr_json("activewindow")
    return w if isinstance(w, dict) and w.get("address") else None


def desktop_active() -> bool:
    return _signature() is not None and hypr("j/version") is not None


# ------------------------------------------------------------ processes
def cmdline(pid: int) -> list[str]:
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return [x.decode(errors="replace") for x in f.read().split(b"\0") if x]
    except OSError:
        return []


def alive(pid: int) -> bool:
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().split(") ", 1)[1][0] != "Z"
    except (OSError, IndexError):
        return False


def user_processes() -> list[tuple[int, list[str]]]:
    uid = os.getuid()
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            if os.stat("/proc/" + d).st_uid != uid:
                continue
        except OSError:
            continue
        c = cmdline(int(d))
        if c:
            out.append((int(d), c))
    return out


def program_name(cmd: list[str]) -> str:
    """firefox-esr, foot, zeta-settings (also for Python scripts)."""
    if not cmd:
        return ""
    b = os.path.basename(cmd[0])
    if re.match(r"python3?(\.\d+)?$", b) and len(cmd) > 1:
        for x in cmd[1:]:
            if not x.startswith("-"):
                return os.path.basename(x)
    return b


# ------------------------------------------------------------ installed apps
# in XDG precedence order: an entry from the user or from /usr/local wins over
# the package one
# (e.g. LocalSend hidden by ZETA Share); then Flatpak apps. Integrated
# AppImages have their entry in ~/.local/share/applications.
DESKTOP_ENTRY_DIRS = [os.path.join(HOME, ".local/share/applications"),
                "/usr/local/share/applications", "/usr/share/applications",
                os.path.join(HOME, ".local/share/flatpak/exports/share/applications"),
                "/var/lib/flatpak/exports/share/applications"]

# common ways of naming apps (after norm): -> .desktop id, without .desktop
# i18n-data-begin: Italian and English app names the user may say
SYNONYMS = {
    "browser": "firefox-esr", "internet": "firefox-esr", "navigatore": "firefox-esr",
    "web": "firefox-esr", "firefox": "firefox-esr",
    "posta": "thunderbird", "email": "thunderbird", "e-mail": "thunderbird", "mail": "thunderbird",
    "posta elettronica": "thunderbird", "thunderbird": "thunderbird",
    "terminale": "foot", "console": "foot", "shell": "foot", "prompt dei comandi": "foot",
    "file": "thunar", "gestore file": "thunar", "gestore dei file": "thunar", "esplora file": "thunar",
    "esplora risorse": "thunar", "cartelle": "thunar", "thunar": "thunar",
    "editor": "org.gnome.TextEditor", "editor di testo": "org.gnome.TextEditor",
    "blocco note": "org.gnome.TextEditor", "note": "org.gnome.TextEditor",
    "calcolatrice": "org.gnome.Calculator", "calcolatore": "org.gnome.Calculator",
    "impostazioni": "zeta-settings", "preferenze": "zeta-settings", "settings": "zeta-settings",
    "pannello di controllo": "zeta-settings",
    "monitor": "zeta-monitor", "monitor di sistema": "zeta-monitor", "gestione attivita": "zeta-monitor",
    "task manager": "zeta-monitor", "gestione processi": "zeta-monitor",
    "sicurezza": "zeta-security", "security": "zeta-security",
    "zeta share": "zeta-share", "share": "zeta-share", "localsend": "zeta-share", "condivisione": "zeta-share",
    "pacchetti": "synaptic", "gestore pacchetti": "synaptic", "synaptic": "synaptic",
    "visualizzatore immagini": "org.gnome.eog", "foto": "org.gnome.eog", "immagini": "org.gnome.eog",
    "pdf": "org.gnome.Evince", "lettore pdf": "org.gnome.Evince", "documenti pdf": "org.gnome.Evince",
    "video": "mpv", "lettore video": "mpv", "musica": "mpv", "lettore multimediale": "mpv",
    "archivi": "org.gnome.FileRoller", "gestore archivi": "org.gnome.FileRoller",
    "zeta": "zeta-core", "zeta core": "zeta-core", "assistente": "zeta-core",
    "testo da immagine": "zeta-text-capture", "ocr": "zeta-text-capture", "stampanti avanzate": "system-config-printer",
    "cerca": "zeta-search", "ricerca": "zeta-search",
    # in English
    "web browser": "firefox-esr", "email client": "thunderbird", "mail client": "thunderbird",
    "terminal": "foot", "command prompt": "foot", "command line": "foot",
    "files": "thunar", "file manager": "thunar", "file explorer": "thunar", "explorer": "thunar",
    "folders": "thunar", "text editor": "org.gnome.TextEditor", "notepad": "org.gnome.TextEditor",
    "notes": "org.gnome.TextEditor", "calculator": "org.gnome.Calculator",
    "system monitor": "zeta-monitor", "activity monitor": "zeta-monitor", "process manager": "zeta-monitor",
    "control panel": "zeta-settings", "preferences": "zeta-settings",
    "sharing": "zeta-share", "packages": "synaptic", "package manager": "synaptic",
    "image viewer": "org.gnome.eog", "photos": "org.gnome.eog", "pictures": "org.gnome.eog",
    "images": "org.gnome.eog", "pdf viewer": "org.gnome.Evince", "pdf reader": "org.gnome.Evince",
    "video player": "mpv", "media player": "mpv", "music": "mpv", "music player": "mpv",
    "archives": "org.gnome.FileRoller", "archive manager": "org.gnome.FileRoller",
    "assistant": "zeta-core", "text from image": "zeta-text-capture", "advanced printers": "system-config-printer",
    "printer settings": "system-config-printer", "search": "zeta-search",
}
# i18n-data-end

_PLACEHOLDER = re.compile(r"%[a-zA-Z]")


class App:
    __slots__ = ("id", "name", "argv", "binary", "classes", "names", "is_hidden", "icon")

    def __repr__(self):
        return "App(%s)" % self.id


def _read_desktop(path):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    try:
        cp.read(path, encoding="utf-8")
        d = dict(cp["Desktop Entry"])
    except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
        return None
    if d.get("Type") != "Application" or not d.get("Exec"):
        return None
    return d


_CACHE = {"when": 0.0, "app": []}


def installed_apps(reload=False) -> list[App]:
    """Apps from the .desktop files (hidden entries are kept, to recognize
    windows, but they are not offered). Re-read at most every 30 seconds."""
    if not reload and _CACHE["app"] and time.monotonic() - _CACHE["when"] < 30:
        return _CACHE["app"]
    try:
        import sys
        sys.path.insert(0, "/usr/lib/zeta")
        from ui.app_names import NAMES
    except ImportError:
        NAMES = {}
    seen, out = set(), []
    lang = language()
    for d in DESKTOP_ENTRY_DIRS:
        for f in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            aid = os.path.basename(f)[:-8]
            if aid in seen:
                continue                      # already seen in a higher-precedence folder
            info = _read_desktop(f)
            if not info:
                continue
            seen.add(aid)
            a = App()
            a.id = aid
            a.name = NAMES.get(aid + ".desktop") or info.get("Name[%s]" % lang) or info.get("Name") or aid
            try:
                import shlex
                a.argv = [x for x in shlex.split(_PLACEHOLDER.sub("", info["Exec"])) if x]
            except ValueError:
                a.argv = info["Exec"].split()
            while a.argv and (a.argv[0] == "env" or "=" in a.argv[0]):
                a.argv.pop(0)
            a.binary = os.path.basename(a.argv[0]) if a.argv else ""
            classes = {norm(aid), norm(aid.rsplit(".", 1)[-1]), norm(a.binary)}
            if info.get("StartupWMClass"):
                classes.add(norm(info["StartupWMClass"]))
            a.classes = {c for c in classes if c}
            # the names the user may call it by: in English, in Italian and
            # in the system language
            names = {norm(a.name), norm(info.get("Name", "")), norm(info.get("Name[it]", "")),
                    norm(info.get("Name[%s]" % lang, "")),
                    norm(info.get("GenericName[it]", "")), norm(info.get("GenericName", "")),
                    norm(info.get("GenericName[%s]" % lang, "")),
                    norm(aid), norm(aid.rsplit(".", 1)[-1]), norm(a.binary)}
            for k in ("Keywords[it]", "Keywords", "Keywords[%s]" % lang):
                names |= {norm(x) for x in info.get(k, "").split(";") if len(x) > 2}
            a.names = {n for n in names if n}
            a.is_hidden = info.get("NoDisplay", "").lower() == "true" or info.get("Hidden", "").lower() == "true"
            a.icon = info.get("Icon", "")
            out.append(a)
    _CACHE.update(when=time.monotonic(), app=out)
    return out


# generic words that name a role, not an app: they map to the app chosen in
# Settings › Default Apps («apri il browser» opens the chosen one)
# i18n-data-begin: Italian and English role names the user may say
ROLES = {
    "browser": "browser", "internet": "browser", "navigatore": "browser", "web": "browser",
    "posta": "mail", "email": "mail", "e-mail": "mail", "mail": "mail", "posta elettronica": "mail",
    "terminale": "terminal", "console": "terminal", "shell": "terminal", "prompt dei comandi": "terminal",
    "file": "file", "gestore file": "file", "gestore dei file": "file", "esplora file": "file",
    "esplora risorse": "file",
    "editor": "editor", "editor di testo": "editor", "blocco note": "editor",
    "lettore video": "video", "lettore multimediale": "video",
    "visualizzatore immagini": "images", "lettore pdf": "pdf",
    # in English
    "web browser": "browser", "email client": "mail", "mail client": "mail",
    "terminal": "terminal", "command prompt": "terminal", "command line": "terminal",
    "file manager": "file", "file explorer": "file", "files": "file",
    "text editor": "editor", "notepad": "editor",
    "video player": "video", "media player": "video", "music player": "video",
    "image viewer": "images", "photo viewer": "images", "pdf viewer": "pdf", "pdf reader": "pdf",
}
# i18n-data-end


def _default_app(role: str) -> str | None:
    try:
        import sys
        if "/usr/lib/zeta" not in sys.path:
            sys.path.insert(0, "/usr/lib/zeta")
        from system import default_apps
        aid = default_apps.current(role)
    except Exception:  # noqa: BLE001 - without GIO, the fixed synonyms are used
        return None
    return aid[:-8] if aid and aid.endswith(".desktop") else aid


def find_app(text: str, roles: bool = True) -> App | None:
    """The app being talked about: synonyms, exact name, then words of the name."""
    t = norm(text)
    # i18n-data-begin: Italian and English articles and words for "app"
    t = re.sub(r"^(?:(?:il|lo|la|i|gli|le|un|una|uno|the|a|an|my)\s+|l'\s*)", "", t)
    t = re.sub(r"\s+(app|applicazione|programma|application|program)$", "", t)
    t = re.sub(r"^(app|applicazione|programma|application|program)\s+", "", t)
    # i18n-data-end
    if not t:
        return None
    all_apps = installed_apps()
    by_id = {a.id: a for a in all_apps}
    if roles and t in ROLES:
        choice = _default_app(ROLES[t])
        if choice in by_id:
            return by_id[choice]
    if t in SYNONYMS and SYNONYMS[t] in by_id:
        return by_id[SYNONYMS[t]]
    visible = [a for a in all_apps if not a.is_hidden]
    # for the same executable the real app wins, not its settings window
    # («mousepad» -> Mousepad, not «Impostazioni di Mousepad»)
    visible.sort(key=lambda a: ("settings" in a.id.lower() or "preferen" in a.id.lower()))
    for a in visible:
        if t == norm(a.name) or t in (norm(a.id), norm(a.id.rsplit(".", 1)[-1])):
            return a
    for a in visible:
        if t == a.binary.lower():
            return a
    for a in visible:
        if t in a.names:
            return a
    # whole word inside a name («text editor» -> «Editor di testo» no; «firefox esr» yes)
    for a in visible:
        if any(re.search(r"\b%s\b" % re.escape(t), n) for n in a.names if len(t) > 3):
            return a
    # a description: «quel programma per le email», «qualcosa per la musica»
    # i18n-data-begin: Italian and English description patterns
    m = re.match(r"^(?:quel|quello|qualcosa|qualche|un|una|il|la|l')?\s*"
                 r"(?:programma|app|applicazione|cosa|coso|roba)?\s*"
                 r"(?:per|della|delle|dei|del|di|da)\s+(?:(?:il|lo|la|l'|i|gli|le|un|una)\s*)?(.+)$", t) or \
        re.match(r"^(?:(?:that|some|something|an|a)\s+)?(?:(?:program|app|application|thing)\s+)?"
                 r"(?:for|to)\s+(?:(?:the|my|a|an)\s+)?(.+)$", t)
    # i18n-data-end
    if m and m.group(1) != t:
        return find_app(m.group(1), roles)
    return None


def app_of_window(w: dict) -> App | None:
    class_name = norm(w.get("class") or w.get("initialClass") or "")
    prog = program_name(cmdline(int(w.get("pid") or 0))) if w.get("pid") else ""
    for a in installed_apps():
        if class_name and (class_name in a.classes or class_name.rsplit(".", 1)[-1] in a.classes):
            return a
    for a in installed_apps():
        if prog and prog == a.binary:
            return a
    return None


def windows_of(app: App) -> list[dict]:
    """The open windows of an app (by class or by process)."""
    out = []
    for w in windows():
        class_name = norm(w.get("class") or w.get("initialClass") or "")
        if class_name and (class_name in app.classes or class_name.rsplit(".", 1)[-1] in app.classes):
            out.append(w)
            continue
        if w.get("pid") and program_name(cmdline(int(w["pid"]))) == app.binary:
            out.append(w)
    out.sort(key=lambda w: w.get("focusHistoryID", 1 << 30))
    return out


def processes_of(app: App) -> list[int]:
    """The user's processes that are that app (by program name)."""
    return [pid for pid, c in user_processes() if program_name(c) == app.binary]


def wait(condition, seconds: float, step: float = 0.2) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if condition():
                return True
        except Exception:  # noqa: BLE001 - a failing check counts as «not yet»
            pass
        time.sleep(step)
    try:
        return bool(condition())
    except Exception:  # noqa: BLE001
        return False
