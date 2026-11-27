# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings > Desktop & Icons.

Everything about the icons on the wallpaper: whether they are shown, their
size, the names under them (size, lines, color, shadow or band), the
spacing, the grid, where new icons go, the order, and whether one click or
two opens a file. The values are written to ~/.config/zeta/desktop-look.json
(system/desktop_look.py); the desktop watches that file and changes at once,
without restarting. "Show desktop icons" stays a zeta-appearance key, as in
earlier versions, because zeta-session reads it to start the desktop.

Where each icon sits is never touched here, except by "Arrange icons now",
which asks first.
"""
import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from system import desktop_look  # noqa: E402
from ui.page_tools import bg, confirm, run_quiet, toast  # noqa: E402

APPEARANCE = os.path.expanduser("~/.config/zeta")


def _appearance(key, default):
    try:
        with open(os.path.join(APPEARANCE, key), encoding="utf-8") as f:
            return f.read().strip() or default
    except OSError:
        return default


class DesktopPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.look = desktop_look.load()
        self._timer = None
        self._rows = {}

        # --- showing
        g = Adw.PreferencesGroup(title=tr("Desktop"))
        self.show = Adw.SwitchRow(
            title=tr("Show desktop icons"),
            subtitle=tr("Files and folders of the Desktop folder, Home and Trash on the wallpaper"),
            active=_appearance("desktop-icons", "1") == "1")
        self.show.connect("notify::active", self._on_show)
        g.add(self.show)
        self.add(g)

        # --- icons
        g = Adw.PreferencesGroup(title=tr("Icons"))
        sizes = [tr("Same as the Dock")] + ["%d px" % v for v in desktop_look.ICON_SIZES]
        self._combo(g, "icon_size", tr("Icon size"), tr("Larger icons need more room: an icon that no longer fits is shown nearby and goes back to its place when there is room again"),
                    sizes, [None] + list(desktop_look.ICON_SIZES))
        self._spin(g, "spacing", tr("Spacing"), tr("Space between icons, in pixels"), 0, 64)
        self._switch(g, "grid", tr("Align to grid"),
                     tr("Icons snap into tidy cells. Off: each icon stays exactly where you drop it"))
        self._combo(g, "side", tr("New icons appear"), "",
                    [tr("From the left"), tr("From the right")], ["left", "right"])
        self._combo(g, "direction", tr("Fill order"), "",
                    [tr("Top to bottom, then next column"), tr("Left to right, then next row")],
                    ["columns", "rows"])
        self._combo(g, "click", tr("Open items with"), "",
                    [tr("Double click"), tr("Single click")], ["double", "single"])
        self.add(g)

        # --- names
        g = Adw.PreferencesGroup(title=tr("Names"))
        self._switch(g, "labels", tr("Show names"),
                     tr("Off: only the icons, the name appears when the pointer rests on one"))
        self._combo(g, "label_size", tr("Text size"), "",
                    [tr("Smallest"), tr("Small"), tr("Default"), tr("Large"), tr("Larger"), tr("Largest")],
                    list(desktop_look.LABEL_SIZES))
        self._combo(g, "label_lines", tr("Lines"), tr("Longer names are shortened with …"),
                    ["1", "2", "3", "4"], [1, 2, 3, 4])
        self._switch(g, "label_bold", tr("Bold"), "")
        self._combo(g, "label_color", tr("Text color"), "",
                    [tr("Automatic (follows the theme)"), tr("White"), tr("Black"), tr("Accent color")],
                    list(desktop_look.LABEL_COLORS))
        self._combo(g, "label_effect", tr("Contrast"),
                    tr("Keeps names readable on any wallpaper"),
                    [tr("Soft shadow"), tr("Band behind the text"), tr("None")],
                    list(desktop_look.LABEL_EFFECTS))
        self.add(g)

        # --- arrangement
        g = Adw.PreferencesGroup(
            title=tr("Arrangement"),
            description=tr("Icons stay where you put them, after a restart and when the screen "
                           "resolution changes. They are arranged again only when you ask."))
        self._combo(g, "order", tr("Sort by (when arranging)"), "",
                    [tr("Name"), tr("Type"), tr("Date Modified"), tr("Size")],
                    list(desktop_look.ORDERS))
        arrange = Adw.ActionRow(title=tr("Arrange icons now"),
                                subtitle=tr("Puts every icon in order, by the criterion above"))
        b = Gtk.Button(label=tr("Arrange"), valign=Gtk.Align.CENTER)
        b.connect("clicked", self._on_arrange)
        arrange.add_suffix(b)
        g.add(arrange)
        reset = Adw.ActionRow(title=tr("Reset to default"),
                              subtitle=tr("Every option on this page as it was at first. Where the icons sit is kept"))
        b = Gtk.Button(label=tr("Reset"), valign=Gtk.Align.CENTER)
        b.connect("clicked", self._on_reset)
        reset.add_suffix(b)
        g.add(reset)
        self.add(g)
        self._sensitivity()

    # ------------------------------------------------------------ rows
    def _combo(self, group, key, title, subtitle, labels, values):
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
        if subtitle:
            row.set_subtitle(subtitle)
        cur = self.look[key]
        row.set_selected(values.index(cur) if cur in values else 0)
        row.connect("notify::selected", lambda r, _p: self._set(key, values[r.get_selected()]))
        group.add(row)
        self._rows[key] = (row, values)

    def _switch(self, group, key, title, subtitle):
        row = Adw.SwitchRow(title=title, active=bool(self.look[key]))
        if subtitle:
            row.set_subtitle(subtitle)
        row.connect("notify::active", lambda r, _p: self._set(key, r.get_active()))
        group.add(row)
        self._rows[key] = (row, None)

    def _spin(self, group, key, title, subtitle, lo, hi):
        row = Adw.SpinRow.new_with_range(lo, hi, 2)
        row.set_title(title)
        row.set_subtitle(subtitle)
        row.set_value(self.look[key])
        row.connect("notify::value", lambda r, _p: self._set(key, int(r.get_value())))
        group.add(row)
        self._rows[key] = (row, None)

    def _sensitivity(self):
        on = self.show.get_active()
        for key, (row, _v) in self._rows.items():
            row.set_sensitive(on and (self.look["labels"] or not key.startswith("label_")))

    # ------------------------------------------------------------ actions
    def _set(self, key, value):
        if self.look.get(key) == value:
            return
        self.look[key] = value
        self._sensitivity()
        # a short pause: dragging a value through several steps writes once
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(200, self._save)

    def _save(self):
        self._timer = None
        try:
            desktop_look.save(self.look)
        except OSError as e:
            toast(self, tr("Not saved: {error}").format(error=e))
        return False

    def _on_show(self, row, _p):
        self._sensitivity()
        value = "1" if row.get_active() else "0"

        def done(ok):
            if ok is not True:
                toast(self, tr("Could not apply “{setting}”").format(setting=tr("Show desktop icons")))
            root = self.get_root()
            if hasattr(root, "forget_page"):
                root.forget_page("appearance")
        bg(lambda: run_quiet(["zeta-appearance", "set", "desktop-icons", value], timeout=60), done)

    def _on_arrange(self, *_a):
        def go():
            # the running desktop arranges and removes the request file
            # (it alone writes where the icons sit)
            try:
                with open(os.path.join(desktop_look.CFG, "desktop-arrange"), "w") as f:
                    f.write("1\n")
                toast(self, tr("Icons arranged"))
            except OSError as e:
                toast(self, tr("Not saved: {error}").format(error=e))
        confirm(self, tr("Arrange the icons?"),
                tr("Every icon on the desktop is placed again in order. Your current arrangement is lost."),
                tr("Arrange"), go)

    def _on_reset(self, *_a):
        def go():
            desktop_look.reset()
            self.look = desktop_look.load()
            for key, (row, values) in self._rows.items():
                v = self.look[key]
                if values is not None:
                    row.set_selected(values.index(v) if v in values else 0)
                elif isinstance(row, Adw.SpinRow):
                    row.set_value(v)
                else:
                    row.set_active(bool(v))
            self._sensitivity()
            toast(self, tr("Desktop options reset"))
        confirm(self, tr("Reset the desktop options?"),
                tr("Size, names, spacing, grid and click go back to default. Where the icons sit is kept."),
                tr("Reset"), go)
