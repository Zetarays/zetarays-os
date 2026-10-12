# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — the single application registry.

Each part of the system used to look for apps on its own (menu, Dock,
search, desktop, assistant): five lists, five ways of finding the icon, five
ways of launching them. The same app could have the right icon in the menu
and the generic one in the Dock, or show up in search but not in the menu.
Here there is a single list, read from the standard .desktop files:

  - Debian packages (/usr/share/applications), including those installed by
    hand in /usr/local or in home;
  - Flatpak ("exports" folders, even if the session does not know them);
  - AppImage: integrated by integrate_appimages() with their own .desktop file,
    without ever running the file to read its name and icon;
  - programs in /opt with a .desktop file next to them.

For each app: name, icon (also as a file, for the Dock), description,
categories, command, executable, .desktop file, source, and on request
(details()) package, version, architecture and installation folder.
System apps (ZETA, file manager, terminal, Settings...) are protected: they
cannot be hidden or uninstalled from the menu.

No daemons: the list is re-read only if an app folder has changed
(comparing modification times, a few stat calls); icons are indexed once
per process.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from i18n import tr  # noqa: E402

try:
    from ui.app_names import NAMES
except ImportError:          # used outside /usr/lib/zeta
    NAMES = {}

HOME = os.path.expanduser("~")
CFG = os.path.join(HOME, ".config", "zeta")
HIDDEN_APPS_FILE = os.path.join(CFG, "hidden-apps.json")
APPIMAGE_ICONS_FOLDER = os.path.join(HOME, ".local", "share", "zeta", "appimage")
USER_APPS = os.path.join(HOME, ".local", "share", "applications")
APPIMAGE_PREFIX = "zeta-appimage-"
GENERIC_ICON = "/usr/share/icons/zeta/scalable/apps/zeta-app.svg"

FLATPAK_EXPORTS = ["/var/lib/flatpak/exports/share",
                   os.path.join(HOME, ".local", "share", "flatpak", "exports", "share")]



def _appimage_folders():
    """Folders searched for AppImages (the most common ones: where the browser
    puts them, where people "install" them, /opt for the whole system).
    Downloads and Desktop are the XDG ones (their name changes with the
    language); ~/Applications is the standard AppImage folder. The Italian
    folders of earlier installs are kept too, if they exist."""
    folders = [os.path.join(HOME, "Applications")]
    for which in (GLib.UserDirectory.DIRECTORY_DOWNLOAD, GLib.UserDirectory.DIRECTORY_DESKTOP):
        d = GLib.get_user_special_dir(which)
        if d and os.path.normpath(d) != os.path.normpath(HOME):
            folders.append(d)
    # Italian folder names of earlier installs  # i18n-data
    folders += [os.path.join(HOME, n) for n in ("Downloads", "Desktop", "Applicazioni",  # i18n-data
                                                 "Scaricati", "Scrivania")]  # i18n-data
    folders += [os.path.join(HOME, ".local", "bin"), "/opt"]
    seen, out = set(), []
    for d in folders:
        d = os.path.normpath(d)
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


APPIMAGE_FOLDERS = _appimage_folders()

# Service entries: they exist for the programs that open them, but in the
# menu they are duplicates or technical tools already reachable from Settings.
SERVICE_APPS = {
    "footclient.desktop", "foot-server.desktop", "thunar-settings.desktop",
    "thunar-bulk-rename.desktop", "thunar-volman-settings.desktop",
    "nm-connection-editor.desktop", "blueman-manager.desktop", "blueman-adapters.desktop",
    "pavucontrol.desktop", "org.pulseaudio.pavucontrol.desktop", "lxpolkit.desktop",
    "debian-xterm.desktop", "debian-uxterm.desktop", "display-im6.q16.desktop",
    "org.gnome.Evince-previewer.desktop", "calamares-install-debian.desktop", "calamares.desktop",
    "vim.desktop", "nvim.desktop", "htop.desktop", "nm-applet.desktop",
    "org.freedesktop.IBus.Setup.desktop",
    # duplicate: ZETA RAYS Monitor already covers processes, resources and network
    "org.gnome.SystemMonitor.desktop", "gnome-system-monitor.desktop",
}

# Apps that are part of the system: they cannot be removed from the menu or
# uninstalled from here (still possible from the terminal, for those who
# know what they are doing).
PROTECTED_APPS = {
    "thunar.desktop", "org.xfce.thunar.desktop", "foot.desktop", "synaptic.desktop",
    "localsend_app.desktop", "system-config-printer.desktop",
}

# Packages an uninstall must never take away (including as an apt side
# effect: removing a library removes whatever uses it).
SYSTEM_PACKAGES = {
    "hyprland", "waybar", "sddm", "xwayland", "foot", "thunar", "network-manager",
    "nftables", "pipewire", "wireplumber", "pipewire-pulse", "python3", "python3-gi",
    "gir1.2-gtk-4.0", "gir1.2-adw-1", "libgtk-4-1", "libadwaita-1-0",
    "gir1.2-gtk4layershell-1.0", "libgtk4-layer-shell0", "mako-notifier", "swaybg",
    "hypridle", "hyprlock", "wl-clipboard", "xdg-desktop-portal", "xdg-desktop-portal-gtk",
    "xdg-desktop-portal-hyprland", "polkitd", "mate-polkit", "sudo", "apt", "dpkg",
    "systemd", "dbus", "cups", "avahi-daemon", "localsend", "synaptic", "flatpak",
    "calamares", "grub-common", "shim-signed", "linux-base", "zram-tools", "fonts-roboto",
}

SOURCES = {
    "zeta": tr("ZETA RAYS system"),
    "apt": tr("System package (APT)"),
    "flatpak": "Flatpak",
    "appimage": "AppImage",
    "opt": tr("Installed manually (/opt)"),
    "local": tr("Installed manually (/usr/local)"),
    "user": tr("User shortcut"),
}

# Exec field codes (%f %U...): removed; "%%" means a literal "%" (.desktop spec)
_FIELD_CODES = re.compile(r"%(.)")


def _strip_field_codes(command):
    return _FIELD_CODES.sub(lambda m: "%" if m.group(1) == "%" else
                       "" if m.group(1) in "fFuUdDnNickvm" else m.group(0), command)


@dataclass
class App:
    id: str
    name: str
    description: str
    icon: str                     # theme icon name or path
    categories: list
    command: str
    argv: list
    executable: str                # program path ("" if not found)
    desktop: str                   # .desktop file
    source: str                     # key of SOURCES
    protected: bool
    is_hidden: bool                 # hidden by the user
    service: bool                 # technical entry, never in the menu
    launchable: bool
    keywords: list = field(default_factory=list)
    flatpak_id: str = ""
    appimage: str = ""
    wm_class: str = ""
    original: str = ""            # the package's .desktop (also with a custom icon)
    custom_icon: bool = False

    @property
    def in_menu(self):
        return not (self.is_hidden or self.service) and self.launchable

    def info(self):
        return Gio.DesktopAppInfo.new_from_filename(self.desktop) if self.desktop else None


# ------------------------------------------------------------- folders
def data_folders():
    """XDG data folders, plus the Flatpak ones even if the session does not
    have them in XDG_DATA_DIRS (for example after installing Flatpak without
    logging in again)."""
    dirs = [GLib.get_user_data_dir()] + list(GLib.get_system_data_dirs())
    for d in FLATPAK_EXPORTS:
        if d not in dirs:
            dirs.append(d)
    seen, out = set(), []
    for d in dirs:
        d = os.path.normpath(d)
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def app_folders():
    return [os.path.join(d, "applications") for d in data_folders()]


def _signature():
    """Modification times of the app folders: if they do not change, the
    list read earlier is still valid."""
    f = []
    for d in app_folders() + [CFG]:
        try:
            f.append((d, os.stat(d).st_mtime_ns))
        except OSError:
            f.append((d, 0))
    try:
        f.append((HIDDEN_APPS_FILE, os.stat(HIDDEN_APPS_FILE).st_mtime_ns))
    except OSError:
        pass
    return tuple(f)


# ------------------------------------------------------------- hidden
def _read_hidden():
    try:
        with open(HIDDEN_APPS_FILE) as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except (OSError, ValueError):
        return set()


def _write_hidden(item_set):
    os.makedirs(CFG, exist_ok=True)
    tmp = HIDDEN_APPS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(item_set), f, indent=1)
    os.replace(tmp, HIDDEN_APPS_FILE)


# ------------------------------------------------------------- reading
def _argv(command):
    try:
        ok, argv = GLib.shell_parse_argv(_strip_field_codes(command or "").strip())
    except GLib.Error:
        return []
    return list(argv) if ok else []


def _program_index(argv):
    """Position of the program in argv (skips "env VAR=..." and "env -u VAR")."""
    i = 0
    if argv and os.path.basename(argv[0]) == "env":
        i = 1
        while i < len(argv) and ("=" in argv[i] or argv[i].startswith("-")):
            i += 2 if argv[i] in ("-u", "--unset") else 1
    return i


def _program_path(argv, desktop_folder=None):
    """Real path of the launched program (skips "env VAR=...")."""
    i = _program_index(argv)
    if i >= len(argv):
        return ""
    prog = argv[i]
    if os.path.isabs(prog):
        return prog if os.access(prog, os.X_OK) else ""
    found = GLib.find_program_in_path(prog)
    if found:
        return found
    if desktop_folder:
        nearby = os.path.join(desktop_folder, prog)
        if os.path.isfile(nearby) and os.access(nearby, os.X_OK):
            return nearby
    return ""


def _source(app_id, desktop, kf_get):
    if kf_get("X-ZETA-AppImage"):
        return "appimage"
    if kf_get("X-ZETA-Opt"):
        return "opt"
    if kf_get("X-Flatpak") or "/flatpak/exports/" in desktop:
        return "flatpak"
    if app_id.startswith(("zeta-", "org.zetarays.")) and not app_id.startswith(APPIMAGE_PREFIX):
        return "zeta"
    real_path = os.path.realpath(desktop)
    if real_path.startswith("/opt/"):
        return "opt"
    if desktop.startswith(HOME):
        return "user"
    if desktop.startswith("/usr/local/"):
        # ZETA RAYS copy of a package's entry (hook 0500, ZETA Share): the
        # source is still the package
        if os.path.exists(os.path.join("/usr/share/applications", os.path.basename(desktop))):
            return "apt"
        return "local"
    return "apt"


def _from_info(info, hidden):
    app_id = info.get_id() or os.path.basename(info.get_filename() or "")
    desktop = info.get_filename() or ""

    def kf_get(key):
        try:
            return info.get_string(key) or ""
        except (TypeError, GLib.Error):
            return ""

    command = info.get_commandline() or ""
    argv = _argv(command)
    # icon changed by the user: the entry in ~/.local/share/applications is
    # a copy of the package's, which remains the real source
    original = kf_get("X-ZETA-Original") or desktop
    source = _source(app_id, original, kf_get)
    executable = _program_path(argv, os.path.dirname(os.path.realpath(desktop)) if desktop else None)
    if source == "flatpak" and not executable:
        executable = shutil.which("flatpak") or ""
    if source == "user" and executable.startswith("/opt/"):
        source = "opt"
    icon = info.get_icon()
    if isinstance(icon, Gio.FileIcon):
        icon_str = icon.get_file().get_path() or ""
    elif isinstance(icon, Gio.ThemedIcon):
        names = icon.get_names()
        icon_str = names[0] if names else ""
    else:
        icon_str = ""
    name = NAMES.get(app_id) or info.get_display_name() or info.get_name() or app_id
    if source == "appimage":
        name = info.get_name() or name
    return App(
        id=app_id, name=name, description=info.get_description() or "",
        icon=icon_str, categories=[c for c in (info.get_categories() or "").split(";") if c],
        command=command, argv=argv, executable=executable, desktop=desktop, source=source,
        protected=(source == "zeta" or app_id in PROTECTED_APPS),
        is_hidden=app_id in hidden,
        service=app_id in SERVICE_APPS or (app_id == "zeta-install-system.desktop"
                                        and not os.path.exists("/run/live/medium")),
        launchable=bool(executable),
        keywords=list(info.get_keywords() or []),
        flatpak_id=kf_get("X-Flatpak"), appimage=kf_get("X-ZETA-AppImage"),
        wm_class=info.get_startup_wm_class() or "",
        original=original, custom_icon=bool(kf_get("X-ZETA-Custom-Icon")),
    )


_CACHE = {"signature": None, "app": []}


def _invalidate():
    _CACHE["signature"] = None


def _desktop_entries():
    """(id, path) of every .desktop entry, in XDG precedence order (user,
    then system folders, then Flatpak). Subfolders give ids with a dash
    (kde/app.desktop -> kde-app.desktop)."""
    for folder in app_folders():
        if not os.path.isdir(folder):
            continue
        for root, _dirs, files in os.walk(folder):
            rel = os.path.relpath(root, folder)
            for n in sorted(files):
                if n.endswith(".desktop"):
                    aid = n if rel == "." else rel.replace(os.sep, "-") + "-" + n
                    yield aid, os.path.join(root, n)


def all_apps(reread=False):
    """All apps (hidden and service ones too: the caller decides what to show).

    Files are read directly, not from the GIO cache: that one is updated late
    (via inotify), and right after an icon change the menu or the Dock would
    still have shown the old one."""
    signature = _signature()
    if not reread and _CACHE["signature"] == signature:
        return _CACHE["app"]
    _INDEX.clear()                 # new icons and versions along with new apps
    _MISSING.clear()
    _VERSIONS.clear()
    hidden = _read_hidden()
    seen, app = set(), []
    for aid, path in _desktop_entries():
        if aid in seen:
            continue                # an entry with higher precedence already defined it
        seen.add(aid)
        try:
            info = Gio.DesktopAppInfo.new_from_filename(path)
        except TypeError:
            info = None
        # hidden (Hidden=true) or TryExec program missing: per the standard
        # the entry does not exist, and it also masks those below it
        if info is None or info.get_is_hidden() or not info.should_show():
            continue
        a = _from_info(info, hidden)
        a.id = aid
        app.append(a)
    app.sort(key=lambda a: GLib.utf8_collate_key(a.name.casefold(), -1))
    _CACHE.update(signature=signature, app=app)
    return app


def menu():
    """The apps to show in the menu, in search and in pickers."""
    return [a for a in all_apps() if a.in_menu]


def find(key):
    """By .desktop id (with or without ".desktop"), .desktop file or name."""
    if not key:
        return None
    k = key if key.endswith(".desktop") else key + ".desktop"
    listing = all_apps()
    for a in listing:
        if a.id == k or a.desktop == key:
            return a
    if os.path.isabs(key):
        real_path = os.path.realpath(key)
        for a in listing:
            if a.desktop and os.path.realpath(a.desktop) == real_path:
                return a
    lowered = key.casefold()
    for a in listing:
        if a.name.casefold() == lowered or a.id[:-8].casefold() == lowered:
            return a
    # the program name ("gnome-calculator", "blender")
    for a in listing:
        if a.executable and os.path.basename(a.executable).casefold() == lowered:
            return a
    return None


def from_command(cmd):
    """The app matching a command (Dock entries saved without an id)."""
    argv = _argv(cmd)
    if not argv:
        return None
    prog = _program_path(argv) or argv[0]
    base = os.path.basename(prog)
    for a in all_apps():
        if a.executable and (a.executable == prog or os.path.basename(a.executable) == base) \
                and a.source != "flatpak":
            return a
    return None


# ------------------------------------------------------------- icons
_INDEX = {}
_MISSING = set()
_CONTEXTS = ("apps", "applications", "categories", "mimetypes", "places", "devices", "status",
             "actions", "emblems", "ui", "legacy")


def _index(base):
    """icon name -> [(size, path)] for a theme (only once)."""
    if base in _INDEX:
        return _INDEX[base]
    idx = {}
    for root, _dirs, files in os.walk(base):
        rel = os.path.relpath(root, base)
        pieces = rel.split(os.sep)
        if not any(p in _CONTEXTS for p in pieces):
            continue
        dim = 0
        for p in pieces:
            m = re.match(r"^(\d+)(x\d+)?(@\d+x)?$", p)
            if m:
                dim = int(m.group(1))
            elif p == "scalable":
                dim = 10000
        for f in files:
            name, ext = os.path.splitext(f)
            if ext in (".svg", ".png", ".xpm"):
                idx.setdefault(name, []).append((dim, os.path.join(root, f)))
    _INDEX[base] = idx
    return idx


def _themes():
    base_dirs = [os.path.join(HOME, ".local", "share", "icons"), os.path.join(HOME, ".icons")]
    base_dirs += [os.path.join(d, "icons") for d in data_folders()]
    out = []
    for theme in ("zeta", "Adwaita", "hicolor"):
        for b in base_dirs:
            p = os.path.join(b, theme)
            if os.path.isdir(p):
                out.append(p)
    return out


def gtk_icons(display=None):
    """Add the Flatpak and home icons to the GTK theme even if the session
    started before they existed (first Flatpak app installed while the
    session was open: the menu showed the "missing image" icon)."""
    try:
        from gi.repository import Gdk, Gtk
        theme = Gtk.IconTheme.get_for_display(display or Gdk.Display.get_default())
    except (ImportError, ValueError, TypeError):
        return
    already = set(theme.get_search_path() or [])
    for d in FLATPAK_EXPORTS + [os.path.join(HOME, ".local", "share")]:
        p = os.path.join(d, "icons")
        if os.path.isdir(p) and p not in already:
            theme.add_search_path(p)


def icon_file(name, size=64):
    """Icon name (or path) -> file to display, as GTK would do it: the
    ZETA RAYS theme, then Adwaita, hicolor (all sizes, including Flatpak and
    home apps) and /usr/share/pixmaps. Needed by whatever does not draw with
    GTK (the Waybar Dock wants a file)."""
    if not name:
        return GENERIC_ICON
    if os.path.isabs(name):
        return name if os.path.exists(name) else GENERIC_ICON
    found = _search_icon(name, size)
    if found is None and _INDEX and name not in _MISSING:
        # app just installed: the index is stale. Only once per name, or an
        # icon that does not exist would rebuild the index on every redraw
        _MISSING.add(name)
        _INDEX.clear()
        found = _search_icon(name, size)
    return found or GENERIC_ICON


def _search_icon(name, size):
    for theme in _themes():
        candidates = _index(theme).get(name)
        if candidates:
            # scalable first, then the closest size that is not smaller
            candidates = sorted(candidates, key=lambda c: (c[0] < size, abs(c[0] - size)))
            if any(c[0] == 10000 for c in candidates):
                return next(c[1] for c in candidates if c[0] == 10000)
            return candidates[0][1]
    for d in ["/usr/share/pixmaps"] + [os.path.join(x, "pixmaps") for x in data_folders()]:
        for ext in (".svg", ".png", ".xpm"):
            p = os.path.join(d, name + ext)
            if os.path.exists(p):
                return p
    return None


# ------------------------------------------------------------- details
def _output(argv, timeout=8):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LANG="C", LC_ALL="C"))
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def package_of(path):
    """The Debian package that installed a file ("" if none)."""
    if not path:
        return ""
    for p in (path, os.path.realpath(path)):
        out = _output(["dpkg-query", "-S", p])
        if out:
            return out.split(":", 1)[0].split(",")[0].strip()
    return ""


def app_package(app):
    """The Debian package of an app (its menu entry, also when redefined by
    ZETA RAYS in /usr/local, or its program)."""
    return (package_of(app.original or app.desktop)
            or package_of(os.path.join("/usr/share/applications", app.id))
            or package_of(app.executable))


def _ha(kf, group, key):
    """GLib.KeyFile.has_key is not available from Python."""
    try:
        kf.get_value(group, key)
        return True
    except GLib.Error:
        return False


def _arch_elf(path):
    try:
        with open(path, "rb") as f:
            head = f.read(20)
    except OSError:
        return ""
    if head[:4] != b"\x7fELF":
        return ""
    machine = struct.unpack("<H", head[18:20])[0]
    return {0x3E: "amd64 (x86-64)", 0xB7: "arm64 (aarch64)", 0x03: "i386",
            0x28: "armhf"}.get(machine) or tr("other ({code})").format(code="%#x" % machine)


def details(app):
    """The complete information (slower: queries dpkg or flatpak).
    List of (label, value, path_to_open_or_None)."""
    lines = [(tr("Application"), app.name, None)]
    if app.description:
        lines.append((tr("Description"), app.description, None))
    lines.append((tr("Source"), SOURCES.get(app.source, app.source), None))
    version, arch, folder, entry = "", "", "", None
    if app.source == "flatpak":
        out = _output(["flatpak", "info", app.flatpak_id or app.id[:-8]])
        fields = {}
        for r in out.splitlines():
            if ":" in r:
                k, _, v = r.partition(":")
                fields[k.strip()] = v.strip()
        version = fields.get("Version", "")
        arch = fields.get("Arch", "")
        folder = fields.get("Location", "")
        entry = (tr("Flatpak ID"), app.flatpak_id or app.id[:-8], None)
        inst = fields.get("Installation", "")
        if inst:
            lines.append((tr("Installation"),
                          tr("For everyone") if inst == "system" else tr("Only for you"), None))
    elif app.source == "appimage":
        entry = (tr("AppImage file"), app.appimage, app.appimage)
        arch = _arch_elf(app.appimage)
        folder = os.path.dirname(app.appimage)
        try:
            kf = GLib.KeyFile()
            kf.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
            version = kf.get_string("Desktop Entry", "X-AppImage-Version")
        except GLib.Error:
            pass
    else:
        pkg = app_package(app)
        if pkg:
            out = _output(["dpkg-query", "-W", "-f", "${Version}\t${Architecture}", pkg])
            if "\t" in out:
                version, arch = out.split("\t", 1)
            entry = (tr("Package"), pkg, None)
        if app.executable:
            real_path = os.path.realpath(app.executable)
            folder = os.path.dirname(real_path)
            arch = arch or _arch_elf(real_path)
    if entry:
        lines.append(entry)
    if version:
        lines.append((tr("Version"), version, None))
    if arch:
        lines.append((tr("Architecture"), arch, None))
    if app.executable:
        lines.append((tr("Executable"), app.executable, app.executable))
    if app.desktop:
        lines.append((tr("Menu entry (.desktop)"), app.original or app.desktop,
                      app.original or app.desktop))
    if app.custom_icon:
        lines.append((tr("Icon you chose"), app.icon, app.icon))
    if folder:
        lines.append((tr("Folder"), folder, folder))
    if app.protected:
        lines.append((tr("Status"), tr("System component (protected)"), None))
    return lines


_VERSIONS = {}


def version(app):
    """Only the version (for search), cached per process."""
    if app.id in _VERSIONS:
        return _VERSIONS[app.id]
    v = ""
    if app.source == "flatpak":
        for r in _output(["flatpak", "info", app.flatpak_id or app.id[:-8]]).splitlines():
            if r.strip().startswith("Version:"):
                v = r.split(":", 1)[1].strip()
    elif app.source == "appimage":
        try:
            kf = GLib.KeyFile()
            kf.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
            v = kf.get_string("Desktop Entry", "X-AppImage-Version")
        except GLib.Error:
            pass
    elif app.source in ("apt", "zeta"):
        pkg = app_package(app)
        if pkg:
            v = _output(["dpkg-query", "-W", "-f", "${Version}", pkg]).strip()
    _VERSIONS[app.id] = v
    return v


def position(app):
    """The file to show with "Open file location"."""
    if app.source == "appimage" and app.appimage:
        return app.appimage
    if app.source == "flatpak":
        for base in ("/var/lib/flatpak/app", os.path.join(HOME, ".local/share/flatpak/app")):
            p = os.path.join(base, app.flatpak_id or app.id[:-8], "current", "active")
            if os.path.exists(p):
                return os.path.realpath(p)
        return app.desktop
    if app.executable:
        return os.path.realpath(app.executable) if app.source == "opt" else app.executable
    return app.desktop


_CHILDREN = set()


def spawn(argv, **kw):
    """Start a detached program and reap its exit (GLib child watch): in
    long-running processes (menu, search) a forgotten Popen stayed a zombie.
    The Popen is kept until GLib has reaped it, so Python does not try to
    reap it a second time."""
    kw.setdefault("stdout", subprocess.DEVNULL)
    kw.setdefault("stderr", subprocess.DEVNULL)
    kw.setdefault("start_new_session", True)
    try:
        p = subprocess.Popen(argv, **kw)
    except OSError:
        return None
    _CHILDREN.add(p)

    def finished(_pid, state, proc=p):
        proc.returncode = state
        _CHILDREN.discard(proc)
    GLib.child_watch_add(GLib.PRIORITY_DEFAULT_IDLE, p.pid, finished)
    return p


def show_in_file_manager(path):
    """Open the file manager on the folder with the file selected (like
    "Show in Finder"), through the standard FileManager1 interface."""
    if not path:
        return False
    uri = Gio.File.new_for_path(path).get_uri()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                      "org.freedesktop.FileManager1",
                      "ShowFolders" if os.path.isdir(path) else "ShowItems",
                      GLib.Variant("(ass)", ([uri], "")), None,
                      Gio.DBusCallFlags.NONE, 5000, None)
        return True
    except GLib.Error:
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        return spawn(["thunar", folder]) is not None


# ------------------------------------------------------------- actions
def _activate_dbus(info, timeout_ms=30000):
    """Start a D-Bus-activatable app (DBusActivatable=true: many Flatpak and
    GNOME apps) and wait for its answer, like "gio launch" does. Needed by
    short-lived callers: if the caller exits before the reply, dbus-daemon
    drops the pending activation and the app starts without a window."""
    app_id = (info.get_id() or "")[:-len(".desktop")] if (info.get_id() or "").endswith(".desktop") else ""
    if not app_id:
        return False
    path = "/" + app_id.replace(".", "/").replace("-", "_")
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(app_id, path, "org.freedesktop.Application", "Activate",
                      GLib.Variant("(a{sv})", ({},)), None, Gio.DBusCallFlags.NONE, timeout_ms, None)
        return True
    except GLib.Error:
        return False


def launch(app, context=None, wait=False):
    """Launch the app as from the menu (the same way everywhere).
    wait=True: the caller exits right after (zeta-app launch, used by the
    Dock): a D-Bus-activated app is started synchronously, see _activate_dbus."""
    info = app.info()
    if info is None:
        return False
    if wait and info.get_boolean("DBusActivatable") and _activate_dbus(info):
        return True
    if context is None:
        context = Gio.AppLaunchContext()
    context.unsetenv("LD_PRELOAD")
    try:
        return info.launch([], context)
    except GLib.Error:
        return False


def hide_away(app, is_hidden=True):
    """Remove the app from the menu (does not uninstall it). Not protected ones."""
    if app.protected and is_hidden:
        return False
    s = _read_hidden()
    (s.add if is_hidden else s.discard)(app.id)
    _write_hidden(s)
    _invalidate()
    return True


def desktop_folder():
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
    if d:
        return d
    old = os.path.join(HOME, "Scrivania")       # earlier installs  # i18n-data
    return old if os.path.isdir(old) else os.path.join(HOME, "Desktop")


def on_desktop(app):
    """The shortcut already on the Desktop for this app, or ""."""
    d = desktop_folder()
    try:
        names = os.listdir(d)
    except OSError:
        return ""
    real_path = os.path.realpath(app.desktop) if app.desktop else ""
    # a program in /opt: a symlink to its original .desktop (Send to ›
    # Desktop) or a copy with full paths also counts as "it"
    origin = ""
    if app.source == "opt" and app.desktop:
        kfa = GLib.KeyFile()
        try:
            kfa.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
            origin = _kf_str(kfa, "X-ZETA-Opt")
        except GLib.Error:
            pass
    for n in names:
        if not n.endswith(".desktop"):
            continue
        p = os.path.join(d, n)
        if n == app.id or (real_path and os.path.realpath(p) == real_path) \
                or (origin and os.path.realpath(p) == origin):
            return p
        try:
            kf = GLib.KeyFile()
            kf.load_from_file(p, GLib.KeyFileFlags.NONE)
            if _kf_str(kf, "X-ZETA-App") == app.id or (origin and _kf_str(kf, "X-ZETA-Origin") == origin):
                return p
        except GLib.Error:
            continue
    return ""


def add_to_desktop(app):
    """Desktop shortcut: a copy of the menu entry (same name, same icon,
    same command), which keeps working after a reboot and is removed like
    any other file. Never the same app twice."""
    already = on_desktop(app) or appimage_on_desktop(app)
    if already:
        return False, tr("“{name}” is already on the Desktop.").format(name=app.name)
    d = desktop_folder()
    os.makedirs(d, exist_ok=True)
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(app.desktop, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error as e:
        return False, tr("Can't read {path}: {error}").format(path=app.desktop, error=e.message)
    kf.set_string("Desktop Entry", "X-ZETA-App", app.id)
    if app.name != (kf.get_string("Desktop Entry", "Name") if _ha(kf, "Desktop Entry", "Name") else ""):
        kf.set_string("Desktop Entry", "Name", app.name)
    # relative Exec (program in /opt next to its .desktop): on the Desktop
    # the folder changes, so the full path is written
    if app.executable and app.argv and not os.path.isabs(app.argv[0]) \
            and not GLib.find_program_in_path(app.argv[0]):
        cmd = kf.get_string("Desktop Entry", "Exec")
        kf.set_string("Desktop Entry", "Exec", cmd.replace(app.argv[0], exec_program(app.executable), 1))
        if not _ha(kf, "Desktop Entry", "Path"):
            kf.set_string("Desktop Entry", "Path", os.path.dirname(app.executable))
    if app.icon and not os.path.isabs(app.icon) and icon_file(app.icon) == GENERIC_ICON:
        nearby_icon = _adjacent_icon(app)
        if nearby_icon:
            kf.set_string("Desktop Entry", "Icon", nearby_icon)
    dest = os.path.join(d, app.id)
    tmp = dest + ".tmp"
    with open(tmp, "w") as f:
        f.write(kf.to_data()[0])
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    try:
        Gio.File.new_for_path(dest).set_attribute_string(
            "metadata::trusted", "true", Gio.FileQueryInfoFlags.NONE, None)
    except GLib.Error:
        pass
    return True, tr("“{name}” added to the Desktop.").format(name=app.name)


def _adjacent_icon(app):
    for base in (app.executable, app.desktop):
        if not base:
            continue
        folder = os.path.dirname(os.path.realpath(base))
        for extension in ("svg", "png", "xpm"):
            p = os.path.join(folder, "%s.%s" % (app.icon, extension))
            if os.path.isfile(p):
                return p
    return ""


# ------------------------------------------------------------- custom icon
ICON_FOLDER = os.path.join(HOME, ".local", "share", "zeta", "icons")


def _copy_icon(image, name):
    """Copy the chosen image into the user's icons (scaled down if huge: a
    4000-pixel photo is useless at 64)."""
    os.makedirs(ICON_FOLDER, exist_ok=True)
    base = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "icon"
    ext = os.path.splitext(image)[1].lower()
    if ext in (".svg", ".svgz"):
        dest = os.path.join(ICON_FOLDER, base + ext)
        shutil.copyfile(image, dest)
        return dest
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pix = GdkPixbuf.Pixbuf.new_from_file(image)
    side = max(pix.get_width(), pix.get_height())
    if side > 512:
        k = 512 / side
        pix = pix.scale_simple(max(1, int(pix.get_width() * k)), max(1, int(pix.get_height() * k)),
                               GdkPixbuf.InterpType.BILINEAR)
    dest = os.path.join(ICON_FOLDER, base + ".png")
    pix.savev(dest, "png", [], [])
    return dest


def _fingerprint(path):
    """Content fingerprint: dpkg and Flatpak do not change the file dates
    (they carry the package's date), but the content does change."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return ""


def _write_kf(kf, dest):
    tmp = dest + ".tmp"
    with open(tmp, "w") as f:
        f.write(kf.to_data()[0])
    os.replace(tmp, dest)


def _icon_everywhere(app, icon):
    """The same icon in the Desktop shortcuts and in the Dock."""
    p = on_desktop(app)
    if p and not os.path.islink(p):
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
            kf.set_string("Desktop Entry", "Icon", icon)
            _write_kf(kf, p)
        except (GLib.Error, OSError):
            pass
    try:
        from system import dock
        dock.apply()                 # the Dock takes the icon from the registry
    except Exception:  # noqa: BLE001 — the Dock must not stop the change
        pass


def change_icon(app, image):
    """The chosen icon applies everywhere: menu, search, Dock, Desktop, Ctrl+Tab.

    For packaged apps a copy of their entry is written to
    ~/.local/share/applications (which takes precedence per the XDG
    standard) with the new icon: the package's file is not touched, and
    "Restore" removes only the copy. Entries already owned by the user
    (AppImages, hand-made shortcuts) are edited directly, remembering the
    previous icon."""
    try:
        icon = _copy_icon(image, app.id[:-8] if app.id.endswith(".desktop") else app.id)
    except (OSError, GLib.Error) as e:
        return False, tr("That image can't be used: {error}").format(error=e)
    os.makedirs(USER_APPS, exist_ok=True)
    g = "Desktop Entry"
    kf = GLib.KeyFile()
    flag = GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS
    own = app.desktop.startswith(USER_APPS + os.sep) and not app.custom_icon \
        and app.original == app.desktop
    try:
        if app.custom_icon or own:
            kf.load_from_file(app.desktop, flag)
            dest = app.desktop
            if own:
                kf.set_string(g, "X-ZETA-Original-Icon", app.icon)
        else:
            kf.load_from_file(app.original or app.desktop, flag)
            dest = os.path.join(USER_APPS, app.id)
            kf.set_string(g, "X-ZETA-Original", app.original or app.desktop)
            kf.set_string(g, "X-ZETA-Original-Signature", _fingerprint(app.original or app.desktop))
        kf.set_string(g, "Icon", icon)
        kf.set_string(g, "X-ZETA-Custom-Icon", "true")
        _write_kf(kf, dest)
    except (GLib.Error, OSError) as e:
        return False, tr("Couldn't change the icon: {error}").format(error=e)
    _invalidate()
    _icon_everywhere(app, icon)
    return True, tr("New icon for “{name}”.").format(name=app.name)


def restore_icon(app):
    """Restore the app's original icon."""
    if not app.custom_icon:
        return False, tr("“{name}” already has its own icon.").format(name=app.name)
    g = "Desktop Entry"
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(app.desktop, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error as e:
        return False, e.message
    original = _kf_str(kf, "X-ZETA-Original")
    if original:
        # copy made by ZETA: remove it and the package's entry applies again
        try:
            os.unlink(app.desktop)
        except OSError as e:
            return False, tr("Couldn't restore it: {error}").format(error=e.strerror)
        info = Gio.DesktopAppInfo.new_from_filename(original) if os.path.exists(original) else None
        icon = ""
        if info is not None and info.get_icon() is not None:
            icon = info.get_icon().to_string()
    else:
        icon = _kf_str(kf, "X-ZETA-Original-Icon") or "application-x-executable"
        kf.set_string(g, "Icon", icon)
        for k in ("X-ZETA-Custom-Icon", "X-ZETA-Original-Icon"):
            try:
                kf.remove_key(g, k)
            except GLib.Error:
                pass
        _write_kf(kf, app.desktop)
    _invalidate()
    _icon_everywhere(app, icon)
    return True, tr("“{name}” has its own icon again.").format(name=app.name)


def _kf_str(kf, key):
    try:
        return kf.get_string("Desktop Entry", key)
    except GLib.Error:
        return ""


ORPHANS_FILE = os.path.join(HOME, ".cache", "zeta", "orphan-apps.json")
ORPHAN_WAIT = 20          # seconds: an app missing this long has really been removed
_PACKAGE_MANAGERS = {"apt", "apt-get", "aptitude", "dpkg", "synaptic", "flatpak", "unattended-upgr",
            "packagekitd", "zeta-packages"}


def _package_manager_running():
    """True if apt, dpkg, Synaptic or Flatpak are at work: at those moments
    an app can be missing for a few seconds (removed and put back)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % pid) as f:
                if f.read().strip() in _PACKAGE_MANAGERS:
                    return True
        except OSError:
            continue
    return False


def _confirmed_orphans(missing):
    """Among the missing apps, those already missing for ORPHAN_WAIT
    seconds (with no package manager at work). The others keep waiting."""
    import time
    try:
        with open(ORPHANS_FILE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    now = time.time()
    state = {k: v for k, v in state.items() if k in missing}
    for k in missing:
        state.setdefault(k, now)
    busy = _package_manager_running()
    confirmed = set() if busy else {k for k, v in state.items() if now - v >= ORPHAN_WAIT}
    for k in confirmed:
        state.pop(k, None)
    os.makedirs(os.path.dirname(ORPHANS_FILE), exist_ok=True)
    with open(ORPHANS_FILE, "w") as f:
        json.dump(state, f)
    return confirmed


def orphans_pending():
    """True if some missing app is awaiting confirmation (the menu re-checks)."""
    try:
        with open(ORPHANS_FILE) as f:
            return bool(json.load(f))
    except (OSError, ValueError):
        return False


def maintenance():
    """After every change to the apps (installed, upgraded, removed even from
    Synaptic or the terminal), without daemons: the app menu calls it.

      - copies with a custom icon follow the upgraded package entry (same new
        command, chosen icon kept) and disappear if the app has been
        uninstalled;
      - shortcuts made by ZETA (Dock, Desktop) for apps that no longer exist
        are removed; files placed by hand by the user are not touched;
      - the Dock is regenerated if an icon has changed.
    Returns the names of the apps that disappeared."""
    g = "Desktop Entry"
    try:
        names = os.listdir(USER_APPS)
    except OSError:
        names = []
    for n in names:
        p = os.path.join(USER_APPS, n)
        if not n.endswith(".desktop"):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            continue
        original = _kf_str(kf, "X-ZETA-Original")
        if not original:
            continue
        if not os.path.exists(original):
            if not _package_manager_running():
                try:
                    os.unlink(p)          # app uninstalled: remove the copy too
                except OSError:
                    pass
            continue
        fingerprint = _fingerprint(original)
        if fingerprint and fingerprint != _kf_str(kf, "X-ZETA-Original-Signature"):
            # the package entry has changed (upgrade): the copy follows it,
            # keeping only the chosen icon
            new = GLib.KeyFile()
            try:
                new.load_from_file(original, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
                new.set_string(g, "Icon", _kf_str(kf, "Icon"))
                new.set_string(g, "X-ZETA-Original", original)
                new.set_string(g, "X-ZETA-Original-Signature", fingerprint)
                new.set_string(g, "X-ZETA-Custom-Icon", "true")
                _write_kf(new, p)
            except (GLib.Error, OSError):
                pass
    _invalidate()
    ids = {a.id for a in all_apps(reread=True)}
    vanished = []
    # ZETA shortcuts (Desktop, Dock) pointing to apps that are not installed
    d = desktop_folder()
    desktop_items = {}
    try:
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if not n.endswith(".desktop") or os.path.islink(p):
                continue
            kf = GLib.KeyFile()
            try:
                kf.load_from_file(p, GLib.KeyFileFlags.NONE)
            except GLib.Error:
                continue
            aid = _kf_str(kf, "X-ZETA-App")
            if aid and aid not in ids:
                try:
                    name = kf.get_locale_string("Desktop Entry", "Name", None)   # the user's language
                except GLib.Error:
                    name = ""
                desktop_items[p] = (aid, name or aid)
    except OSError:
        pass
    try:
        from system import dock
        entries = dock.load_dock()
    except Exception:  # noqa: BLE001 — without a Dock, clean up the rest
        dock, entries = None, []
    in_dock = {e["app"] for e in entries if e.get("app") and e["app"] not in ids}
    confirmed = _confirmed_orphans({a for a, _n in desktop_items.values()} | in_dock)
    for p, (aid, name) in desktop_items.items():
        if aid in confirmed:
            try:
                Gio.File.new_for_path(p).trash(None)
                vanished.append(name)
            except GLib.Error:
                pass
    if dock is not None:
        try:
            kept = [e for e in entries if not (e.get("app") in confirmed)]
            if len(kept) != len(entries) and kept:
                vanished += [e.get("name", e["app"]) for e in entries if e.get("app") in confirmed]
                dock.save_dock(kept)
            dock.apply_if_changed()
        except Exception:  # noqa: BLE001 — the Dock must not stop the maintenance
            pass
    return vanished


# ------------------------------------------------------------- Dock
def in_dock(app):
    from system import dock
    for e in dock.load_dock():
        if e.get("app") == app.id:
            return True
        if not e.get("app") and app.executable and app.source != "flatpak":
            a = from_command(e.get("cmd", ""))
            if a is not None and a.id == app.id:
                return True
    return False


def add_to_dock(app):
    from system import dock
    if in_dock(app):
        return False, tr("“{name}” is already in the Dock.").format(name=app.name)
    entries = dock.load_dock()
    entries.append(dock.entry_from_app(app))
    dock.save_dock(entries)
    dock.apply(entries)
    return True, tr("“{name}” added to the Dock.").format(name=app.name)


def remove_from_dock(app):
    from system import dock
    entries = dock.load_dock()
    rest = []
    for e in entries:
        if e.get("app") == app.id:
            continue
        if not e.get("app"):
            a = from_command(e.get("cmd", ""))
            if a is not None and a.id == app.id:
                continue
        rest.append(e)
    if len(rest) == len(entries):
        return False, tr("“{name}” isn't in the Dock.").format(name=app.name)
    if not rest:
        return False, tr("The Dock must have at least one app.")
    dock.save_dock(rest)
    dock.apply(rest)
    return True, tr("“{name}” removed from the Dock.").format(name=app.name)


# ------------------------------------------------------------- uninstall
# apt in English: its output is parsed (Inst/Remv); LANGUAGE overrides LC_ALL
_ENV_APT = dict({k: v for k, v in os.environ.items() if k != "LANGUAGE"},
                DEBIAN_FRONTEND="noninteractive", LANG="C.UTF-8", LC_ALL="C.UTF-8")


def system_package(pkg):
    """True for packages that are never removed from here: those of the
    ZETA RAYS system and those Debian marks as essential or important."""
    base = pkg.split(":")[0]
    if base in SYSTEM_PACKAGES or base.startswith(("linux-image", "grub", "shim", "zeta")):
        return True
    out = _output(["dpkg-query", "-W", "-f", "${Essential} ${Priority}", base])
    return out.startswith("yes") or " required" in out or " important" in out


def simulate_apt(argv):
    """apt-get -s (no privileges needed): (code, removed, installed, message)."""
    try:
        p = subprocess.run(["apt-get", "-s"] + argv, env=_ENV_APT, capture_output=True,
                           text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, [], [], str(e)
    via = re.findall(r"^Remv (\S+)", p.stdout, re.M)
    su = re.findall(r"^Inst (\S+)", p.stdout, re.M)
    return p.returncode, via, su, (p.stderr or p.stdout).strip()[-600:]


def uninstallable(app):
    """(yes/no, why: a full sentence to show) — what to offer in the menu."""
    if app.protected:
        return False, tr("“{name}” is part of the system.").format(name=app.name)
    if app.source in ("opt", "local"):
        return False, tr("“{name}” was installed manually: remove it by deleting its "
                         "folder.").format(name=app.name)
    return True, ""


def remove_appimage_integration(app, ignore=True):
    """Remove an AppImage's entry and icon. ignore=True: the file stays and
    must not be put back in the menu on the next scan."""
    # the app's stable key is read before its entry is removed: it is
    # ignored by app, not by path, so moving the file does not bring it back
    key = ""
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
        key = _kf_str(kf, "X-ZETA-AppImage-Key")
    except GLib.Error:
        pass
    _remove_appimage_files(app.desktop, os.path.basename(app.desktop)[:-len(".desktop")])
    if ignore:
        _ignore_appimage("app:" + key if key else app.appimage)
    _clean_shortcuts(app)


def _clean_shortcuts(app):
    """After an uninstall: no dead shortcuts on the Desktop, in the Dock or
    among the hidden apps."""
    p = on_desktop(app)
    if p:
        try:
            os.unlink(p)
        except OSError:
            pass
    try:
        remove_from_dock(app)
    except Exception:          # noqa: BLE001 — the Dock must not stop the cleanup
        pass
    s = _read_hidden()
    if app.id in s:
        s.discard(app.id)
        _write_hidden(s)
    _invalidate()


def after_uninstall(app):
    _clean_shortcuts(app)


# ------------------------------------------------------------- AppImage
IGNORED_APPIMAGES_FILE = os.path.join(CFG, "ignored-appimages.json")


def _ignore_appimage(path):
    try:
        with open(IGNORED_APPIMAGES_FILE) as f:
            s = set(json.load(f))
    except (OSError, ValueError):
        s = set()
    s.add(path)
    os.makedirs(CFG, exist_ok=True)
    with open(IGNORED_APPIMAGES_FILE, "w") as f:
        json.dump(sorted(s), f, indent=1)


def _ignored_appimages():
    try:
        with open(IGNORED_APPIMAGES_FILE) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def is_appimage(path):
    """True for an AppImage (ELF with the "AI" type 1 or 2 magic)."""
    try:
        with open(path, "rb") as f:
            head = f.read(11)
    except OSError:
        return False
    return head[:4] == b"\x7fELF" and head[8:10] == b"AI" and head[10] in (1, 2)


def _elf_end(path):
    """Where the ELF part ends: the AppImage file system starts there."""
    with open(path, "rb") as f:
        h = f.read(64)
    if h[4] == 2:           # 64 bit
        e_shoff, = struct.unpack("<Q", h[40:48])
        e_shentsize, e_shnum = struct.unpack("<HH", h[58:62])
    else:
        e_shoff, = struct.unpack("<I", h[32:36])
        e_shentsize, e_shnum = struct.unpack("<HH", h[46:50])
    return e_shoff + e_shentsize * e_shnum


def _read_appimage(path, folder):
    """Extract the desktop entry and the icon from the AppImage's own file
    system without running it (unsquashfs).
    Returns (KeyFile, icon path, desktop file name) or (None, None, None)."""
    try:
        off = _elf_end(path)
    except (OSError, struct.error):
        return None, None, None
    unsq = shutil.which("unsquashfs")
    if not unsq:
        return None, None, None
    try:
        r = subprocess.run([unsq, "-o", str(off), "-l", "-d", "", path],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None, None, None
    # the listing comes as "/name" (or "squashfs-root/name" with old unsquashfs)
    names = []
    for x in r.stdout.splitlines():
        x = x.strip()
        if x.startswith("squashfs-root"):
            x = x[len("squashfs-root"):]
        names.append(x.lstrip("/"))
    root = [n for n in names if n and "/" not in n]
    desktop = next((n for n in root if n.endswith(".desktop")), None)
    if not desktop:
        return None, None, None

    def extract(names):
        try:
            subprocess.run([unsq, "-o", str(off), "-f", "-d", folder, path] + names,
                           capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass

    def real_path(name):
        """Root entries are often symlinks to files deeper inside
        (usr/share/applications/..., .DirIcon -> icon): the target is
        extracted too, without ever leaving the AppImage."""
        p = os.path.join(folder, name)
        for _ in range(4):
            if not os.path.islink(p):
                break
            dest = os.path.normpath(os.path.join(os.path.dirname(name), os.readlink(p))).lstrip("/")
            if dest.startswith(".."):
                return None
            extract([dest])
            name, p = dest, os.path.join(folder, dest)
        return p if os.path.isfile(p) and not os.path.islink(p) else None

    extract([desktop, ".DirIcon"] + [n for n in root if n.endswith((".png", ".svg"))])
    desktop_file = real_path(desktop)
    if not desktop_file:
        return None, None, None
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(desktop_file, GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error:
        return None, None, None
    icon = None
    try:
        icon_name = kf.get_string("Desktop Entry", "Icon")
    except GLib.Error:
        icon_name = ""
    for cand in ([icon_name + ".svg", icon_name + ".png"] if icon_name else []) + [".DirIcon"]:
        if cand not in root:
            continue
        p = real_path(cand)
        if p and os.path.getsize(p) > 0:
            icon = p
            break
    return kf, icon, desktop


def quote_exec(path):
    """A path inside Exec= as the .desktop standard wants it: in double
    quotes (not single quotes: other programs do not understand them) with
    \\, ", ` and $ escaped."""
    path = path.replace("%", "%%")          # "%" is a field code
    if re.fullmatch(r"[A-Za-z0-9_./+:@-]+", path):
        return path
    return '"%s"' % re.sub(r'([\\"`$])', r"\\\1", path)


def exec_program(path):
    """The program at the start of Exec=. With a "%" in the name (an AppImage
    downloaded as "App%20Name") GIO discards the entry: it checks that the
    program exists without first turning "%%" into "%". With "env" in front
    the check finds /usr/bin/env, and at launch time the path is correct."""
    return ("env " if "%" in path else "") + quote_exec(path)


# ------------------------------------------------------------- programs outside the menu
# A downloaded and unpacked program (Blender from blender.org in /opt or in
# Downloads) ships a .desktop next to itself with "Exec=blender" and
# "Icon=blender": names that only work inside that folder. Copied elsewhere
# (dragged to the Desktop, pasted, copied from the file manager) it could no
# longer find the program and the Desktop showed it as "Blender (missing)".
# Every entry that leaves its folder is therefore rewritten with full paths,
# and remembers where it came from (X-ZETA-Origin).

OPT_PREFIX = "zeta-opt-"

# Blender downloaded from blender.org (5.x) opens on Wayland and sizes its
# interface only by Hyprland's screen scale (1 on almost every screen): on a
# screen above 96 DPI it came out small. The packaged Blender (Synaptic) goes
# through X11, where Blender sizes its interface by the screen's real DPI,
# and looks the right size. Its entries (menu, Desktop, Dock) therefore
# launch it the same way, without touching the scale of the rest of the
# system.
NO_WAYLAND = ("blender",)
_X11_PREFIX = "env -u WAYLAND_DISPLAY "


def _adapted_command(command, prog):
    """Exec with the fixes for programs that render badly on Wayland (only
    manually downloaded ones: system packages are left as they are)."""
    if os.path.basename(prog) in NO_WAYLAND and not prog.startswith("/usr/") \
            and "WAYLAND_DISPLAY" not in command:
        return _X11_PREFIX + command
    return command
_TOKEN = r"(?:(?<=\s)|^)%s(?=\s|$)"


def _replace_program(command, old, new):
    """Replace the program inside Exec= (whole word only, first occurrence)."""
    return re.sub(_TOKEN % re.escape(old), lambda _m: new, command, count=1)



def resolved_entry(source):
    """KeyFile of a .desktop with program, icon and folder made absolute
    relative to the real file's folder (following symlinks). None if it is
    not an application or the program cannot be found."""
    g = "Desktop Entry"
    real_path = os.path.realpath(source)
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(real_path, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    except GLib.Error:
        return None
    if (_kf_str(kf, "Type") or "Application") != "Application":
        return None
    command = _kf_str(kf, "Exec")
    argv = _argv(command)
    folder = os.path.dirname(real_path)
    origin = _kf_str(kf, "X-ZETA-Origin")
    i = _program_index(argv)
    if i >= len(argv):
        return None
    token = argv[i]
    prog = ""
    # the program next to the .desktop comes before the one in PATH: with
    # Blender also installed from Synaptic, "Exec=blender" of 5.2 in /opt
    # launched /usr/bin/blender, i.e. the other Blender
    for base in [folder] + ([os.path.dirname(origin)] if origin else []):
        nearby = os.path.join(base, token)
        if not os.path.isabs(token) and os.path.isfile(nearby) and os.access(nearby, os.X_OK):
            prog, folder = nearby, base
            break
    if not prog:
        prog = _program_path(argv, folder)
    if not prog:
        return None
    if not os.path.isabs(token) and prog != GLib.find_program_in_path(token):
        kf.set_string(g, "Exec", _replace_program(command, token, exec_program(prog)))
        if not _kf_str(kf, "Path"):
            kf.set_string(g, "Path", os.path.dirname(prog))
    kf.set_string(g, "Exec", _adapted_command(_kf_str(kf, "Exec"), prog))
    test = _kf_str(kf, "TryExec")
    if test and not os.path.isabs(test) and not GLib.find_program_in_path(test):
        nearby = os.path.join(folder, test)
        kf.set_string(g, "TryExec", nearby if os.access(nearby, os.X_OK) else prog)
    icon = _kf_str(kf, "Icon")
    if icon and not os.path.isabs(icon) and icon_file(icon) == GENERIC_ICON:
        for base in (folder, os.path.dirname(prog)):
            found = next((os.path.join(base, icon + e) for e in (".svg", ".png", ".xpm")
                            if os.path.isfile(os.path.join(base, icon + e))), "")
            if found:
                kf.set_string(g, "Icon", found)
                break
    if not origin:
        kf.set_string(g, "X-ZETA-Origin", real_path)
    return kf


def _write_shortcut(kf, dest):
    """Write the shortcut (executable and "trusted", like the menu ones)."""
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(kf.to_data()[0])
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    try:
        Gio.File.new_for_path(dest).set_attribute_string(
            "metadata::trusted", "true", Gio.FileQueryInfoFlags.NONE, None)
    except GLib.Error:
        pass


def _unique_name(folder, name):
    dest = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    base = re.sub(r" \(\d+\)$", "", base)          # «blender (3)», not «blender (2) (2)»
    n = 2
    while os.path.lexists(dest):
        dest = os.path.join(folder, "%s (%d)%s" % (base, n, ext))
        n += 1
    return dest


def external_shortcut(source, folder=None, unique=True):
    """Shortcut on the Desktop (or in folder) for a .desktop that is not
    among the applications: a copy with full paths, which works wherever it
    is moved or copied. With unique=True, if one already exists for the same
    program, that one is returned. (path, "") or ("", error)."""
    kf = resolved_entry(source)
    name = os.path.basename(source)
    if kf is None:
        return "", tr("“{name}” doesn't start a program that can be found.").format(name=name)
    folder = folder or desktop_folder()
    os.makedirs(folder, exist_ok=True)
    origin = _kf_str(kf, "X-ZETA-Origin")
    if unique:
        for n in os.listdir(folder):
            p = os.path.join(folder, n)
            if not n.endswith(".desktop"):
                continue
            if os.path.realpath(p) == origin:
                return p, ""
            other = GLib.KeyFile()
            try:
                other.load_from_file(p, GLib.KeyFileFlags.NONE)
            except GLib.Error:
                continue
            if _kf_str(other, "X-ZETA-Origin") == origin:
                return p, ""
    dest = _unique_name(folder, name if name.endswith(".desktop") else name + ".desktop")
    try:
        _write_shortcut(kf, dest)
    except OSError as e:
        return "", tr("Couldn't create the shortcut: {error}").format(error=e.strerror)
    return dest, ""


def adjacent_entry(path):
    """The .desktop next to a program (blender -> blender.desktop) that
    launches it, or ""."""
    real_path = os.path.realpath(path)
    folder = os.path.dirname(real_path)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return ""
    for n in names:
        if not n.endswith(".desktop"):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(os.path.join(folder, n), GLib.KeyFileFlags.NONE)
        except GLib.Error:
            continue
        prog = _program_path(_argv(_kf_str(kf, "Exec")), folder)
        if prog and os.path.realpath(prog) == real_path:
            return os.path.join(folder, n)
    return ""


def program_shortcut(path, folder=None):
    """A program (ELF binary) dragged onto the Desktop: the shortcut of its
    .desktop entry if it has one next to it, otherwise a new one with its
    name. Never a copy of the program: Blender needs its libraries next to
    it and a copy would not start."""
    entry = adjacent_entry(path)
    if entry:
        return external_shortcut(entry, folder)
    real_path = os.path.realpath(path)
    g = "Desktop Entry"
    kf = GLib.KeyFile()
    name = os.path.basename(real_path)
    kf.set_string(g, "Type", "Application")
    kf.set_string(g, "Name", name[:1].upper() + name[1:])
    kf.set_string(g, "Exec", _adapted_command(exec_program(real_path), real_path))
    kf.set_string(g, "Path", os.path.dirname(real_path))
    kf.set_string(g, "Terminal", "false")
    icon = next((os.path.join(os.path.dirname(real_path), name + e) for e in (".svg", ".png", ".xpm")
                  if os.path.isfile(os.path.join(os.path.dirname(real_path), name + e))), "")
    kf.set_string(g, "Icon", icon or "application-x-executable")
    kf.set_string(g, "X-ZETA-Origin", real_path)
    folder = folder or desktop_folder()
    for n in os.listdir(folder) if os.path.isdir(folder) else []:
        p = os.path.join(folder, n)
        if n.endswith(".desktop"):
            other = GLib.KeyFile()
            try:
                other.load_from_file(p, GLib.KeyFileFlags.NONE)
            except GLib.Error:
                continue
            if _kf_str(other, "X-ZETA-Origin") == real_path:
                return p, ""
    dest = _unique_name(folder, re.sub(r"[^\w.+-]+", "-", name) + ".desktop")
    try:
        _write_shortcut(kf, dest)
    except OSError as e:
        return "", tr("Couldn't create the shortcut: {error}").format(error=e.strerror)
    return dest, ""


def _origin_candidates(prog):
    """The .desktop entries next to a program with this name, in the
    folders of manually unpacked programs (up to two levels deep)."""
    base_dirs = ["/opt", os.path.join(HOME, "Applications"), os.path.join(HOME, ".local", "opt")]
    for which in (GLib.UserDirectory.DIRECTORY_DOWNLOAD,):
        d = GLib.get_user_special_dir(which)
        if d:
            base_dirs.append(d)
    base_dirs += [os.path.join(HOME, n) for n in ("Downloads", "Scaricati")]  # i18n-data
    seen = set()
    for b in base_dirs:
        b = os.path.normpath(b)
        if b in seen or not os.path.isdir(b):
            continue
        seen.add(b)
        for root, dirs, files in os.walk(b):
            level = root[len(b):].count(os.sep)
            if level >= 2:
                dirs[:] = []
            if not os.path.isfile(os.path.join(root, prog)):
                continue
            for f in sorted(files):
                if f.endswith(".desktop"):
                    yield os.path.join(root, f)


def repair_shortcut(path):
    """A Desktop shortcut that can no longer find its program (copied from
    the file manager before this fix, or with a relative Exec): look for its
    original entry among the manually unpacked programs and rewrite it with
    full paths. True if it works now."""
    if os.path.islink(path) or not path.endswith(".desktop"):
        return False
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(path, GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return False
    argv = _argv(_kf_str(kf, "Exec"))
    if not argv or _program_index(argv) >= len(argv) or _program_path(argv, os.path.dirname(path)):
        return False
    name = _kf_str(kf, "Name")
    prog = argv[_program_index(argv)]
    if os.sep in prog:
        return False                     # explicit path that is gone: the program was removed
    found = []
    for cand in _origin_candidates(prog):
        other = GLib.KeyFile()
        try:
            other.load_from_file(cand, GLib.KeyFileFlags.NONE)
        except GLib.Error:
            continue
        if _kf_str(other, "Name") == name and _kf_str(other, "Exec") == _kf_str(kf, "Exec") \
                and os.path.realpath(cand) not in found:
            found.append(os.path.realpath(cand))
    origin = _kf_str(kf, "X-ZETA-Origin")
    if origin and os.path.isfile(origin):
        found = [origin]
    if len(found) > 1:
        # the same program in Downloads (the unpacked archive) and in /opt
        # (where it was put to be used): the one in /opt wins
        in_opt = [t for t in found if t.startswith("/opt/")]
        if len(in_opt) == 1:
            found = in_opt
    if len(found) != 1:
        return False                     # none or more than one: do not guess
    new = resolved_entry(found[0])
    if new is None:
        return False
    # what the user changed on the shortcut is kept (chosen icon)
    if _kf_str(kf, "X-ZETA-Custom-Icon"):
        new.set_string("Desktop Entry", "Icon", _kf_str(kf, "Icon"))
        new.set_string("Desktop Entry", "X-ZETA-Custom-Icon", "true")
    try:
        _write_shortcut(new, path)
    except OSError:
        return False
    return True


def opt_entries():
    """The .desktop entries of programs unpacked in /opt (up to two levels:
    /opt/blender-5.2.2/blender.desktop, /opt/blender/5.2/blender.desktop)."""
    found = []
    if not os.path.isdir("/opt"):
        return found
    for root, dirs, files in os.walk("/opt"):
        level = root[len("/opt"):].count(os.sep)
        if level >= 2:
            dirs[:] = []
        if level == 0:
            continue                       # /opt itself: no loose entries
        for f in sorted(files):
            if f.endswith(".desktop"):
                found.append(os.path.join(root, f))
    return found


def _integrate_opt():
    """Put into the menu the programs in /opt that have a .desktop next to
    them and are not already in the menu with their own entry (Chrome,
    VS Code... install one). The generated entry has full paths and
    disappears with the program. Returns the names of the new apps."""
    g = "Desktop Entry"
    os.makedirs(USER_APPS, exist_ok=True)
    current_ones = {}
    for n in os.listdir(USER_APPS):
        if n.startswith(OPT_PREFIX) and n.endswith(".desktop"):
            current_ones[n] = os.path.join(USER_APPS, n)
    _invalidate()
    already, other_names = set(), set()
    for a in all_apps(reread=True):
        if a.id.startswith(OPT_PREFIX) or not a.executable:
            continue
        already.add(os.path.realpath(a.executable))
        other_names.add(a.name)
    entries, names = {}, {}
    for source in opt_entries():
        kf = resolved_entry(source)
        if kf is None or _kf_str(kf, "NoDisplay") == "true" or _kf_str(kf, "Hidden") == "true":
            continue
        prog = _program_path(_argv(_kf_str(kf, "Exec")))
        if not prog or os.path.realpath(prog) in already:
            continue
        rel = os.path.relpath(os.path.realpath(source), "/opt")
        key = re.sub(r"[^a-z0-9._-]+", "-", rel[:-len(".desktop")].lower().replace(os.sep, "-")).strip(".-")
        ident = OPT_PREFIX + key + ".desktop"
        kf.set_string(g, "TryExec", os.path.realpath(prog))
        kf.set_string(g, "X-ZETA-Opt", os.path.realpath(source))
        entries[ident] = kf
        names.setdefault(_kf_str(kf, "Name"), []).append(ident)
    # two versions of the same program (or the same name as a package, like
    # Blender from Synaptic): the name tells which one
    for name, ids in names.items():
        if len(ids) < 2 and name not in other_names:
            continue
        for ident in ids:
            kf = entries[ident]
            folder = os.path.basename(os.path.dirname(_kf_str(kf, "X-ZETA-Opt")))
            m = re.search(r"\d+(?:\.\d+)+", folder)
            kf.set_string(g, "Name", "%s %s" % (name, m.group(0) if m else folder))
    added = []
    for ident, kf in entries.items():
        dest = os.path.join(USER_APPS, ident)
        old = current_ones.pop(ident, None)
        text = kf.to_data()[0]
        if old:
            previous = GLib.KeyFile()
            try:
                previous.load_from_file(old, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
                if _kf_str(previous, "X-ZETA-Custom-Icon"):
                    kf.set_string(g, "Icon", _kf_str(previous, "Icon"))
                    kf.set_string(g, "X-ZETA-Custom-Icon", "true")
                    text = kf.to_data()[0]
                with open(old, encoding="utf-8") as f:
                    if f.read() == text:
                        continue
            except (GLib.Error, OSError):
                pass
        else:
            added.append(_kf_str(kf, "Name"))
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, dest)
    # programs removed from /opt: their entry goes too (Desktop and Dock are
    # cleaned up by maintenance(), as for uninstalled apps)
    for p in current_ones.values():
        try:
            os.unlink(p)
        except OSError:
            pass
    _invalidate()
    return added


FILE_META_APPIMAGE = os.path.join(HOME, ".cache", "zeta", "appimage-meta.json")
APPIMAGE_LOCK_FILE = os.path.join(HOME, ".cache", "zeta", "appimage.lock")
_OLD_ID = re.compile(r"^%s[0-9a-f]{12}\.desktop$" % re.escape(APPIMAGE_PREFIX))


def appimage_key(desktop_name, app_name=""):
    """Stable identity of an AppImage application: the name of the desktop
    entry it ships (blender.desktop -> "blender"). Never the path of the
    file: moving, renaming or updating the AppImage keeps the same app, the
    same menu entry and the same Desktop and Dock links."""
    base = desktop_name[:-len(".desktop")] if desktop_name.endswith(".desktop") else desktop_name
    base = re.sub(r"[^a-z0-9._-]+", "-", base.lower()).strip(".-")
    if not base:
        base = re.sub(r"[^a-z0-9]+", "-", app_name.lower()).strip("-") or "app"
    return base


def _id_appimage(key):
    return APPIMAGE_PREFIX + key


def found_appimages():
    found = []
    for d in APPIMAGE_FOLDERS:
        depth = 2 if d == "/opt" else 0
        for root, dirs, files in os.walk(d) if os.path.isdir(d) else []:
            level = root[len(d):].count(os.sep)
            if level >= depth:
                dirs[:] = []
            for f in files:
                if f.lower().endswith(".appimage"):
                    p = os.path.join(root, f)
                    if os.path.isfile(p) and is_appimage(p):
                        found.append(os.path.realpath(p))
    return sorted(set(found))


def _file_fingerprint(st):
    """Same file, even after a move or a rename on the same disk."""
    return "%d:%d:%d:%d" % (st.st_dev, st.st_ino, st.st_size, int(st.st_mtime))


def _appimage_signature(st):
    # "v4": the format of the generated entry; changing it regenerates them
    return "v4:%d:%d" % (st.st_size, int(st.st_mtime))


def _version_order(meta, mtime):
    """Newest first: by the version the AppImage declares, then by date."""
    numbers = tuple(int(x) for x in re.findall(r"\d+", meta.get("version") or "")[:6])
    return (numbers, mtime)


class _Lock:
    """One AppImage scan at a time (the path unit, the session start and the
    app menu can all ask for one at the same moment)."""

    def __enter__(self):
        os.makedirs(os.path.dirname(APPIMAGE_LOCK_FILE), exist_ok=True)
        self.f = open(APPIMAGE_LOCK_FILE, "w")
        import fcntl
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_a):
        self.f.close()


def _read_json(path, empty):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(empty)) else empty
    except (OSError, ValueError):
        return empty


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def integrate_appimages():
    """Create, update or remove the menu entries of the AppImages found in
    the usual folders, and of the programs unpacked in /opt with a desktop
    entry next to them. Returns the names of the apps that are new."""
    with _Lock():
        new_items = _integrate_appimages()
        try:
            new_items += _integrate_opt()
        except OSError:
            pass                  # /opt unreadable: the AppImages stay
        return new_items


def _integrate_appimages():
    g = "Desktop Entry"
    os.makedirs(USER_APPS, exist_ok=True)
    os.makedirs(APPIMAGE_ICONS_FOLDER, exist_ok=True)
    ignored = _ignored_appimages()

    # entries written by earlier scans: current ones (stable id) and old ones
    # named after a hash of the path (before 1.7), which are migrated
    current_ones, old_entries = {}, {}
    for n in os.listdir(USER_APPS):
        if not (n.startswith(APPIMAGE_PREFIX) and n.endswith(".desktop")):
            continue
        p = os.path.join(USER_APPS, n)
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            try:
                os.unlink(p)
            except OSError:
                pass
            continue
        if _OLD_ID.match(n) and not _kf_str(kf, "X-ZETA-AppImage-Key"):
            old_entries[n] = (p, kf)
        else:
            current_ones[n[:-len(".desktop")]] = (p, kf)

    meta_cache = _read_json(FILE_META_APPIMAGE, {})
    new_cache = {}
    already_read = {}                     # path -> (KeyFile, icon) read in this scan
    by_key = {}                # key -> [(order, path, stat, meta)]
    tmp_root = tempfile.mkdtemp(prefix="zeta-appimage-")
    try:
        for p in found_appimages():
            if p in ignored:
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue                      # gone while we were looking
            imp = _file_fingerprint(st)
            meta = meta_cache.get(imp)
            if not meta or "key" not in meta:
                folder = tempfile.mkdtemp(dir=tmp_root)
                kf, icon, desktop = _read_appimage(p, folder)
                if kf is None:
                    continue                  # no desktop entry inside: not an app
                name = _kf_str(kf, "Name") or os.path.splitext(os.path.basename(p))[0]
                meta = {"key": appimage_key(desktop, name), "name": name,
                        "version": _kf_str(kf, "X-AppImage-Version")}
                already_read[p] = (kf, icon)
            new_cache[imp] = meta
            if "app:" + meta["key"] in ignored:
                continue
            by_key.setdefault(meta["key"], []).append(
                (_version_order(meta, st.st_mtime), p, st, meta))
        _write_json(FILE_META_APPIMAGE, new_cache)

        added, renames, kept = [], {}, set()
        for key, versions in by_key.items():
            versions.sort(key=lambda v: v[0], reverse=True)
            _sort_order, p, st, meta = versions[0]
            ident = _id_appimage(key)
            kept.add(ident)
            dest = os.path.join(USER_APPS, ident + ".desktop")
            signature = _appimage_signature(st)
            existing = current_ones.get(ident)
            # old entries of any version of this app point here now
            paths = {v[1] for v in versions}
            for n, (_vp, vkf) in old_entries.items():
                if _kf_str(vkf, "X-ZETA-AppImage") in paths:
                    renames[n] = ident + ".desktop"
            custom = ""
            for _x, kfv in ([existing] if existing else []) + \
                    [old_entries[n] for n in renames if renames[n] == ident + ".desktop"]:
                if _kf_str(kfv, "X-ZETA-Custom-Icon"):
                    custom = _kf_str(kfv, "Icon")
                    break
            if existing:
                ekf = existing[1]
                if _kf_str(ekf, "X-ZETA-AppImage-Signature") == signature:
                    if _kf_str(ekf, "X-ZETA-AppImage") != p:
                        # same file, moved or renamed: only the path changes
                        ekf.set_string(g, "Exec", exec_program(p) + " %U")
                        ekf.set_string(g, "TryExec", p)
                        ekf.set_string(g, "Path", os.path.dirname(p))
                        ekf.set_string(g, "X-ZETA-AppImage", p)
                        _write_kf(ekf, dest)
                    _make_executable(p)
                    continue
            if p not in already_read:
                folder = tempfile.mkdtemp(dir=tmp_root)
                kf, icon, _desktop = _read_appimage(p, folder)
                if kf is None:
                    continue
                already_read[p] = (kf, icon)
            kf, icon = already_read[p]
            out = _appimage_entry(kf, icon, p, ident, key, signature, custom)
            _write_kf(out, dest)
            _make_executable(p)
            if not existing and ident + ".desktop" not in renames.values():
                added.append(out.get_string(g, "Name"))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    # apps whose AppImage is gone: entry and icon go; Desktop and Dock links
    # are removed later by maintenance(), only if still missing (two phases)
    for ident, (p, _kf) in current_ones.items():
        if ident not in kept:
            _remove_appimage_files(p, ident)
    for n, (p, _kf) in old_entries.items():
        _remove_appimage_files(p, n[:-len(".desktop")])
    if renames:
        _rename_shortcuts(renames)
    _invalidate()
    _align_appimage_shortcuts()
    return added


def _make_executable(p):
    """A downloaded file is not executable: it becomes so here, so the menu
    can start it (only the user's own files, never system ones)."""
    try:
        st = os.stat(p)
        if not os.access(p, os.X_OK) and st.st_uid == os.getuid():
            os.chmod(p, st.st_mode | 0o100)
    except OSError:
        pass


def _appimage_entry(kf, icon, p, ident, key, signature, custom):
    g = "Desktop Entry"
    out = GLib.KeyFile()
    out.set_string(g, "Type", "Application")
    for k in ("Name", "GenericName", "Comment", "Categories", "Keywords",
              "StartupWMClass", "MimeType", "Terminal", "X-AppImage-Version"):
        if _ha(kf, g, k):
            out.set_string(g, k, kf.get_string(g, k))
    # translated names and descriptions shipped by the app
    for k in ("Name", "GenericName", "Comment"):
        try:
            keys = kf.get_keys(g)[0]
        except GLib.Error:
            keys = []
        for c in keys:
            if c.startswith(k + "[") and c.endswith("]"):
                out.set_string(g, c, kf.get_string(g, c))
    if not _ha(out, g, "Name"):
        out.set_string(g, "Name", os.path.splitext(os.path.basename(p))[0])
    if not _ha(out, g, "Categories"):
        out.set_string(g, "Categories", "Utility;")
    if not _ha(out, g, "Comment"):
        out.set_string(g, "Comment", "AppImage")
    dest_icon = ""
    if icon:
        with open(icon, "rb") as fi:
            svg = icon.endswith(".svg") or fi.read(5).startswith(b"<")
        ext = ".svg" if svg else ".png"
        dest_icon = os.path.join(APPIMAGE_ICONS_FOLDER, ident + ext)
        other_icon = os.path.join(APPIMAGE_ICONS_FOLDER, ident + (".png" if svg else ".svg"))
        shutil.copyfile(icon, dest_icon + ".tmp")
        os.replace(dest_icon + ".tmp", dest_icon)
        if os.path.exists(other_icon):
            os.unlink(other_icon)
    out.set_string(g, "Icon", dest_icon or "application-x-executable")
    if custom:
        out.set_string(g, "X-ZETA-Original-Icon", out.get_string(g, "Icon"))
        out.set_string(g, "Icon", custom)
        out.set_string(g, "X-ZETA-Custom-Icon", "true")
    out.set_string(g, "Exec", exec_program(p) + " %U")
    out.set_string(g, "TryExec", p)
    out.set_string(g, "Path", os.path.dirname(p))
    out.set_string(g, "X-ZETA-AppImage", p)
    out.set_string(g, "X-ZETA-AppImage-Key", key)
    out.set_string(g, "X-ZETA-AppImage-Signature", signature)
    return out


def _remove_appimage_files(p, ident):
    for f in (p, os.path.join(APPIMAGE_ICONS_FOLDER, ident + ".png"),
              os.path.join(APPIMAGE_ICONS_FOLDER, ident + ".svg")):
        try:
            os.unlink(f)
        except OSError:
            pass


def _rename_shortcuts(renames):
    """Old app id -> new app id in the Desktop links, the Dock and the list
    of apps removed from the menu (migration of the pre-1.7 ids)."""
    g = "Desktop Entry"
    d = desktop_folder()
    try:
        names = os.listdir(d)
    except OSError:
        names = []
    for n in names:
        p = os.path.join(d, n)
        if not n.endswith(".desktop") or os.path.islink(p):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            continue
        new = renames.get(_kf_str(kf, "X-ZETA-App"))
        if new:
            kf.set_string(g, "X-ZETA-App", new)
            _write_kf(kf, p)
    try:
        from system import dock
        entries = dock.load_dock()
        changed = False
        for e in entries:
            if e.get("app") in renames:
                e["app"] = renames[e["app"]]
                e["cmd"] = "zeta-app launch %s" % shlex.quote(e["app"])
                changed = True
        if changed:
            dock.save_dock(entries)
    except Exception:  # noqa: BLE001 - the Dock must not stop the migration
        pass
    s = _read_hidden()
    if s & set(renames):
        _write_hidden({renames.get(x, x) for x in s})


def appimage_on_desktop(app):
    """The AppImage file of this app, when the file itself is on the Desktop."""
    if not app.appimage:
        return ""
    d = os.path.realpath(desktop_folder())
    return app.appimage if os.path.dirname(os.path.realpath(app.appimage)) == d else ""


def _align_appimage_shortcuts():
    """Desktop links of AppImage apps follow the app: same command and icon
    after the file moved or the app was updated. A link is redundant when the
    AppImage file itself sits on the Desktop (two icons for one app): the
    link made by ZETA goes to the Trash, the user's file stays."""
    g = "Desktop Entry"
    app_per_id = {a.id: a for a in all_apps() if a.source == "appimage"}
    d = desktop_folder()
    try:
        names = os.listdir(d)
    except OSError:
        return
    for n in names:
        p = os.path.join(d, n)
        if not n.endswith(".desktop") or os.path.islink(p):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            continue
        app = app_per_id.get(_kf_str(kf, "X-ZETA-App"))
        if not app:
            continue
        if appimage_on_desktop(app):
            try:
                Gio.File.new_for_path(p).trash(None)
            except GLib.Error:
                pass
            continue
        source = GLib.KeyFile()
        try:
            source.load_from_file(app.desktop, GLib.KeyFileFlags.NONE)
        except GLib.Error:
            continue
        changed = False
        for k in ("Exec", "TryExec", "Path", "Icon"):
            v = _kf_str(source, k)
            if v and _kf_str(kf, k) != v:
                kf.set_string(g, k, v)
                changed = True
        if changed:
            _write_kf(kf, p)
