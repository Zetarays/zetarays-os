# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › Fonts: the font library.

Every font of the computer shown in its own typeface, with a sample text
that can be changed, a search, "Add Fonts…" (the files are copied into
~/.local/share/fonts and are ready at once in every app) and removal of the
fonts added by the user. System fonts belong to the system packages and are
not removed here.

The list is read only when the page is opened, and built a few rows at a
time: Settings must open instantly even with hundreds of fonts installed.
"""
import os
import shutil
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from i18n import ntr, tr  # noqa: E402

FOLDER = os.path.join(GLib.get_user_data_dir(), "fonts")
EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".pfb")
SAMPLE_TEXT = "The quick brown fox jumps over the lazy dog 0123456789"


def _is_user_font(path):
    home = os.path.expanduser("~")
    return path.startswith((FOLDER + os.sep, os.path.join(home, ".fonts") + os.sep))


def font_families():
    """{family: {"styles": set, "files": set, "user": bool}} from fontconfig."""
    try:
        r = subprocess.run(["fc-list", "--format", "%{family[0]}\\t%{style[0]}\\t%{file}\\n"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        pieces = line.split("\t")
        if len(pieces) != 3 or not pieces[0].strip():
            continue
        fam, style, file = pieces[0].strip(), pieces[1].strip(), pieces[2].strip()
        entry = out.setdefault(fam, {"styles": set(), "files": set(), "user": False})
        entry["styles"].add(style)
        entry["files"].add(file)
        entry["user"] = entry["user"] or _is_user_font(file)
    return out


def _update_cache():
    subprocess.run(["fc-cache", "-f", FOLDER], capture_output=True, timeout=120)


class FontsPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self._loaded = False
        self._lines = []
        self._sample = SAMPLE_TEXT

        intro = Adw.PreferencesGroup(
            title=tr("Fonts"),
            description=tr("The fonts of this computer, each shown in its own typeface. "
                           "Fonts you add are ready at once in every app."))
        add = Gtk.Button(label=tr("Add Fonts…"), valign=Gtk.Align.CENTER,
                              css_classes=["suggested-action"])
        add.connect("clicked", lambda *_: self._choose_file())
        intro.set_header_suffix(add)
        self.search = Adw.EntryRow(title=tr("Search fonts"))
        self.search.connect("changed", lambda *_: self._filter_rows())
        intro.add(self.search)
        self.test = Adw.EntryRow(title=tr("Sample text"))
        self.test.set_text(SAMPLE_TEXT)
        self.test.connect("changed", lambda *_: self._sample_changed())
        intro.add(self.test)
        self.add(intro)

        self.group = Adw.PreferencesGroup()
        self.items = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,
                                 css_classes=["boxed-list"])
        self.items.set_filter_func(self._visible)
        self.wait = Adw.ActionRow(title=tr("Reading the fonts…"))
        self.items.append(self.wait)
        self.group.add(self.items)
        self.add(self.group)

        # «Add Fonts…» also by dropping files on the page
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        self.connect("map", lambda *_: self._load())

    # ---- list
    def _load(self, force=False):
        if self._loaded and not force:
            return
        self._loaded = True

        def work():
            data = font_families()
            GLib.idle_add(self._show, data)
        threading.Thread(target=work, daemon=True).start()

    def _show(self, data):
        for r in self._lines + [self.wait]:
            if r.get_parent() is not None:
                self.items.remove(r)
        self._lines = []
        entries = sorted(data.items(), key=lambda kv: (not kv[1]["user"], kv[0].casefold()))
        self.group.set_description(ntr("{n} font family", "{n} font families", len(entries))
                                    .format(n=len(entries)))

        def in_batches(i=0):
            for fam, v in entries[i:i + 40]:
                self._row(fam, v)
            if i + 40 < len(entries):
                GLib.idle_add(in_batches, i + 40)
            return False
        in_batches()
        return False

    def _row(self, family, entry):
        line = Adw.ActionRow(use_markup=True)
        line.family = family
        line.set_title(GLib.markup_escape_text(family))
        n = len(entry["styles"])
        origin = tr("Added by you") if entry["user"] else tr("System")
        line.set_subtitle(GLib.markup_escape_text(
            ntr("{n} style", "{n} styles", n).format(n=n) + " · " + origin))
        # preview on the right at a fixed width: the name and the details on
        # the left stay whole
        test = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=30,
                          width_chars=30,
                          margin_top=4, margin_bottom=4)
        test.add_css_class("zeta-font-sample")
        line.test = test
        self._set_sample(line)
        line.add_suffix(test)
        if entry["user"]:
            via = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text=tr("Remove"))
            via.add_css_class("flat")
            via.connect("clicked", lambda *_a, v=entry, f=family: self._remove(f, v))
            line.add_suffix(via)
        self.items.append(line)
        self._lines.append(line)

    def _set_sample(self, line):
        text = GLib.markup_escape_text(self._sample or line.family)
        family = GLib.markup_escape_text(line.family).replace('"', "&quot;")
        line.test.set_markup('<span font_family="%s" size="large">%s</span>' % (family, text))

    def _sample_changed(self):
        self._sample = self.test.get_text().strip() or SAMPLE_TEXT
        for r in self._lines:
            self._set_sample(r)

    def _visible(self, line):
        q = self.search.get_text().strip().casefold()
        return not q or not hasattr(line, "family") or q in line.family.casefold()

    def _filter_rows(self):
        self.items.invalidate_filter()

    # ---- adding and removing
    def _choose_file(self):
        file_filter = Gtk.FileFilter(name=tr("Fonts"))
        for e in EXTENSIONS:
            file_filter.add_suffix(e.lstrip("."))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog = Gtk.FileDialog(title=tr("Add Fonts"), filters=filters, modal=True)
        dialog.open_multiple(self.get_root(), None, self._chosen)

    def _chosen(self, dialog, outcome):
        try:
            files = dialog.open_multiple_finish(outcome)
        except GLib.Error:
            return                       # annullato
        self._install([f.get_path() for f in files if f.get_path()])

    def _on_drop(self, _t, value, _x, _y):
        files = value.get_files() if hasattr(value, "get_files") else []
        self._install([f.get_path() for f in files if f.get_path()])
        return True

    def _install(self, paths):
        valid = [p for p in paths if p.lower().endswith(EXTENSIONS) and os.path.isfile(p)]
        if not valid:
            self._notice(tr("No font files: choose .ttf, .otf, .ttc or .woff files."))
            return

        def work():
            os.makedirs(FOLDER, exist_ok=True)
            copied = 0
            for p in valid:
                dest = os.path.join(FOLDER, os.path.basename(p))
                try:
                    if os.path.abspath(p) != os.path.abspath(dest):
                        shutil.copy2(p, dest)
                    copied += 1
                except OSError:
                    continue
            _update_cache()
            GLib.idle_add(self._installed, copied)
        threading.Thread(target=work, daemon=True).start()

    def _installed(self, n):
        self._notice(ntr("{n} font added: it is ready in every app.",
                         "{n} fonts added: they are ready in every app.", n).format(n=n))
        self._load(force=True)
        return False

    def _remove(self, family, entry):
        def work():
            for f in entry["files"]:
                if _is_user_font(f):
                    try:
                        Gio.File.new_for_path(f).trash(None)     # recuperabile dal Cestino
                    except GLib.Error:
                        pass
            _update_cache()
            GLib.idle_add(lambda: (self._notice(tr("“{name}” moved to the Trash.").format(name=family)),
                                   self._load(force=True)) and False)
        threading.Thread(target=work, daemon=True).start()

    def _notice(self, text):
        toasts = getattr(self.get_root(), "toasts", None)
        if toasts is not None:
            toasts.add_toast(Adw.Toast(title=text, timeout=4, use_markup=False))
