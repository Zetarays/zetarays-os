# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — right-click menu for apps, the same everywhere.

Used by the app menu (logo in the bar) and by search: same entries and same
look. It is drawn INSIDE the window (on top of the content, with a
Gtk.Overlay) and not as a popover: the app menu and search are full-screen
layers with exclusive keyboard focus, and there the GTK popup received the
click but lost it (the entry highlighted, the menu closed, the action did not
run; from the keyboard it worked). Quick actions (Desktop, Dock, remove from
menu) are done here; those that open a window (About, Uninstall) are opened
by "zeta-app" as a normal window.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from system import applications as reg  # noqa: E402

CSS = """
.zeta-menu-app { background: @surface; border: 1px solid @line; border-radius: 12px;
                 padding: 6px; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45); }
.zeta-menu-entry { background: none; border: none; box-shadow: none; padding: 7px 14px;
                  border-radius: 8px; min-height: 0; }
.zeta-menu-entry:hover, .zeta-menu-entry:focus-visible { background: @hover_2; }
.zeta-menu-entry label { font-size: 13px; color: @ink; }
.zeta-menu-entry.danger label { color: #FF6B6B; }
.zeta-menu-sep { margin: 4px 8px; background: @line; min-height: 1px; }
"""
_style_loaded = [False]


def _load_style():
    if _style_loaded[0]:
        return
    prov = Gtk.CssProvider()
    prov.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
    _style_loaded[0] = True


class OverlayMenu:
    """Menu drawn on top of a window's content (Gtk.Overlay)."""

    def __init__(self, overlay):
        self.overlay = overlay
        self.box = None
        _load_style()

    def opened(self):
        return self.box is not None

    def contains(self, widget):
        while widget is not None:
            if widget is self.box:
                return True
            widget = widget.get_parent()
        return False

    def close_window(self):
        if self.box is not None:
            self.overlay.remove_overlay(self.box)
            self.box = None

    def open_at(self, widget, x, y, entries):
        self.close_window()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                      halign=Gtk.Align.START, valign=Gtk.Align.START)
        box.add_css_class("zeta-menu-app")
        first = None
        for entry in entries:
            if entry is None:
                sep = Gtk.Box()
                sep.add_css_class("zeta-menu-sep")
                box.append(sep)
                continue
            # (label, action) or (label, action, True) for a dangerous entry
            label, fn = entry[0], entry[1]
            b = Gtk.Button(child=Gtk.Label(label=label, xalign=0))
            b.add_css_class("zeta-menu-entry")
            if len(entry) > 2 and entry[2]:
                b.add_css_class("danger")
            b.connect("clicked", lambda _b, f=fn: (self.close_window(), f()))
            box.append(b)
            first = first or b
        # position: where the click happened, but always inside the window
        point = widget.translate_coordinates(self.overlay, x, y)   # (ok, x, y)
        if point and len(point) == 3 and not point[0]:
            point = None
        px, py = (point[-2], point[-1]) if point else (x, y)
        width = box.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        alt = box.measure(Gtk.Orientation.VERTICAL, width)[1]
        W, H = self.overlay.get_width(), self.overlay.get_height()
        box.set_margin_start(int(max(8, min(px, W - width - 8))))
        box.set_margin_top(int(max(8, min(py, H - alt - 8))))
        self.overlay.add_overlay(box)
        self.box = box
        if first is not None:
            GLib.idle_add(lambda: (first.grab_focus(), False)[1])


def _zeta_app(*argv):
    reg.spawn(["zeta-app", *argv])


def notice(title, text=""):
    reg.spawn(["notify-send", "-a", "ZETA RAYS", "-i", "zeta-app", title, text])


def app_entries(app, launch, after=None):
    """Menu entries for an app from the registry. launch: how to launch it from
    here; after: called after every action (to close the app menu)."""
    def done(fn):
        def f():
            fn()
            if after:
                after()
        return f

    def outcome(result):
        ok, msg = result
        notice(msg)

    entries = [(tr("Open"), done(lambda: launch(app))),
            (tr("Open file location"), done(lambda: reg.show_in_file_manager(reg.position(app)))),
            None]
    on_desktop = reg.on_desktop(app) or reg.appimage_on_desktop(app)
    if on_desktop:
        entries.append((tr("Already on the Desktop"),
                     done(lambda: reg.show_in_file_manager(on_desktop))))
    else:
        entries.append((tr("Add to Desktop"), done(lambda: outcome(reg.add_to_desktop(app)))))
    if reg.in_dock(app):
        entries.append((tr("Remove from Dock"), done(lambda: outcome(reg.remove_from_dock(app)))))
    else:
        entries.append((tr("Add to Dock"), done(lambda: outcome(reg.add_to_dock(app)))))
    entries += [None, (tr("Get info"), done(lambda: _zeta_app("info", app.id))),
             (tr("Change icon…"), done(lambda: _zeta_app("set-icon", app.id)))]
    if app.custom_icon:
        entries.append((tr("Restore icon"), done(lambda: outcome(reg.restore_icon(app)))))
    if not app.protected:
        entries.append((tr("Remove from Applications"), done(
            lambda: (reg.hide_away(app), notice(tr("“{name}” removed from the menu").format(name=app.name),
                                               tr("Put it back from Settings › Default Apps.")))))
        )
        can_uninstall, _reason = reg.uninstallable(app)
        if can_uninstall:
            entries.append((tr("Uninstall…"), done(lambda: _zeta_app("uninstall", app.id)), True))
    return entries
