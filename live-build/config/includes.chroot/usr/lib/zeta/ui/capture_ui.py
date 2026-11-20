# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — the windows of zeta-screenshot (GTK4, layer shell).

One process, started the first time it is needed and then kept in memory,
hidden (like the bar panels: the next opening is instant, and while hidden
it uses no CPU). It shows:

  toolbar     Region | Window | Full Screen | Record Region | Record Screen,
              timer, options (bottom centre; Print key)
  card        a capture just taken: thumbnail, Edit, Copy Text, Open Folder,
              Delete (a click on the notification opens it)
  indicator   while recording: red dot, elapsed time, Stop (a corner the
              recording does not cover)

The captures themselves are made by the command line (system/capture.py),
started from here after the toolbar has disappeared from the screen.
popup.preload_layer_shell() must have run before this module is imported.
"""
import os
import shutil
import sys
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from i18n import tr, trc  # noqa: E402
from system import capture, spawn  # noqa: E402
from ui import popup  # noqa: E402

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LS  # noqa: E402
except (ValueError, ImportError):
    LS = None

CSS = """
.zs-card { padding: 10px 12px; }
button.zs-mode { padding: 8px 6px; border-radius: 12px; background: none; border: none;
                 box-shadow: none; min-width: 84px; }
button.zs-mode:hover, button.zs-mode:focus-visible { background: @hover; }
.zs-mode-label { font-size: 11px; color: @ink_2; }
.zs-small { font-size: 12px; color: @ink_2; }
button.zs-seg { padding: 2px 10px; min-height: 24px; border-radius: 8px; background: @hover;
                border: none; box-shadow: none; }
button.zs-seg label { font-size: 12px; }
button.zs-seg:hover { background: @hover_2; }
button.zs-seg.on { background: @accent; }
button.zs-seg.on label { color: @accent_ink; }
checkbutton label { font-size: 12px; color: @ink_2; }
.zs-sep { min-width: 1px; background: @line; margin: 8px 4px; }
.zs-pill { background: @surface; border: 1px solid @line; border-radius: 999px;
           padding: 5px 5px 5px 14px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35); }
.zs-dot { background: #FF453A; border-radius: 999px; min-width: 10px; min-height: 10px; }
.zs-time { font-size: 13px; font-weight: 500; font-feature-settings: "tnum"; }
button.zs-stop { background: @hover; border-radius: 999px; padding: 3px 12px 3px 8px;
                 border: none; box-shadow: none; }
button.zs-stop:hover { background: @hover_2; }
button.zs-stop label { font-size: 12px; font-weight: 500; }
.zs-thumb { border-radius: 10px; background: @surface_2; }
.zs-name { font-size: 12px; color: @ink_dim; }
.zs-status { font-size: 12px; color: @ink_2; }
"""

# start time of the command that started this process (ZETA_CAPTURE_TIMING=1
# prints when the toolbar becomes visible); not passed on to child processes
T0 = float(os.environ.pop("ZETA_CAPTURE_T0", "") or time.time())


def _icon_button(icon, label, css, tooltip=None):
    b = Gtk.Button(css_classes=[css], tooltip_text=tooltip or label)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.append(Gtk.Image(icon_name=icon, pixel_size=22))
    box.append(Gtk.Label(label=label, css_classes=["zs-mode-label"]))
    b.set_child(box)
    return b


def _separator():
    return Gtk.Box(css_classes=["zs-sep"])


def _bg(work, done=None):
    def runner():
        res = work()
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])
    threading.Thread(target=runner, daemon=True).start()


def _gdk_monitor(connector):
    if not connector:
        return None
    monitors = Gdk.Display.get_default().get_monitors()
    for i in range(monitors.get_n_items()):
        m = monitors.get_item(i)
        if m.get_connector() == connector:
            return m
    return None


# ------------------------------------------------------------------ toolbar
class Toolbar(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=tr("Screenshot"), decorated=False)
        popup.make_overlay(self, "zeta-screenshot")
        if LS and LS.is_supported():
            LS.set_exclusive_zone(self, 0)          # stays above the bar, not under it
        self.settings = capture.load_settings()

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                       css_classes=["zeta-card", "zs-card"], halign=Gtk.Align.CENTER,
                       valign=Gtk.Align.END, margin_bottom=14)
        self.card = card

        modes = Gtk.Box(spacing=2)
        self.first = None
        for icon, label, cmd in (
                ("zeta-capture-region", trc("screenshot mode", "Region"), ["region"]),
                ("zeta-capture-window", tr("Window"), ["window"]),
                ("zeta-capture-screen", tr("Full Screen"), ["screen"])):
            b = _icon_button(icon, label, "zs-mode")
            b.connect("clicked", lambda _b, c=cmd: self.run(c))
            modes.append(b)
            self.first = self.first or b
        modes.append(_separator())
        self.record_buttons = []
        for icon, label, cmd in (
                ("zeta-capture-record-region", tr("Record Region"), ["record", "region"]),
                ("zeta-capture-record-screen", tr("Record Screen"), ["record", "screen"])):
            b = _icon_button(icon, label, "zs-mode")
            b.connect("clicked", lambda _b, c=cmd: self.run(c))
            modes.append(b)
            self.record_buttons.append(b)
        self.stop_button = _icon_button("zeta-capture-stop", tr("Stop Recording"), "zs-mode")
        self.stop_button.connect("clicked", lambda *_: self.stop_recording())
        modes.append(self.stop_button)
        if shutil.which("hyprpicker"):
            modes.append(_separator())
            b = _icon_button("zeta-capture-color", tr("Pick Color"), "zs-mode",
                             tr("Copy the color of a point on the screen"))
            b.connect("clicked", lambda *_: self.run(["color"], delay=False))
            modes.append(b)
        modes.append(_separator())
        close = Gtk.Button(css_classes=["zeta-round"], valign=Gtk.Align.CENTER,
                           tooltip_text=tr("Close"), margin_start=4)
        close.set_child(Gtk.Image(icon_name="zeta-capture-close", pixel_size=16))
        close.connect("clicked", lambda *_: self.close_bar())
        modes.append(close)
        card.append(modes)

        opts = Gtk.Box(spacing=6, margin_start=6, margin_end=6)
        opts.append(Gtk.Image(icon_name="zeta-capture-timer", pixel_size=16))
        opts.append(Gtk.Label(label=tr("Timer"), css_classes=["zs-small"], margin_end=2))
        self.delay_buttons = {}
        for d in capture.DELAYS:
            b = Gtk.Button(label=tr("Off") if d == 0 else tr("{n} s").format(n=d),
                           css_classes=["zs-seg"], valign=Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, v=d: self.set_delay(v))
            opts.append(b)
            self.delay_buttons[d] = b
        opts.append(Gtk.Box(hexpand=True, width_request=16))
        self.checks = {}
        for key, label in (("save", tr("Save to file")), ("copy", tr("Copy to clipboard")),
                           ("pointer", tr("Show the pointer")), ("audio", tr("Record sound"))):
            c = Gtk.CheckButton(label=label)
            c.connect("toggled", lambda w, k=key: self.set_option(k, w.get_active()))
            opts.append(c)
            self.checks[key] = c
        self.checks["audio"].set_tooltip_text(tr("Records what the computer plays"))
        self.checks["pointer"].set_tooltip_text(tr("Screenshots include the mouse pointer"))
        card.append(opts)

        self.set_child(card)
        popup.close_on_outside(self, card, self.close_bar)
        self._timed = False
        self.connect("map", self._mapped)

    def _mapped(self, *_):
        if os.environ.get("ZETA_CAPTURE_TIMING") and not self._timed:
            self._timed = True
            print("toolbar visible after %d ms" % ((time.time() - T0) * 1000), file=sys.stderr)

    def prepare(self):
        """Every time it appears: current options and recording state."""
        self.settings = capture.load_settings()
        for key, c in self.checks.items():
            c.set_active(bool(self.settings[key]))
        self._show_delay()
        recording = capture.recording_state() is not None
        for b in self.record_buttons:
            b.set_visible(not recording)
        self.stop_button.set_visible(recording)
        GLib.idle_add(lambda: self.first.grab_focus() and False)

    def _show_delay(self):
        for d, b in self.delay_buttons.items():
            if d == self.settings["delay"]:
                b.add_css_class("on")
            else:
                b.remove_css_class("on")

    def set_delay(self, d):
        self.settings["delay"] = d
        self._show_delay()
        self._save()

    def set_option(self, key, value):
        if self.settings.get(key) == value:
            return
        self.settings[key] = value
        # at least one of "save" and "copy": otherwise a capture would vanish
        if not self.settings["save"] and not self.settings["copy"]:
            other = "copy" if key == "save" else "save"
            self.settings[other] = True
            self.checks[other].set_active(True)
        self._save()

    def _save(self):
        try:
            capture.save_settings(self.settings)
        except OSError:
            pass

    def run(self, cmd, delay=True):
        """Hide first: the capture starts once the toolbar is off the screen
        (its layer has no closing animation, see hyprland.lua)."""
        args = ["zeta-screenshot"] + cmd
        if delay and self.settings["delay"]:
            args += ["--delay", str(self.settings["delay"])]
        self.set_visible(False)
        GLib.timeout_add(120, lambda: (spawn(args), False)[1])

    def stop_recording(self):
        self.set_visible(False)
        _bg(lambda: capture.stop_recording(wait=False))

    def close_bar(self):
        self.set_visible(False)       # stays in memory: the next opening is instant
        return False


# ------------------------------------------------------------------ card
class Card(Gtk.ApplicationWindow):
    """A capture just made, with what can be done with it."""

    def __init__(self, app):
        super().__init__(application=app, title=tr("Screenshot"), decorated=False)
        popup.make_overlay(self, "zeta-screenshot-card")
        self.path = None
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                       css_classes=["zeta-card", "zs-card"], halign=Gtk.Align.END,
                       valign=Gtk.Align.START, margin_top=12, margin_end=12, width_request=340)
        head = Gtk.Box(spacing=8)
        self.title = Gtk.Label(xalign=0, hexpand=True, css_classes=["zeta-title"])
        head.append(self.title)
        close = Gtk.Button(css_classes=["zeta-round"], tooltip_text=tr("Close"))
        close.set_child(Gtk.Image(icon_name="zeta-capture-close", pixel_size=14))
        close.connect("clicked", lambda *_: self.close_card())
        head.append(close)
        card.append(head)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True,
                                   css_classes=["zs-thumb"], height_request=180, width_request=316)
        card.append(self.picture)
        self.name = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, css_classes=["zs-name"])
        card.append(self.name)
        self.buttons = Gtk.Box(spacing=2, halign=Gtk.Align.CENTER)
        card.append(self.buttons)
        self.status = Gtk.Label(xalign=0, wrap=True, max_width_chars=44, css_classes=["zs-status"],
                                visible=False)
        card.append(self.status)
        self.set_child(card)
        popup.close_on_outside(self, card, self.close_card)

    def load(self, path):
        self.path = path
        video = not path.lower().endswith(".png")
        self.title.set_text(tr("Screen recording") if video else tr("Screenshot"))
        self.name.set_text(os.path.basename(path) if capture.is_saved(path) else tr("Not saved to a file"))
        self.status.set_visible(False)
        self.picture.set_paintable(None)
        if video:
            _bg(lambda: capture.thumbnail(path), self._thumb)
        else:
            self._thumb(path)
        child = self.buttons.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.buttons.remove(child)
            child = nxt
        if video:
            items = [("zeta-capture-play", tr("Play"), "open")]
        else:
            items = [("zeta-capture-edit", tr("Edit"), "edit"),
                     ("zeta-capture-text", tr("Copy Text"), "text")]
        if capture.is_saved(path):
            items += [("zeta-capture-folder", tr("Open Folder"), "folder"),
                      ("zeta-capture-trash", tr("Delete"), "delete")]
        else:
            items += [("zeta-capture-save", tr("Save"), "save")]
        first = None
        for icon, label, key in items:
            b = _icon_button(icon, label, "zs-mode")
            b.connect("clicked", lambda btn, k=key: self.act(k, btn))
            self.buttons.append(b)
            first = first or b
        GLib.idle_add(lambda: first.grab_focus() and False)

    def _thumb(self, thumb):
        if thumb and os.path.exists(thumb):
            try:
                self.picture.set_paintable(Gdk.Texture.new_from_filename(thumb))
            except GLib.Error:
                pass

    def _say(self, text):
        self.status.set_text(text)
        self.status.set_visible(True)

    def act(self, key, button):
        path = self.path
        if not path or not os.path.exists(path):
            self._say(tr("The file no longer exists."))
            return
        if key == "text":
            button.set_sensitive(False)
            self._say(tr("Reading the text…"))

            def done(res):
                ok, text = res
                button.set_sensitive(True)
                if ok:
                    preview = text if len(text) <= 200 else text[:197].rstrip() + "…"
                    self._say(tr("Text copied to the clipboard:") + "\n" + preview)
                else:
                    self._say(tr("No readable text found."))
            _bg(lambda: capture.ocr_to_clipboard(path), done)
        elif key == "save":
            dest = capture.save_copy(path)
            if dest:
                self.load(dest)
                self._say(tr("Saved to the Screenshots folder."))
            else:
                self._say(tr("Could not save the file."))
        elif key == "delete":
            self.close_card()
            _bg(lambda: capture.trash(path))
        else:
            self.close_card()
            work = {"edit": capture.edit, "folder": capture.show_in_folder,
                    "open": capture.open_file}[key]
            _bg(lambda: work(path))

    def close_card(self):
        self.set_visible(False)
        return False


# ------------------------------------------------------------------ indicator
class Indicator(Gtk.ApplicationWindow):
    """Red dot, elapsed time, Stop. Updated once per second, nothing more."""

    def __init__(self, app):
        super().__init__(application=app, title=tr("Recording"), decorated=False)
        self.add_css_class("zeta-overlay")
        self.layer = bool(LS and LS.is_supported())
        if self.layer:
            LS.init_for_window(self)
            LS.set_namespace(self, "zeta-screenshot-recording")
            LS.set_layer(self, LS.Layer.OVERLAY)
            LS.set_keyboard_mode(self, LS.KeyboardMode.NONE)
            LS.set_exclusive_zone(self, 0)
        pill = Gtk.Box(spacing=10, css_classes=["zs-pill"])
        pill.append(Gtk.Box(css_classes=["zs-dot"], valign=Gtk.Align.CENTER))
        self.time = Gtk.Label(label="00:00", css_classes=["zs-time"], width_chars=7, xalign=0)
        pill.append(self.time)
        self.stop = Gtk.Button(css_classes=["zs-stop"], tooltip_text=tr("Stop recording"))
        inner = Gtk.Box(spacing=6)
        inner.append(Gtk.Image(icon_name="zeta-capture-stop", pixel_size=14))
        self.stop_label = Gtk.Label(label=tr("Stop"))
        inner.append(self.stop_label)
        self.stop.set_child(inner)
        self.stop.connect("clicked", lambda *_: self.stop_now())
        pill.append(self.stop)
        self.set_child(pill)
        self.timer = None
        self.recording = None

    def place(self, st):
        if not self.layer:
            return
        rect = tuple(st["region"]) if st.get("region") else None
        name, corner = capture.pill_corner(rect, st.get("output"), capture.monitor_rects())
        mon = _gdk_monitor(name)
        if mon is not None:
            LS.set_monitor(self, mon)
        top = corner.startswith("top")
        right = corner.endswith("right")
        LS.set_anchor(self, LS.Edge.TOP, top)
        LS.set_anchor(self, LS.Edge.BOTTOM, not top)
        LS.set_anchor(self, LS.Edge.RIGHT, right)
        LS.set_anchor(self, LS.Edge.LEFT, not right)
        for edge in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_margin(self, edge, 12)

    def refresh(self):
        st = capture.recording_state()
        if st is None:
            self._end()
            return
        if self.recording != st.get("file"):
            # a new recording: placed before it is shown (a layer surface
            # cannot move to another screen while it is visible)
            self.set_visible(False)
            self.recording = st.get("file")
            self.stop.set_sensitive(True)
            self.stop_label.set_text(tr("Stop"))
            self.place(st)
        self._tick()
        self.present()
        if self.timer is None:
            self.timer = GLib.timeout_add_seconds(1, self._tick)

    def _tick(self):
        st = capture.recording_state()
        if st is None:
            self._end()
            return False
        self.time.set_text(capture.format_duration(time.time() - st.get("started", time.time())))
        if st.get("stopping"):
            self.stop.set_sensitive(False)
            self.stop_label.set_text(tr("Saving…"))
        return True

    def stop_now(self):
        self.stop.set_sensitive(False)
        self.stop_label.set_text(tr("Saving…"))
        _bg(lambda: capture.stop_recording(wait=True), lambda _r: self.refresh())

    def _end(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        self.recording = None
        self.set_visible(False)


# ------------------------------------------------------------------ application
class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=capture.APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.toolbar = self.card = self.indicator = None

    def _action(self, name, ptype, handler):
        a = Gio.SimpleAction.new(name, GLib.VariantType.new(ptype) if ptype else None)
        a.connect("activate", lambda _a, p: handler(p))
        self.add_action(a)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        popup.clean_env()
        popup.load_css(CSS)
        self._action("show", None, lambda _p: self.toggle_toolbar())
        self._action("card", "s", lambda p: self.show_card(p.get_string()))
        self._action("indicator", None, lambda _p: self.show_indicator())
        self.hold()                   # stays in memory, hidden, after the first use

    def do_command_line(self, cl):
        args = [a.decode(errors="surrogateescape") if isinstance(a, bytes) else str(a)
                for a in cl.get_arguments()[1:]]
        what = args[0] if args else "panel"
        if what == "card" and len(args) > 1:
            self.show_card(os.path.abspath(args[1]))
        elif what == "indicator":
            self.show_indicator()
        else:
            self.toggle_toolbar()
        return 0

    def do_activate(self):
        self.toggle_toolbar()

    def toggle_toolbar(self):
        popup.follow_theme()
        if self.toolbar is not None and self.toolbar.get_visible():
            self.toolbar.set_visible(False)
            return
        if self.toolbar is None:
            self.toolbar = Toolbar(self)
        self.toolbar.prepare()
        self.toolbar.present()

    def show_card(self, path):
        if not path or not os.path.exists(path):
            return
        popup.follow_theme()
        if self.card is None:
            self.card = Card(self)
        self.card.load(path)
        self.card.present()

    def show_indicator(self):
        if self.indicator is None:
            if capture.recording_state() is None:
                return
            self.indicator = Indicator(self)
        self.indicator.refresh()


def main(args):
    """args: ["panel"], ["card", PATH] or ["indicator"]."""
    return App().run(["zeta-screenshot"] + list(args))
