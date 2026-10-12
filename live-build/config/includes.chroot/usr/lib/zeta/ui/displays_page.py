# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › Displays.

Every connected display: resolution (the native one marked), refresh rate,
scale (only the values Hyprland accepts for that resolution), rotation,
position on a drag-and-drop map, mirror, main display, on/off, brightness of
a built-in panel, details. Nothing changes until «Apply»: then the new
settings are applied, the real state is read back and compared, and a
dialog asks to keep them; without an answer they go back by themselves after
15 seconds. Kept settings are remembered per display (make, model, serial).

The logic is in system/displays.py; this file is only the interface.
"""
import copy
import math
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from system import power, displays  # noqa: E402
from ui import accent  # noqa: E402

CONFIRM_SECONDS = 15
ROTATIONS = (0, 1, 2, 3)      # Hyprland: normal, 90°, 180°, 270°


def _rotation_name(v):
    return tr("Normal") if v == 0 else "%d°" % (v * 90)


def _hz(v):
    return ("%d Hz" % round(v)) if abs(v - round(v)) < 0.02 else ("%.2f Hz" % v)


def _signature(items):
    return [(m["name"], m["enabled"], m["mirror"], m["width"], m["height"],
             round(m["refresh"], 1), m["x"], m["y"], round(m["scale"], 3), m["rotation"])
            for m in items]


class Layout(Gtk.DrawingArea):
    """The display map: proportional, draggable rectangles. When released, a
    display snaps to one side of another (never overlapping, never
    detached)."""

    def __init__(self, page):
        super().__init__(content_height=220, hexpand=True)
        self.page = page
        self.set_draw_func(self._draw)
        self._dragged = None
        self._start = (0, 0)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._drag_begin)
        g.connect("drag-update", self._move)
        g.connect("drag-end", self._drag_end)
        self.add_controller(g)

    # displays shown on the map: on and not mirrored
    def _rectangles(self):
        out = []
        for i, m in enumerate(self.page.displays, 1):
            c = self.page.conf[m["name"]]
            if not c["enabled"] or c["mirror"]:
                continue
            w, h = displays.logical_size(c)
            out.append((m["name"], i, c["x"], c["y"], w, h))
        return out

    def _transform(self, width, height):
        r = self._rectangles()
        if not r:
            return 1.0, 0, 0, r
        x0 = min(a[2] for a in r)
        y0 = min(a[3] for a in r)
        x1 = max(a[2] + a[4] for a in r)
        y1 = max(a[3] + a[5] for a in r)
        margin = 24
        k = min((width - 2 * margin) / max(1, x1 - x0), (height - 2 * margin) / max(1, y1 - y0))
        ox = (width - (x1 - x0) * k) / 2 - x0 * k
        oy = (height - (y1 - y0) * k) / 2 - y0 * k
        return k, ox, oy, r

    def _draw(self, _a, cr, width, height):
        k, ox, oy, r = self._transform(width, height)
        acc = accent.color_rgb()
        dark = Adw.StyleManager.get_default().get_dark()
        for name, number, x, y, w, h in r:
            if self._dragged and self._dragged[0] == name:
                x, y = self._dragged[1], self._dragged[2]
            px, py, pw, ph = ox + x * k + 2, oy + y * k + 2, w * k - 4, h * k - 4
            radius = 8
            cr.new_sub_path()
            cr.arc(px + pw - radius, py + radius, radius, -math.pi / 2, 0)
            cr.arc(px + pw - radius, py + ph - radius, radius, 0, math.pi / 2)
            cr.arc(px + radius, py + ph - radius, radius, math.pi / 2, math.pi)
            cr.arc(px + radius, py + radius, radius, math.pi, 3 * math.pi / 2)
            cr.close_path()
            if dark:
                cr.set_source_rgba(1, 1, 1, 0.07)
            else:
                cr.set_source_rgba(0, 0, 0, 0.06)
            cr.fill_preserve()
            if name == self.page.chosen:
                cr.set_source_rgb(*acc)
                cr.set_line_width(2.5)
            else:
                cr.set_source_rgba(0.55, 0.55, 0.58, 0.6)
                cr.set_line_width(1)
            cr.stroke()
            # big number and connector name
            cr.set_source_rgba(*((0.93, 0.93, 0.92) if dark else (0.11, 0.11, 0.12)), 1)
            cr.select_font_face("Roboto", 0, 0)
            cr.set_font_size(max(14, min(34, ph * 0.32)))
            t = str(number)
            e = cr.text_extents(t)
            cr.move_to(px + pw / 2 - e.width / 2 - e.x_bearing, py + ph / 2 + e.height / 2 - 6)
            cr.show_text(t)
            cr.set_font_size(11)
            cr.set_source_rgba(0.54, 0.54, 0.56, 1)
            e = cr.text_extents(name)
            if e.width < pw - 8:
                cr.move_to(px + pw / 2 - e.width / 2 - e.x_bearing, py + ph - 10)
                cr.show_text(name)
            if name == self.page.primary and len(r) > 1:
                cr.set_source_rgb(*acc)
                cr.arc(px + 12, py + 12, 4, 0, 2 * math.pi)
                cr.fill()

    def _display_at(self, sx, sy):
        k, ox, oy, r = self._transform(self.get_width(), self.get_height())
        for name, _n, x, y, w, h in r:
            if ox + x * k <= sx <= ox + (x + w) * k and oy + y * k <= sy <= oy + (y + h) * k:
                return name, x, y
        return None

    def _drag_begin(self, g, sx, sy):
        s = self._display_at(sx, sy)
        if not s:
            return
        self.page.choose(s[0])
        self._start = (s[1], s[2])
        self._dragged = [s[0], s[1], s[2]]

    def _move(self, g, dx, dy):
        if not self._dragged:
            return
        k, _ox, _oy, _r = self._transform(self.get_width(), self.get_height())
        self._dragged[1] = round(self._start[0] + dx / k)
        self._dragged[2] = round(self._start[1] + dy / k)
        self.queue_draw()

    def _drag_end(self, g, dx, dy):
        if not self._dragged:
            return
        name, x, y = self._dragged
        self._dragged = None
        self.page.place(name, x, y)


class DisplaysPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.displays = []
        self.conf = {}
        self.original = {}
        self.primary = None
        self.main_orig = None
        self.chosen = None
        self._busy = False
        self._watch = None
        self._groups = []
        self.connect("map", lambda *_: self._on_shown())
        self.connect("unmap", lambda *_: self._on_hidden())
        self.reload()

    # ------------------------------------------------------------ state
    def reload(self, keep_chosen=True):
        self.displays = displays.read()
        self.conf = displays.configuration(self.displays)
        self.original = copy.deepcopy(self.conf)
        names = [m["name"] for m in self.displays]
        self.primary = displays.saved_main(self.displays) or (names[0] if names else None)
        self.main_orig = self.primary
        if not (keep_chosen and self.chosen in names):
            active_ids = [m["name"] for m in self.displays if m["focused"]]
            self.chosen = active_ids[0] if active_ids else (names[0] if names else None)
        self._build()

    def is_modified(self):
        return self.conf != self.original or self.primary != self.main_orig

    def _on_shown(self):
        if self._watch is None:
            self._watch = GLib.timeout_add_seconds(2, self._check_connections)

    def _on_hidden(self):
        if self._watch is not None:
            GLib.source_remove(self._watch)
            self._watch = None

    def _check_connections(self):
        """A display was plugged in or unplugged: the page refreshes by itself."""
        if self._busy:
            return True
        new_displays = displays.read()
        before = {m["name"] for m in self.displays}
        after = {m["name"] for m in new_displays}
        if before != after:
            self.reload()
            self._notice(tr("Displays changed: the list is up to date."))
        elif not self.is_modified() and _signature(new_displays) != _signature(self.displays):
            self.reload()
        return True

    # ------------------------------------------------------- construction
    def _build(self):
        for g in self._groups:
            self.remove(g)
        self._groups = []
        self.mapping = None
        if not self.displays:
            g = Adw.PreferencesGroup(title=tr("Displays"),
                                     description=tr("No display information from the desktop."))
            self._add(g)
            return

        more = len(self.displays) > 1
        header = Adw.PreferencesGroup(
            title=tr("Arrangement") if more else tr("Display"),
            description=(tr("Drag the displays to match how they sit on your desk. "
                            "Changes take effect when you press Apply.") if more else
                         tr("Changes take effect when you press Apply.")))
        if more:
            self.mapping = Layout(self)
            frame = Gtk.Frame(child=self.mapping, margin_bottom=6)
            header.add(frame)
            mode = Adw.ComboRow(title=tr("Use the displays"))
            entries = [tr("Join Displays"), tr("Mirror")]
            for i, m in enumerate(self.displays, 1):
                entries.append(tr("Only {name}").format(name="%d · %s" % (i, m["identity"])))
            mode.set_model(Gtk.StringList.new(entries))
            mode.set_selected(self._current_mode())
            mode.connect("notify::selected", lambda c, _p: None if getattr(self, "_updating_mode", False)
                         else self._change_mode(c.get_selected()))
            header.add(mode)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=10)
        ident = Gtk.Button(label=tr("Identify Displays"))
        ident.connect("clicked", lambda *_: subprocess.Popen(
            ["zeta-displays", "identify"], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        buttons.append(ident)
        self.cancel = Gtk.Button(label=tr("Undo Changes"), sensitive=self.is_modified())
        self.cancel.connect("clicked", lambda *_: self._cancel())
        buttons.append(self.cancel)
        self.apply_button = Gtk.Button(label=tr("Apply"), css_classes=["suggested-action"],
                                          sensitive=self.is_modified())
        self.apply_button.connect("clicked", lambda *_: self._apply())
        buttons.append(self.apply_button)
        header.add(buttons)
        self._add(header)

        self.mode = mode if more else None
        self._detail = None
        self._redraw_detail()

    def _redraw_detail(self):
        """Only the selected display's panel, the buttons and the map: the map
        stays the same widget (recreating it interrupted dragging)."""
        if self._detail is not None:
            self.remove(self._detail)
            self._groups.remove(self._detail)
        m = next((x for x in self.displays if x["name"] == self.chosen), self.displays[0])
        self._detail = self._screen_group(m)
        self._add(self._detail)
        self.cancel.set_sensitive(self.is_modified())
        self.apply_button.set_sensitive(self.is_modified() and not self._busy)
        if self.mode is not None and self.mode.get_selected() != self._current_mode():
            self._updating_mode = True
            self.mode.set_selected(self._current_mode())
            self._updating_mode = False
        if getattr(self, "mapping", None) is not None:
            self.mapping.queue_draw()

    def _add(self, g):
        self.add(g)
        self._groups.append(g)

    def _number(self, name):
        for i, m in enumerate(self.displays, 1):
            if m["name"] == name:
                return i
        return 0

    def _screen_group(self, m):
        c = self.conf[m["name"]]
        n = self._number(m["name"])
        more = len(self.displays) > 1
        g = Adw.PreferencesGroup(title=("%d · %s" % (n, m["identity"])) if more else m["identity"],
                                 description=m["name"] if m["identity"] != m["name"] else None)

        if more:
            enabled_outputs = [x for x, v in self.conf.items() if v["enabled"] and not v["mirror"]]
            use = Adw.SwitchRow(title=tr("Use This Display"), active=c["enabled"])
            use.set_sensitive(not (c["enabled"] and not c["mirror"] and len(enabled_outputs) == 1))
            use.connect("notify::active", lambda r, _p: self._change(m["name"], enabled=r.get_active()))
            g.add(use)
            main_row = Adw.SwitchRow(title=tr("Main Display"),
                                  subtitle=tr("The first workspace opens here"),
                                  active=self.primary == m["name"],
                                  sensitive=c["enabled"] and not c["mirror"])
            main_row.connect("notify::active", lambda r, _p: self._set_main(m["name"], r.get_active()))
            g.add(main_row)
            if c["mirror"]:
                g.add(Adw.ActionRow(title=tr("Mirroring"),
                                    subtitle=tr("Shows the same picture as display {n}").format(
                                        n=self._number(c["mirror"]))))
        if not c["enabled"] or c["mirror"]:
            g.add(self._details(m))
            return g

        # resolution (the native one marked)
        res_list = displays.resolutions(m)
        native_resolution = displays.native_resolution(m)
        current = (c["width"], c["height"])
        if current not in res_list:
            res_list.append(current)
        labels = []
        for w, h in res_list:
            t = "%d × %d" % (w, h)
            if (w, h) == native_resolution:
                t += "  · " + tr("Native")
            labels.append(t)
        resolution_row = Adw.ComboRow(title=tr("Resolution"), model=Gtk.StringList.new(labels))
        resolution_row.set_selected(res_list.index(current))
        resolution_row.connect("notify::selected", lambda r, _p: self._resolution(m, res_list[r.get_selected()]))
        g.add(resolution_row)

        # refresh rate
        freq = displays.refresh_rates(m, *current) or [c["refresh"]]
        if all(abs(f - c["refresh"]) > 0.05 for f in freq):
            freq.append(c["refresh"])
        r_hz = Adw.ComboRow(title=tr("Refresh Rate"), model=Gtk.StringList.new([_hz(f) for f in freq]))
        r_hz.set_selected(min(range(len(freq)), key=lambda i: abs(freq[i] - c["refresh"])))
        r_hz.set_sensitive(len(freq) > 1)
        r_hz.connect("notify::selected", lambda r, _p: self._change(m["name"], refresh=freq[r.get_selected()]))
        g.add(r_hz)

        # scale: only values that divide the resolution exactly
        sc = displays.valid_scales(c["width"], c["height"], c["scale"])
        r_sc = Adw.ComboRow(title=tr("Scale"),
                            subtitle=tr("Size of text, windows and the bar"),
                            model=Gtk.StringList.new(["%d%%" % round(s * 100) for s in sc]))
        r_sc.set_selected(min(range(len(sc)), key=lambda i: abs(sc[i] - c["scale"])))
        r_sc.connect("notify::selected", lambda r, _p: self._change(m["name"], scale=sc[r.get_selected()]))
        g.add(r_sc)

        # rotation
        r_rot = Adw.ComboRow(title=tr("Orientation"),
                             model=Gtk.StringList.new([_rotation_name(v) for v in ROTATIONS]))
        r_rot.set_selected(ROTATIONS.index(c["rotation"]) if c["rotation"] in ROTATIONS else 0)
        r_rot.connect("notify::selected",
                      lambda r, _p: self._change(m["name"], rotation=ROTATIONS[r.get_selected()]))
        g.add(r_rot)

        # brightness: only a laptop's built-in panel
        if m["internal"]:
            percent, _dev = power.backlight()
            if percent is not None:
                line = Adw.ActionRow(title=tr("Brightness"))
                slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 5)
                slider.set_value(percent)
                slider.set_hexpand(True)
                slider.set_size_request(220, -1)
                slider.connect("value-changed", lambda s: power.set_backlight(s.get_value()))
                line.add_suffix(slider)
                g.add(line)

        g.add(self._details(m))
        return g

    def _details(self, m):
        e = Adw.ExpanderRow(title=tr("Details"))

        def line(t, v):
            r = Adw.ActionRow(title=t, subtitle=v or "—", subtitle_selectable=True)
            e.add_row(r)
        line(tr("Connector"), m["name"])
        line(tr("Manufacturer"), m["make"])
        line(tr("Model"), m["model"])
        line(tr("Serial Number"), m["serial"])
        p = displays.inches(m)
        line(tr("Physical Size"), ("%d × %d mm · %s\"" % (m["mm"][0], m["mm"][1], p)) if p else None)
        line(tr("Current Mode"), "%d × %d · %s" % (m["width"], m["height"], _hz(m["refresh"])))
        lw, lh = displays.logical_size(self.conf[m["name"]])
        line(tr("Desktop Area"), "%d × %d" % (lw, lh))
        line(tr("Position"), "%d, %d" % (m["x"], m["y"]))
        line(tr("Variable Refresh Rate"), tr("On") if m["vrr"] else tr("Off"))
        return e

    # ------------------------------------------------------------ changes
    def choose(self, name):
        if name != self.chosen:
            self.chosen = name
            self._redraw_detail()

    def _change(self, name, **values):
        self.conf[name].update(values)
        if values.get("enabled") is False and self.primary == name:
            others = [n for n, c in self.conf.items() if c["enabled"] and not c["mirror"]]
            self.primary = others[0] if others else self.primary
        if values.get("enabled") is True and self.conf[name]["mirror"] is None:
            self._place_beside(name)
        if "scale" in values or "rotation" in values:
            self._compact()
        GLib.idle_add(self._after_change)

    def _after_change(self):
        self._redraw_detail()
        return False

    def _resolution(self, m, wh):
        freq = displays.refresh_rates(m, *wh)
        self._change(m["name"], width=wh[0], height=wh[1],
                     refresh=freq[0] if freq else self.conf[m["name"]]["refresh"])
        self._compact()

    def _set_main(self, name, active):
        # there is always a main display: switching off the current one's
        # toggle does nothing (you choose by turning it on for another one)
        if active:
            self.primary = name
        GLib.idle_add(self._after_change)

    def _current_mode(self):
        enabled_outputs = [n for n, c in self.conf.items() if c["enabled"]]
        if len(enabled_outputs) == 1:
            return 2 + [m["name"] for m in self.displays].index(enabled_outputs[0])
        if any(c["mirror"] for c in self.conf.values()):
            return 1
        return 0

    def _change_mode(self, i):
        if i == self._current_mode():
            return
        names = [m["name"] for m in self.displays]
        source = self.primary if self.primary in names else names[0]
        if i == 0:                               # joined, side by side
            for n in names:
                self.conf[n].update(enabled=True, mirror=None)
            x = 0
            for n in [source] + [n for n in names if n != source]:
                c = self.conf[n]
                c.update(x=x, y=0)
                x += displays.logical_size(c)[0]
        elif i == 1:                             # all mirror the main one
            for n in names:
                self.conf[n].update(enabled=True, mirror=None if n == source else source)
        else:                                    # only one
            only_one = names[i - 2]
            for n in names:
                self.conf[n].update(enabled=(n == only_one), mirror=None)
            self.primary = only_one
            self.chosen = only_one
        GLib.idle_add(self._after_change)

    def _cancel(self):
        self.conf = copy.deepcopy(self.original)
        self.primary = self.main_orig
        self._redraw_detail()

    # -------------------------------------------------- arrangement
    def _rect(self, name, x=None, y=None):
        c = self.conf[name]
        w, h = displays.logical_size(c)
        return (c["x"] if x is None else x, c["y"] if y is None else y, w, h)

    def place(self, name, x, y):
        """Leave the display where it was dropped, snapped to the nearest side
        of another display, without overlaps."""
        others = [n for n, c in self.conf.items() if n != name and c["enabled"] and not c["mirror"]]
        if not others:
            return
        _x, _y, w, h = self._rect(name)
        candidates = []
        for o in others:
            ox, oy, ow, oh = self._rect(o)
            def nearby(v, a, b):
                v = max(a, min(v, b))
                return v
            ty = nearby(y, oy - h + 40, oy + oh - 40)
            tx = nearby(x, ox - w + 40, ox + ow - 40)
            for cx, cy in ((ox + ow, ty), (ox - w, ty), (tx, oy + oh), (tx, oy - h)):
                # align the edges if it is nearly aligned
                if abs(cy - oy) < oh * 0.08:
                    cy = oy
                if abs((cy + h) - (oy + oh)) < oh * 0.08:
                    cy = oy + oh - h
                if abs(cx - ox) < ow * 0.08:
                    cx = ox
                if abs((cx + w) - (ox + ow)) < ow * 0.08:
                    cx = ox + ow - w
                candidates.append((cx, cy))
        def overlaps(cx, cy):
            for o in others:
                ox, oy, ow, oh = self._rect(o)
                if cx < ox + ow and cx + w > ox and cy < oy + oh and cy + h > oy:
                    return True
            return False
        good = [p for p in candidates if not overlaps(*p)]
        if not good:
            GLib.idle_add(self._after_change)
            return
        bx, by = min(good, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
        self.conf[name].update(x=int(bx), y=int(by))
        self._normalize()
        GLib.idle_add(self._after_change)

    def _place_beside(self, name):
        """A display turned back on goes to the right of the others."""
        others = [n for n, c in self.conf.items() if n != name and c["enabled"] and not c["mirror"]]
        if others:
            right_edge = max(self._rect(o)[0] + self._rect(o)[2] for o in others)
            self.conf[name].update(x=right_edge, y=min(self._rect(o)[1] for o in others))

    def _compact(self):
        """After a size change (scale, rotation, resolution) side-by-side
        displays are moved back together: no gaps and no overlaps."""
        enabled_outputs = sorted((n for n, c in self.conf.items() if c["enabled"] and not c["mirror"]),
                        key=lambda n: (self.conf[n]["x"], self.conf[n]["y"]))
        if len(enabled_outputs) < 2:
            if enabled_outputs:
                self.conf[enabled_outputs[0]].update(x=0, y=0)
            return
        # laid out in a row (the common case): put them back one after another
        in_row = len({self.conf[n]["y"] for n in enabled_outputs}) == 1
        if in_row:
            x = self.conf[enabled_outputs[0]]["x"]
            for n in enabled_outputs:
                self.conf[n]["x"] = x
                x += self._rect(n)[2]
        self._normalize()

    def _normalize(self):
        enabled_outputs = [n for n, c in self.conf.items() if c["enabled"] and not c["mirror"]]
        if not enabled_outputs:
            return
        mx = min(self.conf[n]["x"] for n in enabled_outputs)
        my = min(self.conf[n]["y"] for n in enabled_outputs)
        for n in enabled_outputs:
            self.conf[n]["x"] -= mx
            self.conf[n]["y"] -= my

    # --------------------------------------------------------- applying
    def _apply(self):
        if self._busy or not self.is_modified():
            return
        error = displays.check(self.conf)
        if error:
            self._notice(tr("At least one display must stay on and show its own picture."))
            return
        self._busy = True
        self.apply_button.set_sensitive(False)
        before, main_before = copy.deepcopy(self.original), self.main_orig
        new, main_row = copy.deepcopy(self.conf), self.primary

        def job():
            ok, msg = displays.apply(new, main_row)
            ok_v, diff = displays.verify(new) if ok else (False, [msg])
            GLib.idle_add(self._applied, ok and ok_v, diff, before, main_before, new, main_row)
        threading.Thread(target=job, daemon=True).start()

    def _applied(self, ok, diff, before, main_before, new, main_row):
        if not ok:
            # the display did not take the settings: revert right away
            self._restore(before, main_before,
                             tr("The display didn't accept these settings. The previous ones are back."))
            return False
        self._ask_confirmation(before, main_before, new, main_row)
        return False

    def _ask_confirmation(self, before, main_before, new, main_row):
        remaining = [CONFIRM_SECONDS]
        d = Adw.AlertDialog(heading=tr("Keep These Display Settings?"),
                            body=self._countdown_text(remaining[0]))
        d.add_response("revert", tr("Revert"))
        d.add_response("keep", tr("Keep Changes"))
        d.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("revert")
        d.set_close_response("revert")
        done = [False]

        def answer(_d, r):
            if done[0]:
                return
            done[0] = True
            if r == "keep":
                try:
                    displays.save(new, main_row)
                    self._notice(tr("Display settings saved."))
                except OSError as e:
                    self._notice(str(e))
                self._busy = False
                self.reload()
            else:
                self._restore(before, main_before, tr("Previous display settings restored."))

        def tick():
            if done[0]:
                return False
            remaining[0] -= 1
            if remaining[0] <= 0:
                d.close()
                answer(d, "revert")
                return False
            d.set_body(self._countdown_text(remaining[0]))
            return True
        d.connect("response", answer)
        d.present(self.get_root())
        GLib.timeout_add_seconds(1, tick)

    def _countdown_text(self, n):
        return tr("The previous settings come back in {n} seconds unless you keep these.").format(n=n)

    def _restore(self, before, main_before, message):
        def job():
            displays.apply(before, main_before)
            displays.verify(before)
            GLib.idle_add(finish)

        def finish():
            self._busy = False
            self.reload()
            self._notice(message)
            return False
        threading.Thread(target=job, daemon=True).start()

    def _notice(self, text):
        toasts = getattr(self.get_root(), "toasts", None)
        if toasts is not None:
            toasts.add_toast(Adw.Toast(title=text, timeout=4, use_markup=False))
