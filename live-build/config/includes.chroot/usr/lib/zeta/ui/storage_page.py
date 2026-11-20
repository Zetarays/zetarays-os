# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings > Storage.

How the disk is used (system and apps, personal files, Trash, caches,
Flatpak apps, AI models, downloaded packages) and the quick ways to free
space. The sizes are measured with "du" in a thread when the page is first
shown, with a progress bar: opening Settings never waits for it.

Freeing space:
- Empty Trash and the thumbnail cache are the user's own files;
- the package cache (apt-get clean) goes through /usr/libexec/zeta-storage
  with pkexec, a single fixed operation;
- unused Flatpak runtimes are removed by flatpak itself, which asks
  PolicyKit when the system installation needs it.
"Analyze in detail" opens Disk Usage Analyzer (baobab), "Disks" opens
GNOME Disks (format USB drives, write disk images, check a disk's health).
"""
import os
import shutil
import subprocess

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from ui.page_tools import bg, confirm, pkexec_helper, size_text, spawn, toast  # noqa: E402

HOME = os.path.expanduser("~")
TRASH = os.path.join(GLib.get_user_data_dir(), "Trash")
CACHE = GLib.get_user_cache_dir()
THUMBNAILS = os.path.join(CACHE, "thumbnails")
USER_FLATPAK = os.path.join(GLib.get_user_data_dir(), "flatpak")
SYSTEM_FLATPAK = "/var/lib/flatpak"
MODELS = "/usr/share/ollama/.ollama/models"
APT_ARCHIVES = "/var/cache/apt/archives"
HELPER = "/usr/libexec/zeta-storage"

# category -> color of its part of the bar (fixed: they must differ from
# each other on both themes)
COLORS = {"system": "#3A8DFF", "personal": "#4CC94A", "ai": "#A970FF", "flatpak": "#FF9F0A",
          "trash": "#FF453A", "cache": "#FFD60A", "packages": "#64D2FF", "free": None}


def du(path):
    """Bytes used by a folder (0 when missing or unreadable)."""
    if not os.path.exists(path):
        return 0
    try:
        r = subprocess.run(["du", "-sx", "-B1", path], capture_output=True, text=True, timeout=600,
                           env=dict(os.environ, LC_ALL="C.UTF-8"))
        return int(r.stdout.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0


def same_disk(a, b):
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def measure(progress):
    """The usage breakdown; progress(fraction, text) is called from this thread."""
    root = shutil.disk_usage("/")
    data = {"total": root.total, "used": root.used, "free": root.free, "home_disk": None}
    steps = [("personal", HOME, tr("Personal files")),
             ("trash", TRASH, tr("Trash")),
             ("cache", CACHE, tr("Caches")),
             ("thumbnails", THUMBNAILS, tr("Caches")),
             ("flatpak_user", USER_FLATPAK, "Flatpak"),
             ("flatpak", SYSTEM_FLATPAK, "Flatpak"),
             ("ai", MODELS, tr("AI models")),
             ("packages", APT_ARCHIVES, tr("Downloaded packages"))]
    sizes = {}
    for i, (key, path, label) in enumerate(steps):
        progress(i / len(steps), label)
        sizes[key] = du(path)
    progress(1.0, "")
    # the personal folder already contains Trash, caches and the user's Flatpak apps
    sizes["personal"] = max(0, sizes["personal"] - sizes["trash"] - sizes["cache"]
                            - sizes["flatpak_user"])
    sizes["flatpak"] += sizes["flatpak_user"]
    home_here = same_disk(HOME, "/")
    on_root = sizes["flatpak"] + sizes["ai"] + sizes["packages"]
    if home_here:
        on_root += sizes["personal"] + sizes["trash"] + sizes["cache"]
    else:
        home = shutil.disk_usage(HOME)
        data["home_disk"] = {"total": home.total, "used": home.used, "free": home.free}
    sizes["system"] = max(0, root.used - on_root)
    data["sizes"] = sizes
    data["home_here"] = home_here
    return data


class UsageBar(Gtk.DrawingArea):
    """A horizontal bar split into the colored parts of the disk."""

    def __init__(self):
        super().__init__(content_height=22, hexpand=True, margin_top=6, margin_bottom=6)
        self.parts = []          # [(fraction, "#RRGGBB")]
        self.set_draw_func(self._draw)

    def set_parts(self, parts):
        self.parts = parts
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        radius = height / 2
        # the empty track (free space) in a neutral grey that works on both themes
        self._rounded(cr, 0, 0, width, height, radius)
        cr.set_source_rgba(0.55, 0.55, 0.58, 0.25)
        cr.fill_preserve()
        cr.clip()
        x = 0.0
        for fraction, color in self.parts:
            w = max(0.0, fraction) * width
            if w <= 0:
                continue
            r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
            cr.set_source_rgb(r, g, b)
            cr.rectangle(x, 0, w, height)
            cr.fill()
            x += w

    @staticmethod
    def _rounded(cr, x, y, w, h, r):
        import math
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()


def dot(color):
    area = Gtk.DrawingArea(content_width=12, content_height=12, valign=Gtk.Align.CENTER)

    def draw(_a, cr, w, h):
        import math
        if color:
            cr.set_source_rgb(*(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)))
        else:
            cr.set_source_rgba(0.55, 0.55, 0.58, 0.5)
        cr.arc(w / 2, h / 2, min(w, h) / 2, 0, 2 * math.pi)
        cr.fill()
    area.set_draw_func(draw)
    return area


class StoragePage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.loaded = False
        self.busy = False
        self.rows = {}

        self.g_disk = Adw.PreferencesGroup(title=tr("Disk"))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text=tr("Measure again"), css_classes=["flat"])
        refresh.connect("clicked", lambda *_: self.refresh())
        self.g_disk.set_header_suffix(refresh)
        if os.path.exists("/run/live/medium"):
            self.g_disk.set_description(tr("You are using ZETA RAYS from the installation media: "
                                           "the space shown is in memory (RAM) and is emptied at "
                                           "restart."))
        self.summary = Adw.ActionRow(title=tr("Measuring…"), use_markup=False)
        self.summary.add_css_class("property")
        self.g_disk.add(self.summary)
        self.bar = UsageBar()
        self.g_disk.add(self.bar)
        self.progress = Gtk.ProgressBar(show_text=True, margin_top=4, margin_bottom=4)
        self.g_disk.add(self.progress)
        self.add(self.g_disk)

        self.g_parts = Adw.PreferencesGroup(title=tr("What uses the space"))
        for key, title in (("system", tr("System and apps")), ("personal", tr("Personal files")),
                           ("ai", tr("AI models")), ("flatpak", tr("Flatpak apps")),
                           ("packages", tr("Downloaded packages")), ("cache", tr("Caches")),
                           ("trash", tr("Trash")), ("free", tr("Free"))):
            row = Adw.ActionRow(title=title)
            row.add_prefix(dot(COLORS[key]))
            label = Gtk.Label(label="…", css_classes=["dim-label"], valign=Gtk.Align.CENTER)
            row.add_suffix(label)
            row.size_label = label
            self.rows[key] = row
            self.g_parts.add(row)
        self.add(self.g_parts)

        g_free = Adw.PreferencesGroup(title=tr("Free up space"))
        self.b_trash = self._action(g_free, tr("Empty Trash"),
                                    tr("Deletes the files in the Trash for good"),
                                    tr("Empty"), self._empty_trash)
        self.b_thumbs = self._action(g_free, tr("Clear thumbnail cache"),
                                     tr("The previews of images and videos are made again when needed"),
                                     tr("Clear"), self._clear_thumbnails)
        self.b_packages = self._action(g_free, tr("Clean package cache"),
                                       tr("Package files already installed by updates"),
                                       tr("Clean"), self._clean_packages)
        self.b_flatpak = self._action(g_free, tr("Remove unused Flatpak runtimes"),
                                      tr("Parts left behind by Flatpak apps you removed"),
                                      tr("Remove"), self._clean_flatpak)
        self.b_flatpak.set_sensitive(shutil.which("flatpak") is not None)
        self.add(g_free)

        g_tools = Adw.PreferencesGroup(title=tr("Tools"))
        for title, subtitle, cmd in (
                (tr("Analyze in detail"), tr("Which folders and files take the most space"), "baobab"),
                (tr("Disks"), tr("Format USB drives and memory cards, write disk images, check a "
                                 "disk's health"), "gnome-disks")):
            r = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
            r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            r.connect("activated", lambda _r, c=cmd: self._open(c))
            r.set_sensitive(shutil.which(cmd) is not None)
            g_tools.add(r)
        self.add(g_tools)

        self.connect("map", lambda *_: None if self.loaded else self.refresh())

    def _action(self, group, title, subtitle, label, callback):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: callback())
        row.add_suffix(b)
        group.add(row)
        return b

    @staticmethod
    def _open(cmd):
        spawn(cmd)

    # ------------------------------------------------------------ measuring
    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.loaded = True
        self.progress.set_visible(True)
        self.progress.set_fraction(0)
        self.summary.set_title(tr("Measuring…"))

        def progress(fraction, text):
            GLib.idle_add(lambda: (self.progress.set_fraction(fraction),
                                   self.progress.set_text(text), False)[-1])
        bg(lambda: measure(progress), self._show)

    def _show(self, data):
        self.busy = False
        self.progress.set_visible(False)
        if isinstance(data, Exception):
            self.summary.set_title(tr("Could not measure the disk"))
            self.summary.set_subtitle(str(data))
            return
        s = data["sizes"]
        total = data["total"] or 1
        self.summary.set_title(tr("{used} used of {total}").format(used=size_text(data["used"]),
                                                                   total=size_text(data["total"])))
        self.summary.set_subtitle(tr("{free} free").format(free=size_text(data["free"])))
        order = ["system", "personal", "ai", "flatpak", "packages", "cache", "trash"]
        if not data["home_here"]:
            order = ["system", "ai", "flatpak", "packages"]
        self.bar.set_parts([(s[k] / total, COLORS[k]) for k in order])
        for key, row in self.rows.items():
            if key == "free":
                row.size_label.set_label(size_text(data["free"]))
            else:
                row.size_label.set_label(size_text(s.get(key, 0)))
        if data["home_disk"]:
            h = data["home_disk"]
            self.rows["personal"].set_subtitle(tr("On a separate disk: {used} used, {free} free").format(
                used=size_text(h["used"]), free=size_text(h["free"])))
        self.b_trash.set_sensitive(s["trash"] > 0)
        self.b_thumbs.set_sensitive(s["thumbnails"] > 0)
        self.b_packages.set_sensitive(s["packages"] > 0)

    # ------------------------------------------------------------ freeing space
    def _empty_trash(self):
        def go():
            def done(ok):
                toast(self, tr("Trash emptied") if ok is True else tr("Could not empty the Trash"))
                self.refresh()
            bg(lambda: subprocess.run(["gio", "trash", "--empty"], capture_output=True,
                                      timeout=600).returncode == 0, done)
        confirm(self, tr("Empty the Trash?"), tr("The files in the Trash are deleted for good."),
                tr("Empty Trash"), go, destructive=True)

    def _clear_thumbnails(self):
        def work():
            for name in os.listdir(THUMBNAILS):
                p = os.path.join(THUMBNAILS, name)
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.unlink(p)
            return True

        def done(res):
            toast(self, tr("Thumbnail cache cleared") if res is True
                  else tr("Could not clear the thumbnail cache"))
            self.refresh()
        bg(work, done)

    def _clean_packages(self):
        self.b_packages.set_sensitive(False)

        def done(res):
            ok, outcome = res
            if outcome is None:                   # password window closed
                self.b_packages.set_sensitive(True)
                return
            if ok:
                toast(self, tr("{size} freed").format(size=size_text(outcome.get("freed", 0))))
            else:
                toast(self, outcome.get("error") or tr("Not changed."))
            self.refresh()
        bg(lambda: pkexec_helper(HELPER, "clean-package-cache", timeout=900), done)

    def _clean_flatpak(self):
        self.b_flatpak.set_sensitive(False)

        def work():
            # no --noninteractive: it also forbids the password window that
            # the system installation needs for a user who is not an admin
            r = subprocess.run(["flatpak", "uninstall", "--unused", "-y"],
                               capture_output=True, text=True, timeout=1800)
            return r.returncode == 0

        def done(ok):
            self.b_flatpak.set_sensitive(True)
            toast(self, tr("Unused Flatpak runtimes removed") if ok is True
                  else tr("Could not remove the unused Flatpak runtimes"))
            self.refresh()
        bg(work, done)
