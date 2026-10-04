# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Monitor — widget riutilizzabili (grafici, tabelle, card)."""
import collections

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


class Sparkline(Gtk.DrawingArea):
    """Grafico a linea con storico scorrevole (Cairo)."""

    def __init__(self, color=(0.23, 0.55, 1.0), maxlen=120, height=70, fill=True):
        super().__init__(hexpand=True)
        self.set_content_height(height)
        self.color = color
        self.fill = fill
        self.data = collections.deque([0.0] * maxlen, maxlen=maxlen)
        self.auto = True          # scala automatica
        self.set_draw_func(self._draw)

    def push(self, v):
        try:
            self.data.append(float(v))
        except (TypeError, ValueError):
            self.data.append(0.0)
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgba(1, 1, 1, 0.02)
        cr.paint()
        data = list(self.data)
        peak = max(data) if self.auto else 100.0
        peak = peak if peak > 1e-6 else 1.0
        n = len(data)
        r, g, b = self.color
        # griglia orizzontale tenue
        cr.set_source_rgba(1, 1, 1, 0.05)
        cr.set_line_width(1)
        for k in range(1, 3):
            y = h * k / 3
            cr.move_to(0, y); cr.line_to(w, y); cr.stroke()
        # linea
        cr.set_line_width(1.6)
        cr.set_source_rgba(r, g, b, 0.9)
        pts = []
        for i, v in enumerate(data):
            x = w * i / max(1, n - 1)
            y = h - (v / peak) * (h - 6) - 3
            pts.append((x, y))
        if pts:
            cr.move_to(*pts[0])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.stroke()
            if self.fill:
                cr.line_to(w, h); cr.line_to(0, h); cr.close_path()
                cr.set_source_rgba(r, g, b, 0.10); cr.fill()


class Bar(Gtk.DrawingArea):
    """Barra di riempimento orizzontale (per CPU per-core, memoria)."""

    def __init__(self, color=(0.23, 0.55, 1.0), height=6):
        super().__init__(hexpand=True)
        self.set_content_height(height)
        self.color = color
        self.value = 0.0
        self.set_draw_func(self._draw)

    def set_value(self, v):
        self.value = max(0.0, min(100.0, float(v)))
        self.queue_draw()

    def _draw(self, _a, cr, w, h):
        cr.set_source_rgba(1, 1, 1, 0.06)
        cr.rectangle(0, 0, w, h); cr.fill()
        r, g, b = self.color
        cr.set_source_rgba(r, g, b, 0.9)
        cr.rectangle(0, 0, w * self.value / 100.0, h); cr.fill()


class Table(Gtk.Box):
    """Tabella leggera: intestazione + righe ricostruite a ogni aggiornamento."""

    def __init__(self, columns, on_select=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.columns = columns          # [(titolo, peso)]
        self.on_select = on_select
        head = Gtk.Box(spacing=0, css_classes=["mono", "thead"])
        for i, (title, weight) in enumerate(columns):
            last = i == len(columns) - 1
            lbl = Gtk.Label(label=title, xalign=0, hexpand=last, css_classes=["col-head"])
            self._size(lbl, weight, last)
            head.append(lbl)
        self.append(head)
        self.listbox = Gtk.ListBox(css_classes=["data-list"])
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE if on_select else Gtk.SelectionMode.NONE)
        if on_select:
            self.listbox.connect("row-selected", self._sel)
        scr = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scr.set_child(self.listbox)
        self.append(scr)
        self._rows = []

    @staticmethod
    def _size(lbl, weight, last):
        # Larghezza in pixel, uguale per intestazione e righe (hanno caratteri di
        # dimensione diversa, quindi una larghezza in "caratteri" non allineerebbe).
        lbl.set_ellipsize(3)            # Pango.EllipsizeMode.END
        if last:
            lbl.set_size_request(max(24, int(weight * 0.84)), -1)
        else:
            lbl.set_size_request(max(24, int(weight * 0.86)), -1)
            lbl.set_max_width_chars(1)  # larghezza naturale minima: resta quella fissata
            lbl.set_margin_end(10)

    def _sel(self, _lb, row):
        if row is not None and self.on_select:
            self.on_select(getattr(row, "key", None))

    def update(self, rows):
        """rows: lista di (chiave, [celle], stile_cella_opzionale)."""
        child = self.listbox.get_first_child()
        while child:
            self.listbox.remove(child)
            child = self.listbox.get_first_child()
        for item in rows:
            key, cells = item[0], item[1]
            styles = item[2] if len(item) > 2 else [None] * len(cells)
            box = Gtk.Box(spacing=0, css_classes=["mono", "trow"])
            for i, ((title, weight), text, style) in enumerate(zip(self.columns, cells, styles)):
                last = i == len(self.columns) - 1
                lbl = Gtk.Label(label=str(text), xalign=0, hexpand=last, ellipsize=3)
                self._size(lbl, weight, last)
                if style:
                    lbl.add_css_class(style)
                box.append(lbl)
            r = Gtk.ListBoxRow(child=box)
            r.key = key
            self.listbox.append(r)


def fmt_rate_short(v):
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if v < 1024 or unit == "GB/s":
            return ("%.0f %s" if v >= 10 or unit == "B/s" else "%.1f %s") % (v, unit)
        v /= 1024


class TrafficChart(Gtk.DrawingArea):
    """Traffico di rete: download e upload sovrapposti, asse con unità e tempo."""

    def __init__(self, accent=(0.23, 0.55, 1.0), up_color=(0.24, 0.86, 0.59), seconds=120, height=220):
        super().__init__(hexpand=True)
        self.set_content_height(height)
        self.seconds = seconds
        self.down = collections.deque([0.0] * seconds, maxlen=seconds)
        self.up = collections.deque([0.0] * seconds, maxlen=seconds)
        self.c_down, self.c_up = accent, up_color
        self.set_draw_func(self._draw)

    def push(self, down, up):
        self.down.append(float(down or 0))
        self.up.append(float(up or 0))
        self.queue_draw()

    def peaks(self):
        return max(self.down), max(self.up)

    def _draw(self, _a, cr, w, h):
        left, right, top, bottom = 64, 8, 8, 22
        cw, ch = w - left - right, h - top - bottom
        peak = max(max(self.down), max(self.up), 1024.0)
        # scala "tonda"
        step = 1
        while step * 4 < peak:
            step *= 2
        ymax = step * 4
        cr.select_font_face("JetBrains Mono")
        cr.set_font_size(10)
        cr.set_line_width(1)
        for k in range(5):
            y = top + ch - ch * k / 4
            cr.set_source_rgba(1, 1, 1, 0.06 if k else 0.12)
            cr.move_to(left, y)
            cr.line_to(left + cw, y)
            cr.stroke()
            cr.set_source_rgba(0.54, 0.54, 0.56, 1)
            txt = fmt_rate_short(ymax * k / 4)
            ext = cr.text_extents(txt)
            cr.move_to(left - 8 - ext.width, y + 3.5)
            cr.show_text(txt)
        for sec in (0, 30, 60, 90, 120):
            if sec > self.seconds:
                continue
            x = left + cw - cw * sec / (self.seconds - 1)
            txt = "ora" if sec == 0 else "-%ds" % sec
            ext = cr.text_extents(txt)
            cr.set_source_rgba(0.54, 0.54, 0.56, 1)
            cr.move_to(min(x - ext.width / 2, left + cw - ext.width), h - 6)
            cr.show_text(txt)
        for data, (r, g, b) in ((self.down, self.c_down), (self.up, self.c_up)):
            vals = list(data)
            n = len(vals)
            pts = [(left + cw * i / (n - 1), top + ch - ch * min(v, ymax) / ymax) for i, v in enumerate(vals)]
            cr.move_to(pts[0][0], top + ch)
            for x, y in pts:
                cr.line_to(x, y)
            cr.line_to(pts[-1][0], top + ch)
            cr.close_path()
            grad = __import__("cairo").LinearGradient(0, top, 0, top + ch)
            grad.add_color_stop_rgba(0, r, g, b, 0.30)
            grad.add_color_stop_rgba(1, r, g, b, 0.02)
            cr.set_source(grad)
            cr.fill()
            cr.set_line_width(1.6)
            cr.set_source_rgba(r, g, b, 0.95)
            for i, (x, y) in enumerate(pts):
                (cr.move_to if i == 0 else cr.line_to)(x, y)
            cr.stroke()
