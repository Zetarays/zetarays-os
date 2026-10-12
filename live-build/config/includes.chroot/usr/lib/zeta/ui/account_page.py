# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › Account: name, user and picture.

The picture (round, 512 px) is shown in the power and account menu, on the
lock screen and at login. It can be a photo of the user (.jpg or .png, cut
to a circle from the center) or a plain circle in one of the four system
colors (the palette in ui/accent.py), by default the accent color.
"""
import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from system import avatar  # noqa: E402
from ui import accent  # noqa: E402

CSS = """
.av-color { min-width: 40px; min-height: 40px; padding: 0; border-radius: 999px; }
.av-color.av-light { box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.22); }
.av-color.av-chosen { outline: 2px solid @accent_bg_color; outline-offset: 3px; }
""" + "".join(".av-color-%s { background: %s; }\n" % (k, c) for k, c, _n in accent.PALETTE)
_css_loaded = False


def _load_css():
    global _css_loaded
    if _css_loaded:
        return
    prov = Gtk.CssProvider()
    prov.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_loaded = True


def _image(path, side):
    """Fixed-size image (the file is already round, with transparency).
    Gtk.Image with pixel_size: a Gtk.Picture would grow to the real size."""
    img = Gtk.Image(pixel_size=side, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    _load(img, path)
    return img


def _load(img, path):
    try:
        # always from disk: after a change the file keeps the same name
        img.set_from_paintable(Gdk.Texture.new_from_filename(path))
    except GLib.Error:
        img.set_from_icon_name("zeta-account")


class AccountPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        full_name, user = avatar.full_name()

        header = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
        self.large = _image(avatar.path(), 128)
        box.append(self.large)
        box.append(Gtk.Label(label=full_name, css_classes=["title-2"]))
        box.append(Gtk.Label(label="%s · %s" % (user, os.uname().nodename),
                             css_classes=["dim-label"]))
        header.add(box)
        self.add(header)

        group = Adw.PreferencesGroup(
            title=tr("Picture"),
            description=tr("Shown in the account menu, on the lock screen and at login."))
        choose = Adw.ActionRow(title=tr("Choose a Picture…"),
                               subtitle=tr("A .jpg or .png photo, cut to a circle from the centre"),
                               activatable=True)
        choose.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        choose.connect("activated", lambda *_: self._choose_file())
        group.add(choose)

        self.add(group)

        # a filled circle in a system color, with no drawing
        _load_css()
        colors = Adw.PreferencesGroup(
            title=tr("Color"),
            description=tr("Or a plain circle in one of the system colors."))
        self.follow = Adw.SwitchRow(title=tr("Same as the Accent Color"),
                                   subtitle=tr("Changes when you change the accent color"))
        self.follow.connect("notify::active", self._follow_changed)
        colors.add(self.follow)
        row = Gtk.Box(spacing=18, halign=Gtk.Align.START, margin_top=14, margin_bottom=14,
                       margin_start=14, margin_end=14)
        self.buttons = []
        for key, color, _name in accent.PALETTE:
            b = Gtk.Button(css_classes=["av-color", "av-color-" + key],
                           tooltip_text=accent.color_name(key), valign=Gtk.Align.CENTER)
            if color == "#FFFFFF":
                b.add_css_class("av-light")       # keeps white visible on a light theme too
            b.color = color
            b.connect("clicked", lambda btn: self._run_job(lambda c=btn.color: avatar.set_color(c)))
            row.append(b)
            self.buttons.append(b)
        colors.add(Adw.PreferencesRow(activatable=False, child=row))
        self.add(colors)
        self._mark_choice()

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)
        self.connect("map", lambda *_: (_load(self.large, avatar.path()), self._mark_choice()))

    def _choose_file(self):
        file_filter = Gtk.FileFilter(name=tr("Pictures (.jpg, .png)"))
        for extension in ("png", "jpg", "jpeg", "PNG", "JPG", "JPEG"):
            file_filter.add_suffix(extension)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog = Gtk.FileDialog(title=tr("Choose a Picture"), filters=filters, modal=True)
        dialog.open(self.get_root(), None, self._chosen)

    def _chosen(self, dialog, outcome):
        try:
            f = dialog.open_finish(outcome)
        except GLib.Error:
            return                                   # canceled
        if f and f.get_path():
            p = f.get_path()
            self._run_job(lambda: avatar.set_from_file(p))

    def _on_drop(self, _t, value, _x, _y):
        files = value.get_files() if hasattr(value, "get_files") else []
        if files and files[0].get_path():
            p = files[0].get_path()
            self._run_job(lambda: avatar.set_from_file(p))
            return True
        return False

    def _run_job(self, job):
        def worker():
            ok, msg = job()
            GLib.idle_add(self._done, ok, msg)
        threading.Thread(target=worker, daemon=True).start()

    def _mark_choice(self):
        """Switch and highlighted color according to the saved choice."""
        choice = avatar.choice()
        self._updating = True
        self.follow.set_active(choice == "accent")
        self._updating = False
        current = avatar.current_color() if choice != "photo" else None
        for b in self.buttons:
            if b.color == current:
                b.add_css_class("av-chosen")
            else:
                b.remove_css_class("av-chosen")

    def _follow_changed(self, line, _p):
        if getattr(self, "_updating", False):
            return
        if line.get_active():
            self._run_job(lambda: avatar.set_color("accent"))
        else:
            # keep the current color, but fixed
            c = avatar.current_color()
            if any(c == x for _k, x, _n in accent.PALETTE):
                self._run_job(lambda: avatar.set_color(c))
            else:
                self._run_job(lambda: avatar.set_color(accent.DEFAULT))

    def _done(self, ok, msg):
        _load(self.large, avatar.path())
        self._mark_choice()
        toasts = getattr(self.get_root(), "toasts", None)
        if toasts is not None:
            toasts.add_toast(Adw.Toast(title=msg, timeout=3, use_markup=False))
        # the account menu (zeta-power-menu) rereads the picture every time it
        # opens; the lock screen reads it from ~/.face
        return False
