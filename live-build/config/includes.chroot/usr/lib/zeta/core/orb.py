# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA — sfera-rete (Cairo puro, senza GTK).

Una sfera di nodi collegati da una maglia di linee (plexus) che ruota, con
impulsi luminosi che viaggiano lungo i collegamenti. Colore scelto dall'utente
tra blu, rosso, verde, bianco.

Usato sia dall'app GTK `zeta-core` sia dai test di rendering.
"""
import math
import random

import cairo

N = 220          # nodi sulla sfera
K = 6            # collegamenti per nodo (maglia triangolata)
PERSP = 3.2      # prospettiva lieve (quasi ortografica, come nei riferimenti)
N_PULSE = 46     # impulsi che viaggiano lungo i collegamenti

# palette selezionabile: id -> RGB
# Nessuna tavolozza qui dentro: il colore arriva da chi disegna, e chi disegna
# lo chiede a ui.accento, che è l'unico posto dove vive il colore scelto
# dall'utente. Una seconda tavolozza qui significherebbe due verità diverse
# sullo stesso colore.


def lighten(c, k):
    return tuple(v + (1 - v) * k for v in c)


def _fibonacci_sphere(n, rng):
    pts = []
    ga = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - 2 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1 - y * y))
        a = ga * i
        pts.append((math.cos(a) * r, y, math.sin(a) * r,
                    rng.uniform(0.8, 1.5)))       # dimensione del nodo
    return pts


def _edges(pts, k):
    edges = set()
    n = len(pts)
    for i in range(n):
        xi, yi, zi = pts[i][0], pts[i][1], pts[i][2]
        d = sorted((((xi - pts[j][0]) ** 2 + (yi - pts[j][1]) ** 2
                     + (zi - pts[j][2]) ** 2), j) for j in range(n) if j != i)
        for _, j in d[:k]:
            edges.add((i, j) if i < j else (j, i))
    return list(edges)


def _make_glow(s):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, s, s)
    c = cairo.Context(surf)
    g = cairo.RadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2)
    g.add_color_stop_rgba(0.0, 1, 1, 1, 1.0)
    g.add_color_stop_rgba(0.30, 1, 1, 1, 0.45)
    g.add_color_stop_rgba(1.0, 1, 1, 1, 0.0)
    c.set_source(g)
    c.arc(s / 2, s / 2, s / 2, 0, math.tau)
    c.fill()
    return surf


def _cam(x, y, z, cay, say, cax, sax):
    x, z = x * cay + z * say, -x * say + z * cay
    y, z = y * cax - z * sax, y * sax + z * cax
    return x, y, z


def _spin(state, t):
    if state == "attesa":
        return 0.12, 1.0
    if state == "ascolto":
        return 0.18, 1.4
    if state == "elaborazione":
        return 0.55, 2.4
    if state == "risposta":
        return 0.30, 1.8
    if state == "allerta":
        return 0.9, 3.0
    return 0.15, 1.0


class Orb:
    def __init__(self, seed=7):
        rng = random.Random(seed)
        self.pts = _fibonacci_sphere(N, rng)
        self.edges = _edges(self.pts, K)
        # impulsi: (indice arco, velocità, fase)
        self.pulses = [(rng.randrange(len(self.edges)),
                        rng.uniform(0.25, 0.7), rng.uniform(0, 1))
                       for _ in range(N_PULSE)]
        self.px = [0.0] * N
        self.py = [0.0] * N
        self.pz = [0.0] * N
        self.pd = [0.0] * N
        self.glow = _make_glow(48)
        # classe di grandezza di ogni nodo (per scegliere l'immagine pronta)
        self._size_levels = [min(self.SIZE_LEVELS - 1,
                                 int((p[3] - 0.8) / 0.7 * self.SIZE_LEVELS))
                             for p in self.pts]

    # --- immagini pronte (sprite) ---------------------------------------
    # Disegnare ogni nodo con un arco e ogni alone con una maschera, 60 volte
    # al secondo, teneva occupato quasi mezzo core anche con la finestra
    # ferma. Le forme sono sempre le stesse: si disegnano una volta sola, per
    # ogni livello di profondita', e poi si incollano.
    DEPTH_LEVELS = 12
    SIZE_LEVELS = 4

    def _sprite_cache(self, ctx, color):
        target = ctx.get_target()
        try:
            sx, sy = target.get_device_scale()
        except (AttributeError, cairo.Error):
            sx = sy = 1.0
        key = (color, sx, sy)
        if getattr(self, "_cache_key", None) == key:
            return self._cache
        hi = lighten(color, 0.55)
        cache = {"halo": {}, "core": {}, "pulse": {}}

        def surf(size):
            s = int(math.ceil(size))
            try:
                img = target.create_similar(cairo.CONTENT_COLOR_ALPHA, s, s)
            except cairo.Error:
                img = cairo.ImageSurface(cairo.FORMAT_ARGB32, s, s)
            return img, cairo.Context(img), s

        def blob(rad, col, alpha):
            img, c, s = surf(rad * 2 + 2)
            g = cairo.RadialGradient(s / 2, s / 2, 0, s / 2, s / 2, rad)
            a = min(1.0, alpha)
            g.add_color_stop_rgba(0.0, col[0], col[1], col[2], a)
            g.add_color_stop_rgba(0.30, col[0], col[1], col[2], a * 0.45)
            g.add_color_stop_rgba(1.0, col[0], col[1], col[2], 0.0)
            c.set_source(g)
            c.arc(s / 2, s / 2, rad, 0, math.tau)
            c.fill()
            return img, s / 2

        for dl in range(self.DEPTH_LEVELS):
            d = (dl + 0.5) / self.DEPTH_LEVELS
            for sl in range(self.SIZE_LEVELS):
                base = 0.8 + 0.7 * (sl + 0.5) / self.SIZE_LEVELS
                sz = base * (1.4 + 2.6 * d)
                cache["halo"][dl, sl] = blob(sz * 2.4, color, 0.10 + 0.25 * d)
                col = lighten(color, 0.25 + 0.5 * d)
                img, c, s = surf(sz * 2 + 2)
                c.set_source_rgba(col[0], col[1], col[2], 0.45 + 0.5 * d)
                c.arc(s / 2, s / 2, sz, 0, math.tau)
                c.fill()
                cache["core"][dl, sl] = (img, s / 2)
            cache["pulse"][dl] = blob(4.5 + 3.5 * d, hi, 0.35 + 0.5 * d)
        self._cache_key, self._cache = key, cache
        return cache

    def _paste(self, ctx, sprite, x, y):
        img, half = sprite
        ctx.set_source_surface(img, x - half, y - half)
        ctx.paint()

    def _dl(self, d):
        return min(self.DEPTH_LEVELS - 1, max(0, int(d * self.DEPTH_LEVELS)))

    def draw(self, ctx, w, h, t, color=(0.23, 0.55, 1.0), state="attesa"):
        cx, cy = w / 2, h / 2
        R = min(w, h) * 0.42
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()

        color = tuple(color)
        r, g, b = color
        cache = self._sprite_cache(ctx, color)
        spin, pulse_k = _spin(state, t)

        ay = t * spin
        ax = 0.28 * math.sin(t * 0.22)
        cay, say = math.cos(ay), math.sin(ay)
        cax, sax = math.cos(ax), math.sin(ax)

        # proiezione dei nodi
        px, py, pz, pd = self.px, self.py, self.pz, self.pd
        for i, (x0, y0, z0, _sz) in enumerate(self.pts):
            x, y, z = _cam(x0, y0, z0, cay, say, cax, sax)
            f = PERSP / (PERSP - z)
            px[i] = cx + x * R * f
            py[i] = cy + y * R * f
            pz[i] = z
            pd[i] = (z + 1.0) / 2.0        # 0 dietro .. 1 davanti

        # --- collegamenti: un tracciato per livello di profondita' ---
        # (dietro prima), invece di un tratto per ogni linea
        livelli = [[] for _ in range(8)]
        for i, j in self.edges:
            d = (pd[i] + pd[j]) / 2
            livelli[min(7, int(d * 8))].append((i, j))
        ctx.set_line_width(1.0)
        for lv, archi in enumerate(livelli):
            if not archi:
                continue
            d = (lv + 0.5) / 8
            ctx.set_source_rgba(r, g, b, 0.06 + 0.42 * d)
            for i, j in archi:
                ctx.move_to(px[i], py[i])
                ctx.line_to(px[j], py[j])
            ctx.stroke()

        # --- impulsi che viaggiano lungo i collegamenti ---
        ctx.set_operator(cairo.OPERATOR_ADD)
        for e_idx, sp, ph in self.pulses:
            i, j = self.edges[e_idx]
            u = (t * sp * pulse_k + ph) % 1.0
            d = pd[i] + (pd[j] - pd[i]) * u
            if d < 0.28:
                continue
            self._paste(ctx, cache["pulse"][self._dl(d)],
                        px[i] + (px[j] - px[i]) * u, py[i] + (py[j] - py[i]) * u)

        # --- nodi: aloni (sommati), poi i nuclei dal fondo al davanti ---
        idx = sorted(range(N), key=lambda k: pz[k])
        sl_of = self._size_levels
        for i in idx:
            self._paste(ctx, cache["halo"][self._dl(pd[i]), sl_of[i]], px[i], py[i])
        ctx.set_operator(cairo.OPERATOR_OVER)
        for i in idx:
            self._paste(ctx, cache["core"][self._dl(pd[i]), sl_of[i]], px[i], py[i])
