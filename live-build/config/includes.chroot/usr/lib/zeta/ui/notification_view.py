# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS: recent notifications and Do Not Disturb, a view of zeta-clipboard
(opened by "zeta-dnd history" and by the bell in the bar).

The notifications come from mako over D-Bus (fr.emersion.Mako: the ones still
on screen, or hidden by Do Not Disturb, and the history), asked
asynchronously: the panel appears at once and fills in a moment later.
"Clear" dismisses the ones on screen and hides the history (see
system/notifications.py: mako has no command to empty it).
"""
import html
import re

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

from i18n import tr  # noqa: E402
from system import notifications as N  # noqa: E402
from system import spawn  # noqa: E402

CSS = """
list.notif-list { background: none; }
list.notif-list > row { border-radius: 12px; padding: 10px 12px; margin-bottom: 6px;
                        background: @surface_2; }
.notif-app { font-size: 11px; color: @ink_dim; font-weight: 500; }
.notif-summary { font-size: 13px; font-weight: 500; }
.notif-body { font-size: 12px; color: @ink_2; }
.notif-head { font-size: 14px; font-weight: 600; }
"""


def _plain(value):
    """Text of a field: strings only, without the markup (<b>, <i>, links)
    that mako and some apps use in the body."""
    if not isinstance(value, str):
        return ""
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()


class NotificationView(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.bus = None
        self.mako_pid = 0
        self.newest = 0
        self.pending = 0
        self.collected = []

        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label=tr("Notifications"), css_classes=["notif-head"],
                              hexpand=True, xalign=0))
        head.append(Gtk.Label(label=tr("Do Not Disturb"), css_classes=["zeta-small"]))
        self.dnd = Gtk.Switch(valign=Gtk.Align.CENTER,
                              tooltip_text=tr("Hide notifications. Critical ones still appear."))
        self.dnd_handler = self.dnd.connect("notify::active", self._dnd_switched)
        head.append(self.dnd)
        self.append(head)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["notif-list"])
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    child=self.list, propagate_natural_height=True,
                                    max_content_height=520)
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, vexpand=True,
                        valign=Gtk.Align.CENTER, margin_top=24, margin_bottom=24)
        empty.append(Gtk.Image(icon_name="zeta-bell", pixel_size=36, opacity=0.6))
        empty.append(Gtk.Label(label=tr("No notifications"), css_classes=["zeta-dim"]))
        self.stack = Gtk.Stack(vhomogeneous=False)
        self.stack.add_named(scroll, "list")
        self.stack.add_named(empty, "empty")
        self.append(self.stack)

        foot = Gtk.Box(spacing=8)
        foot.append(Gtk.Label(label=tr("Notifications hidden by Do Not Disturb appear here."),
                              css_classes=["zeta-dim", "zeta-small"], hexpand=True, xalign=0,
                              wrap=True))
        self.clear = Gtk.Button(label=tr("Clear"), css_classes=["zeta-flat", "zeta-small"],
                                valign=Gtk.Align.CENTER)
        self.clear.connect("clicked", lambda *_: self.clear_all())
        foot.append(self.clear)
        self.append(foot)

    # --- D-Bus ---
    def _call(self, method, params, reply_type, callback, iface=N.MAKO_IFACE, path=N.MAKO_PATH,
              name=N.BUS_NAME):
        if self.bus is None:
            try:
                self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            except GLib.Error:
                callback(None)
                return

        def finished(bus, result):
            try:
                callback(bus.call_finish(result).unpack())
            except GLib.Error:
                callback(None)
        self.bus.call(name, path, iface, method, params,
                      GLib.VariantType.new(reply_type) if reply_type else None,
                      Gio.DBusCallFlags.NO_AUTO_START, 2000, None, finished)

    def prepare(self):
        self.collected = []
        self.pending = 3
        self._call("GetConnectionUnixProcessID", GLib.Variant("(s)", (N.BUS_NAME,)), "(u)",
                   self._got_pid, iface="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                   name="org.freedesktop.DBus")
        self._call("ListNotifications", None, "(aa{sv})", self._got_list)
        self._call("ListHistory", None, "(aa{sv})", self._got_list)
        self._call("ListModes", None, "(as)", self._got_modes)

    def focus(self):
        self.clear.grab_focus()

    def _got_pid(self, reply):
        self.mako_pid = reply[0] if reply else 0
        self._one_done()

    def _got_list(self, reply):
        if reply:
            self.collected.extend(reply[0])
        self._one_done()

    def _got_modes(self, reply):
        on = bool(reply) and N.DND_MODE in reply[0]
        with self.dnd.handler_block(self.dnd_handler):
            self.dnd.set_active(on)

    def _one_done(self):
        self.pending -= 1
        if self.pending > 0:
            return
        seen = set()
        items = []
        for n in self.collected:
            ident = int(n.get("id", 0))
            if ident not in seen:
                seen.add(ident)
                items.append(n)
        self.newest = max(seen) if seen else 0
        self.fill(N.not_cleared(items, self.mako_pid))

    def fill(self, items):
        self.list.remove_all()
        for n in items[:50]:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            app = _plain(n.get("app-name"))
            if app:
                box.append(Gtk.Label(label=app, xalign=0, css_classes=["notif-app"],
                                     ellipsize=Pango.EllipsizeMode.END))
            summary = _plain(n.get("summary"))
            if summary:
                box.append(Gtk.Label(label=summary, xalign=0, wrap=True, css_classes=["notif-summary"],
                                     wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=40))
            body = _plain(n.get("body"))
            if body:
                box.append(Gtk.Label(label=body, xalign=0, wrap=True, lines=4,
                                     ellipsize=Pango.EllipsizeMode.END, css_classes=["notif-body"],
                                     wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=40))
            self.list.append(box)
        has = bool(items)
        self.clear.set_sensitive(has)
        self.stack.set_visible_child_name("list" if has else "empty")

    # --- actions ---
    def clear_all(self):
        if self.mako_pid:
            N.mark_cleared(self.mako_pid, self.newest)
        self._call("DismissNotifications",
                   GLib.Variant("(a{sv})", ({"all": GLib.Variant("b", True),
                                             "history": GLib.Variant("b", False)},)),
                   None, lambda _r: None)
        self.fill([])

    def _dnd_switched(self, sw, _param):
        spawn(["zeta-dnd", "on" if sw.get_active() else "off"])
