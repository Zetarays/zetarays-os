# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings › Startup Applications.

The programs that start by themselves at login: the entries of
~/.config/autostart (the standard place, also used by apps that offer
"start at login"), started by /usr/libexec/zeta-autostart. Here they can be
added from the installed apps, turned off without being removed
(X-GNOME-Autostart-enabled=false, understood by every desktop), or removed.
"""
import os
import shutil

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from ui.page_tools import toast  # noqa: E402

FOLDER = os.path.join(GLib.get_user_config_dir(), "autostart")
OFF_KEY = "X-GNOME-Autostart-enabled"


def entries():
    out = []
    if not os.path.isdir(FOLDER):
        return out
    for name in sorted(os.listdir(FOLDER)):
        if not name.endswith(".desktop"):
            continue
        path = os.path.join(FOLDER, name)
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(path, GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        except GLib.Error:
            continue
        g = "Desktop Entry"

        def get(k, default=""):
            try:
                return kf.get_locale_string(g, k, None)
            except GLib.Error:
                return default
        if get("Hidden") == "true":
            continue
        out.append({"path": path, "name": get("Name", name[:-8]), "comment": get("Comment"),
                    "icon": get("Icon", "application-x-executable"),
                    "on": get(OFF_KEY, "true") != "false"})
    return out


def set_enabled(path, on):
    kf = GLib.KeyFile()
    kf.load_from_file(path, GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    kf.set_string("Desktop Entry", OFF_KEY, "true" if on else "false")
    kf.save_to_file(path)


class StartupPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.group = Adw.PreferencesGroup(
            title=tr("Startup Applications"),
            description=tr("These programs start by themselves a few seconds after you log in. Fewer programs "
                           "make the login faster."))
        add = Gtk.Button(label=tr("Add App…"), valign=Gtk.Align.CENTER)
        add.connect("clicked", self._on_add)
        self.group.set_header_suffix(add)
        self.add(self.group)
        self._rows = []
        self.refresh()

    def refresh(self):
        for r in self._rows:
            self.group.remove(r)
        self._rows = []
        items = entries()
        if not items:
            r = Adw.ActionRow(title=tr("No program starts by itself."))
            self.group.add(r)
            self._rows.append(r)
        for e in items:
            r = Adw.SwitchRow(title=GLib.markup_escape_text(e["name"]),
                              subtitle=GLib.markup_escape_text(e["comment"]), active=e["on"])
            r.add_prefix(Gtk.Image.new_from_icon_name(e["icon"]))
            r.connect("notify::active", self._on_toggle, e["path"])
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                            tooltip_text=tr("Remove from startup"), css_classes=["flat"])
            rm.connect("clicked", self._on_remove, e["path"])
            r.add_suffix(rm)
            self.group.add(r)
            self._rows.append(r)

    def _on_toggle(self, row, _p, path):
        try:
            set_enabled(path, row.get_active())
        except GLib.Error as e:
            toast(self, tr("Not saved: {error}").format(error=e.message))

    def _on_remove(self, _b, path):
        try:
            os.remove(path)
        except OSError as e:
            toast(self, tr("Not saved: {error}").format(error=e))
        self.refresh()

    def _on_add(self, *_a):
        d = Adw.Dialog(title=tr("Add App…"), content_width=420, content_height=520)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        search = Gtk.SearchEntry(placeholder_text=tr("Search"), margin_start=12, margin_end=12, margin_top=6)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(search)
        lb = Gtk.ListBox(css_classes=["boxed-list"], margin_start=12, margin_end=12, margin_bottom=12,
                         selection_mode=Gtk.SelectionMode.NONE)
        apps = sorted((a for a in Gio.AppInfo.get_all() if a.should_show() and isinstance(a, Gio.DesktopAppInfo)),
                      key=lambda a: a.get_display_name().lower())
        for a in apps:
            r = Adw.ActionRow(title=GLib.markup_escape_text(a.get_display_name()), activatable=True)
            icon = a.get_icon()
            if icon:
                r.add_prefix(Gtk.Image.new_from_gicon(icon))
            r.app = a
            r.connect("activated", lambda row, dlg=d: (self._add_app(row.app), dlg.close()))
            lb.append(r)
        lb.set_filter_func(lambda row: search.get_text().lower() in row.app.get_display_name().lower())
        search.connect("search-changed", lambda *_: lb.invalidate_filter())
        sc = Gtk.ScrolledWindow(vexpand=True, child=lb)
        box.append(sc)
        tv.set_content(box)
        d.set_child(tv)
        d.present(self.get_root())

    def _add_app(self, app):
        src = app.get_filename()
        if not src:
            return
        os.makedirs(FOLDER, exist_ok=True)
        dest = os.path.join(FOLDER, os.path.basename(src))
        try:
            shutil.copyfile(src, dest)
            set_enabled(dest, True)
        except (OSError, GLib.Error) as e:
            toast(self, tr("Not saved: {error}").format(error=e))
        toast(self, tr("{app} starts at login").format(app=app.get_display_name()))
        self.refresh()
