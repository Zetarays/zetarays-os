# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Monitor — mappa del mondo (Cairo, dati Natural Earth 1:110m offline).

Proiezione Natural Earth (Šavrič et al.). Mostra la posizione di rete
dell'utente (IP pubblico) e le destinazioni delle connessioni attive con archi
animati. Nessuna tessera scaricata da Internet: la mappa è locale.
"""
import json
import math
import sys
import time

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, "/usr/lib/zeta")
from i18n import language  # noqa: E402

DATA = "/usr/share/zeta/monitor/world.json"
ISO_CODES = "/usr/share/iso-codes/json/iso_3166-1.json"
LAT_MIN, LAT_MAX = -58.0, 84.0


def project(lon, lat):
    """Natural Earth: (lon, lat in gradi) -> (x, y) non scalati, y verso l'alto."""
    lam = math.radians(lon)
    phi = math.radians(max(-89.9, min(89.9, lat)))
    p2 = phi * phi
    p4 = p2 * p2
    x = lam * (0.8707 - 0.131979 * p2 + p4 * (-0.013791 + p4 * (0.003971 * p2 - 0.001529 * p4)))
    y = phi * (1.007226 + p2 * (0.015085 + p4 * (-0.044475 + 0.028874 * p2 - 0.005916 * p4)))
    return x, y


def _english_names():
    """{ISO alpha-2: English name} from the iso-codes package ({} if missing)."""
    try:
        with open(ISO_CODES) as f:
            return {c["alpha_2"]: c.get("common_name") or c["name"] for c in json.load(f)["3166-1"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _load():
    """Countries of world.json. Its names are Italian: in any other interface
    language they are replaced with the English names (iso-codes)."""
    try:
        with open(DATA) as f:
            countries = json.load(f)["countries"]
    except (OSError, ValueError, KeyError):
        return []
    if language() != "it":
        english = _english_names()
        extra = {"Cipro del Nord": "Northern Cyprus"}      # no ISO code in world.json
        for c in countries:
            c["name"] = english.get(c.get("iso")) or extra.get(c.get("name"), c.get("name"))
    return countries


def country_names():
    """{ISO alpha-2: country name in the interface language}."""
    return {c["iso"]: c["name"] for c in _load() if c.get("iso")}


class WorldMap(Gtk.DrawingArea):
    def __init__(self, accent=(0.23, 0.55, 1.0), height=360, animate=True):
        super().__init__(hexpand=True, vexpand=True)
        self.set_content_height(height)
        self.accent = accent
        self.countries = _load()
        # contorni proiettati una volta sola
        self.shapes = []
        for c in self.countries:
            rings = [[project(lon, lat) for lon, lat in r] for r in c["rings"]]
            self.shapes.append((c["iso"], c["name"], rings))
        self.x0, _ = project(-180, 0)
        self.x1, _ = project(180, 0)
        _, self.y0 = project(0, LAT_MIN)
        _, self.y1 = project(0, LAT_MAX)
        self.me = None                 # {"lat","lon","label"}
        self.points = []               # [{"lat","lon","label","kind"}]
        self.highlight = set()         # ISO dei paesi con connessioni
        self.hover = None
        self._geom = None
        self.t0 = time.monotonic()
        self.set_draw_func(self._draw)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda *_: self._set_hover(None))
        self.add_controller(motion)
        if animate:
            # 80 millisecondi (12 disegni al secondo) erano piu' di quanto
            # l'occhio chieda a una pulsazione lenta, e ridisegnare una mappa
            # vettoriale cosi' spesso e' la ragione per cui il Monitor, aperto
            # su questa scheda, si prendeva una fetta di processore su una
            # macchina modesta. A 5 al secondo l'animazione si vede uguale e
            # costa un terzo. Il disegno avviene comunque solo se la mappa e'
            # davvero in vista (vedi _tick).
            GLib.timeout_add(200, self._tick)

    # ---------- dati ----------
    def set_me(self, lat, lon, label):
        self.me = {"lat": lat, "lon": lon, "label": label} if lat is not None and lon is not None else None
        self.queue_draw()

    def set_points(self, points, countries=()):
        self.points = [p for p in points if p.get("lat") is not None and p.get("lon") is not None]
        self.highlight = set(countries)
        self.queue_draw()

    def _tick(self):
        if self.get_mapped():
            self.queue_draw()
        return True

    # ---------- geometria ----------
    def _fit(self, w, h):
        pad = 10
        sx = (w - 2 * pad) / (self.x1 - self.x0)
        sy = (h - 2 * pad) / (self.y1 - self.y0)
        s = min(sx, sy)
        ox = (w - (self.x1 - self.x0) * s) / 2 - self.x0 * s
        oy = (h - (self.y1 - self.y0) * s) / 2 + self.y1 * s
        self._geom = (s, ox, oy)
        return s, ox, oy

    def to_screen(self, lon, lat):
        s, ox, oy = self._geom
        x, y = project(lon, lat)
        return ox + x * s, oy - y * s

    # ---------- disegno ----------
    def _draw(self, _a, cr, w, h):
        s, ox, oy = self._fit(w, h)
        r, g, b = self.accent
        now = time.monotonic() - self.t0

        # reticolo
        cr.set_line_width(0.6)
        cr.set_source_rgba(1, 1, 1, 0.045)
        for lat in range(-45, 90, 15):
            for lon in range(-180, 181, 5):
                x, y = self.to_screen(lon, lat)
                (cr.move_to if lon == -180 else cr.line_to)(x, y)
            cr.stroke()
        for lon in range(-180, 181, 30):
            for lat in range(int(LAT_MIN), int(LAT_MAX) + 1, 4):
                x, y = self.to_screen(lon, lat)
                (cr.move_to if lat == int(LAT_MIN) else cr.line_to)(x, y)
            cr.stroke()

        # paesi
        for iso, _name, rings in self.shapes:
            hot = iso in self.highlight
            hov = self.hover and self.hover[0] == iso
            for ring in rings:
                for i, (x, y) in enumerate(ring):
                    px, py = ox + x * s, oy - y * s
                    (cr.move_to if i == 0 else cr.line_to)(px, py)
                cr.close_path()
            if hot:
                cr.set_source_rgba(r, g, b, 0.22 if not hov else 0.32)
            else:
                cr.set_source_rgba(1, 1, 1, 0.075 if not hov else 0.12)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.10)
            cr.set_line_width(0.6)
            cr.stroke()

        # archi verso le destinazioni
        if self.me:
            mx, my = self.to_screen(self.me["lon"], self.me["lat"])
            for i, p in enumerate(self.points):
                px, py = self.to_screen(p["lon"], p["lat"])
                d = math.hypot(px - mx, py - my)
                if d < 4:
                    continue
                cx, cy = (mx + px) / 2, (my + py) / 2 - min(120, d * 0.35)
                cr.set_line_width(1.2)
                cr.set_source_rgba(r, g, b, 0.45)
                cr.move_to(mx, my)
                cr.curve_to(cx, cy, cx, cy, px, py)
                cr.stroke()
                # impulso che viaggia lungo l'arco
                t = ((now * 0.35) + i * 0.17) % 1.0
                qx = (1 - t) ** 3 * mx + 3 * (1 - t) ** 2 * t * cx + 3 * (1 - t) * t * t * cx + t ** 3 * px
                qy = (1 - t) ** 3 * my + 3 * (1 - t) ** 2 * t * cy + 3 * (1 - t) * t * t * cy + t ** 3 * py
                cr.set_source_rgba(r, g, b, 0.95)
                cr.arc(qx, qy, 2.2, 0, 2 * math.pi)
                cr.fill()

        # destinazioni
        for p in self.points:
            px, py = self.to_screen(p["lon"], p["lat"])
            cr.set_source_rgba(0.24, 0.86, 0.59, 0.95)
            cr.arc(px, py, 3.2, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.24, 0.86, 0.59, 0.25)
            cr.arc(px, py, 6.5, 0, 2 * math.pi)
            cr.fill()

        # posizione dell'utente (impulso)
        if self.me:
            mx, my = self.to_screen(self.me["lon"], self.me["lat"])
            ph = (now % 2.0) / 2.0
            cr.set_source_rgba(r, g, b, 0.45 * (1 - ph))
            cr.arc(mx, my, 5 + ph * 18, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 1)
            cr.arc(mx, my, 4.2, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(r, g, b, 1)
            cr.arc(mx, my, 3, 0, 2 * math.pi)
            cr.fill()
            self._label(cr, mx + 9, my - 8, self.me["label"], w)

        # etichetta al passaggio del mouse
        if self.hover:
            _iso, name, hx, hy = self.hover
            self._label(cr, hx + 12, hy + 4, name, w)

    def _label(self, cr, x, y, text, w):
        if not text:
            return
        cr.select_font_face("Roboto")
        cr.set_font_size(11.5)
        ext = cr.text_extents(text)
        x = min(x, w - ext.width - 14)
        cr.set_source_rgba(0.07, 0.07, 0.08, 0.92)
        self._rounded(cr, x - 6, y - ext.height - 5, ext.width + 12, ext.height + 10, 6)
        cr.fill()
        cr.set_source_rgba(0.93, 0.93, 0.92, 1)
        cr.move_to(x, y)
        cr.show_text(text)

    @staticmethod
    def _rounded(cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()

    # ---------- interazione ----------
    def _on_motion(self, _c, x, y):
        if not self._geom:
            return
        s, ox, oy = self._geom
        px, py = (x - ox) / s, (oy - y) / s
        found = None
        for iso, name, rings in self.shapes:
            if any(_inside(px, py, ring) for ring in rings):
                found = (iso, name, x, y)
                break
        self._set_hover(found)

    def _set_hover(self, h):
        if (h and self.hover and h[0] == self.hover[0]) and abs(h[2] - self.hover[2]) < 2:
            return
        self.hover = h
        self.queue_draw()


def _inside(x, y, ring):
    """Punto nel poligono (ray casting)."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside
