# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › Displays.

Every connected display: resolution (the native one marked), refresh rate,
scale (only the values Hyprland accepts for that resolution), rotation,
position on a drag-and-drop map, mirror, main display, on/off, brightness of
a built-in panel, details. Nothing changes until «Apply»: then the new
settings are applied, the real state is read back and compared, and a
dialog asks to keep them; without an answer they go back by themselves after
15 seconds. Kept settings are remembered per display (make, model, serial).

The logic is in system/schermi.py; this file is only the interface.
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
from system import power, schermi  # noqa: E402
from ui import accento  # noqa: E402

SECONDI_CONFERMA = 15
ROTAZIONI = (0, 1, 2, 3)      # Hyprland: normale, 90°, 180°, 270°


def _nome_rotazione(v):
    return tr("Normal") if v == 0 else "%d°" % (v * 90)


def _hz(v):
    return ("%d Hz" % round(v)) if abs(v - round(v)) < 0.02 else ("%.2f Hz" % v)


def _firma(lista):
    return [(m["nome"], m["acceso"], m["specchio"], m["larghezza"], m["altezza"],
             round(m["frequenza"], 1), m["x"], m["y"], round(m["scala"], 3), m["rotazione"])
            for m in lista]


class Disposizione(Gtk.DrawingArea):
    """La mappa degli schermi: rettangoli in proporzione, trascinabili.
    Lasciato andare, uno schermo si aggancia a un lato di un altro (mai
    sovrapposti, mai staccati)."""

    def __init__(self, pagina):
        super().__init__(content_height=220, hexpand=True)
        self.pagina = pagina
        self.set_draw_func(self._disegna)
        self._trascinato = None
        self._inizio = (0, 0)
        g = Gtk.GestureDrag()
        g.connect("drag-begin", self._via)
        g.connect("drag-update", self._muovi)
        g.connect("drag-end", self._fine)
        self.add_controller(g)

    # schermi visibili sulla mappa: accesi e non in specchio
    def _rettangoli(self):
        out = []
        for i, m in enumerate(self.pagina.schermi, 1):
            c = self.pagina.conf[m["nome"]]
            if not c["acceso"] or c["specchio"]:
                continue
            w, h = schermi.dimensione_logica(c)
            out.append((m["nome"], i, c["x"], c["y"], w, h))
        return out

    def _trasforma(self, larg, alt):
        r = self._rettangoli()
        if not r:
            return 1.0, 0, 0, r
        x0 = min(a[2] for a in r)
        y0 = min(a[3] for a in r)
        x1 = max(a[2] + a[4] for a in r)
        y1 = max(a[3] + a[5] for a in r)
        margine = 24
        k = min((larg - 2 * margine) / max(1, x1 - x0), (alt - 2 * margine) / max(1, y1 - y0))
        ox = (larg - (x1 - x0) * k) / 2 - x0 * k
        oy = (alt - (y1 - y0) * k) / 2 - y0 * k
        return k, ox, oy, r

    def _disegna(self, _a, cr, larg, alt):
        k, ox, oy, r = self._trasforma(larg, alt)
        acc = accento.colore_rgb()
        scuro = Adw.StyleManager.get_default().get_dark()
        for nome, numero, x, y, w, h in r:
            if self._trascinato and self._trascinato[0] == nome:
                x, y = self._trascinato[1], self._trascinato[2]
            px, py, pw, ph = ox + x * k + 2, oy + y * k + 2, w * k - 4, h * k - 4
            raggio = 8
            cr.new_sub_path()
            cr.arc(px + pw - raggio, py + raggio, raggio, -math.pi / 2, 0)
            cr.arc(px + pw - raggio, py + ph - raggio, raggio, 0, math.pi / 2)
            cr.arc(px + raggio, py + ph - raggio, raggio, math.pi / 2, math.pi)
            cr.arc(px + raggio, py + raggio, raggio, math.pi, 3 * math.pi / 2)
            cr.close_path()
            if scuro:
                cr.set_source_rgba(1, 1, 1, 0.07)
            else:
                cr.set_source_rgba(0, 0, 0, 0.06)
            cr.fill_preserve()
            if nome == self.pagina.scelto:
                cr.set_source_rgb(*acc)
                cr.set_line_width(2.5)
            else:
                cr.set_source_rgba(0.55, 0.55, 0.58, 0.6)
                cr.set_line_width(1)
            cr.stroke()
            # numero grande e nome della presa
            cr.set_source_rgba(*((0.93, 0.93, 0.92) if scuro else (0.11, 0.11, 0.12)), 1)
            cr.select_font_face("Roboto", 0, 0)
            cr.set_font_size(max(14, min(34, ph * 0.32)))
            t = str(numero)
            e = cr.text_extents(t)
            cr.move_to(px + pw / 2 - e.width / 2 - e.x_bearing, py + ph / 2 + e.height / 2 - 6)
            cr.show_text(t)
            cr.set_font_size(11)
            cr.set_source_rgba(0.54, 0.54, 0.56, 1)
            e = cr.text_extents(nome)
            if e.width < pw - 8:
                cr.move_to(px + pw / 2 - e.width / 2 - e.x_bearing, py + ph - 10)
                cr.show_text(nome)
            if nome == self.pagina.principale and len(r) > 1:
                cr.set_source_rgb(*acc)
                cr.arc(px + 12, py + 12, 4, 0, 2 * math.pi)
                cr.fill()

    def _sotto(self, sx, sy):
        k, ox, oy, r = self._trasforma(self.get_width(), self.get_height())
        for nome, _n, x, y, w, h in r:
            if ox + x * k <= sx <= ox + (x + w) * k and oy + y * k <= sy <= oy + (y + h) * k:
                return nome, x, y
        return None

    def _via(self, g, sx, sy):
        s = self._sotto(sx, sy)
        if not s:
            return
        self.pagina.scegli(s[0])
        self._inizio = (s[1], s[2])
        self._trascinato = [s[0], s[1], s[2]]

    def _muovi(self, g, dx, dy):
        if not self._trascinato:
            return
        k, _ox, _oy, _r = self._trasforma(self.get_width(), self.get_height())
        self._trascinato[1] = round(self._inizio[0] + dx / k)
        self._trascinato[2] = round(self._inizio[1] + dy / k)
        self.queue_draw()

    def _fine(self, g, dx, dy):
        if not self._trascinato:
            return
        nome, x, y = self._trascinato
        self._trascinato = None
        self.pagina.posiziona(nome, x, y)


class SchermiPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.schermi = []
        self.conf = {}
        self.originale = {}
        self.principale = None
        self.principale_orig = None
        self.scelto = None
        self._occupato = False
        self._sorveglia = None
        self._gruppi = []
        self.connect("map", lambda *_: self._mostrata())
        self.connect("unmap", lambda *_: self._nascosta())
        self.ricarica()

    # ------------------------------------------------------------ stato
    def ricarica(self, mantieni_scelto=True):
        self.schermi = schermi.leggi()
        self.conf = schermi.configurazione(self.schermi)
        self.originale = copy.deepcopy(self.conf)
        nomi = [m["nome"] for m in self.schermi]
        self.principale = schermi.principale_salvato(self.schermi) or (nomi[0] if nomi else None)
        self.principale_orig = self.principale
        if not (mantieni_scelto and self.scelto in nomi):
            attivi = [m["nome"] for m in self.schermi if m["fuoco"]]
            self.scelto = attivi[0] if attivi else (nomi[0] if nomi else None)
        self._costruisci()

    def modificato(self):
        return self.conf != self.originale or self.principale != self.principale_orig

    def _mostrata(self):
        if self._sorveglia is None:
            self._sorveglia = GLib.timeout_add_seconds(2, self._controlla_collegamenti)

    def _nascosta(self):
        if self._sorveglia is not None:
            GLib.source_remove(self._sorveglia)
            self._sorveglia = None

    def _controlla_collegamenti(self):
        """Uno schermo collegato o staccato: la pagina si aggiorna da sola."""
        if self._occupato:
            return True
        nuovi = schermi.leggi()
        prima = {m["nome"] for m in self.schermi}
        dopo = {m["nome"] for m in nuovi}
        if prima != dopo:
            self.ricarica()
            self._avviso(tr("Displays changed: the list is up to date."))
        elif not self.modificato() and _firma(nuovi) != _firma(self.schermi):
            self.ricarica()
        return True

    # ------------------------------------------------------- costruzione
    def _costruisci(self):
        for g in self._gruppi:
            self.remove(g)
        self._gruppi = []
        self.mappa = None
        if not self.schermi:
            g = Adw.PreferencesGroup(title=tr("Displays"),
                                     description=tr("No display information from the desktop."))
            self._aggiungi(g)
            return

        piu = len(self.schermi) > 1
        testa = Adw.PreferencesGroup(
            title=tr("Arrangement") if piu else tr("Display"),
            description=(tr("Drag the displays to match how they sit on your desk. "
                            "Changes take effect when you press Apply.") if piu else
                         tr("Changes take effect when you press Apply.")))
        if piu:
            self.mappa = Disposizione(self)
            cornice = Gtk.Frame(child=self.mappa, margin_bottom=6)
            testa.add(cornice)
            modo = Adw.ComboRow(title=tr("Use the displays"))
            voci = [tr("Join Displays"), tr("Mirror")]
            for i, m in enumerate(self.schermi, 1):
                voci.append(tr("Only {name}").format(name="%d · %s" % (i, m["identita"])))
            modo.set_model(Gtk.StringList.new(voci))
            modo.set_selected(self._modo_attuale())
            modo.connect("notify::selected", lambda c, _p: None if getattr(self, "_aggiorno_modo", False)
                         else self._cambia_modo(c.get_selected()))
            testa.add(modo)
        bottoni = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=10)
        ident = Gtk.Button(label=tr("Identify Displays"))
        ident.connect("clicked", lambda *_: subprocess.Popen(
            ["zeta-schermi", "identifica"], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        bottoni.append(ident)
        self.annulla = Gtk.Button(label=tr("Undo Changes"), sensitive=self.modificato())
        self.annulla.connect("clicked", lambda *_: self._annulla())
        bottoni.append(self.annulla)
        self.bottone_applica = Gtk.Button(label=tr("Apply"), css_classes=["suggested-action"],
                                          sensitive=self.modificato())
        self.bottone_applica.connect("clicked", lambda *_: self._applica())
        bottoni.append(self.bottone_applica)
        testa.add(bottoni)
        self._aggiungi(testa)

        self.modo = modo if piu else None
        self._dettaglio = None
        self._ridisegna_dettaglio()

    def _ridisegna_dettaglio(self):
        """Solo il riquadro dello schermo scelto, i pulsanti e la mappa: la
        mappa resta la stessa (ricrearla interrompeva il trascinamento)."""
        if self._dettaglio is not None:
            self.remove(self._dettaglio)
            self._gruppi.remove(self._dettaglio)
        m = next((x for x in self.schermi if x["nome"] == self.scelto), self.schermi[0])
        self._dettaglio = self._gruppo_schermo(m)
        self._aggiungi(self._dettaglio)
        self.annulla.set_sensitive(self.modificato())
        self.bottone_applica.set_sensitive(self.modificato() and not self._occupato)
        if self.modo is not None and self.modo.get_selected() != self._modo_attuale():
            self._aggiorno_modo = True
            self.modo.set_selected(self._modo_attuale())
            self._aggiorno_modo = False
        if getattr(self, "mappa", None) is not None:
            self.mappa.queue_draw()

    def _aggiungi(self, g):
        self.add(g)
        self._gruppi.append(g)

    def _numero(self, nome):
        for i, m in enumerate(self.schermi, 1):
            if m["nome"] == nome:
                return i
        return 0

    def _gruppo_schermo(self, m):
        c = self.conf[m["nome"]]
        n = self._numero(m["nome"])
        piu = len(self.schermi) > 1
        g = Adw.PreferencesGroup(title=("%d · %s" % (n, m["identita"])) if piu else m["identita"],
                                 description=m["nome"] if m["identita"] != m["nome"] else None)

        if piu:
            accesi = [x for x, v in self.conf.items() if v["acceso"] and not v["specchio"]]
            usa = Adw.SwitchRow(title=tr("Use This Display"), active=c["acceso"])
            usa.set_sensitive(not (c["acceso"] and not c["specchio"] and len(accesi) == 1))
            usa.connect("notify::active", lambda r, _p: self._cambia(m["nome"], acceso=r.get_active()))
            g.add(usa)
            princ = Adw.SwitchRow(title=tr("Main Display"),
                                  subtitle=tr("The first workspace opens here"),
                                  active=self.principale == m["nome"],
                                  sensitive=c["acceso"] and not c["specchio"])
            princ.connect("notify::active", lambda r, _p: self._principale(m["nome"], r.get_active()))
            g.add(princ)
            if c["specchio"]:
                g.add(Adw.ActionRow(title=tr("Mirroring"),
                                    subtitle=tr("Shows the same picture as display {n}").format(
                                        n=self._numero(c["specchio"]))))
        if not c["acceso"] or c["specchio"]:
            g.add(self._dettagli(m))
            return g

        # risoluzione (la nativa segnata)
        ris = schermi.risoluzioni(m)
        nativa = schermi.nativa(m)
        attuale = (c["larghezza"], c["altezza"])
        if attuale not in ris:
            ris.append(attuale)
        etichette = []
        for w, h in ris:
            t = "%d × %d" % (w, h)
            if (w, h) == nativa:
                t += "  · " + tr("Native")
            etichette.append(t)
        r_ris = Adw.ComboRow(title=tr("Resolution"), model=Gtk.StringList.new(etichette))
        r_ris.set_selected(ris.index(attuale))
        r_ris.connect("notify::selected", lambda r, _p: self._risoluzione(m, ris[r.get_selected()]))
        g.add(r_ris)

        # frequenza
        freq = schermi.frequenze(m, *attuale) or [c["frequenza"]]
        if all(abs(f - c["frequenza"]) > 0.05 for f in freq):
            freq.append(c["frequenza"])
        r_hz = Adw.ComboRow(title=tr("Refresh Rate"), model=Gtk.StringList.new([_hz(f) for f in freq]))
        r_hz.set_selected(min(range(len(freq)), key=lambda i: abs(freq[i] - c["frequenza"])))
        r_hz.set_sensitive(len(freq) > 1)
        r_hz.connect("notify::selected", lambda r, _p: self._cambia(m["nome"], frequenza=freq[r.get_selected()]))
        g.add(r_hz)

        # scala: solo i valori che dividono esattamente la risoluzione
        sc = schermi.scale_valide(c["larghezza"], c["altezza"], c["scala"])
        r_sc = Adw.ComboRow(title=tr("Scale"),
                            subtitle=tr("Size of text, windows and the bar"),
                            model=Gtk.StringList.new(["%d%%" % round(s * 100) for s in sc]))
        r_sc.set_selected(min(range(len(sc)), key=lambda i: abs(sc[i] - c["scala"])))
        r_sc.connect("notify::selected", lambda r, _p: self._cambia(m["nome"], scala=sc[r.get_selected()]))
        g.add(r_sc)

        # rotazione
        r_rot = Adw.ComboRow(title=tr("Orientation"),
                             model=Gtk.StringList.new([_nome_rotazione(v) for v in ROTAZIONI]))
        r_rot.set_selected(ROTAZIONI.index(c["rotazione"]) if c["rotazione"] in ROTAZIONI else 0)
        r_rot.connect("notify::selected",
                      lambda r, _p: self._cambia(m["nome"], rotazione=ROTAZIONI[r.get_selected()]))
        g.add(r_rot)

        # luminosita': solo lo schermo interno di un portatile
        if m["interno"]:
            perc, _dev = power.backlight()
            if perc is not None:
                riga = Adw.ActionRow(title=tr("Brightness"))
                barra = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 5)
                barra.set_value(perc)
                barra.set_hexpand(True)
                barra.set_size_request(220, -1)
                barra.connect("value-changed", lambda s: power.set_backlight(s.get_value()))
                riga.add_suffix(barra)
                g.add(riga)

        g.add(self._dettagli(m))
        return g

    def _dettagli(self, m):
        e = Adw.ExpanderRow(title=tr("Details"))

        def riga(t, v):
            r = Adw.ActionRow(title=t, subtitle=v or "—", subtitle_selectable=True)
            e.add_row(r)
        riga(tr("Connector"), m["nome"])
        riga(tr("Manufacturer"), m["marca"])
        riga(tr("Model"), m["modello"])
        riga(tr("Serial Number"), m["seriale"])
        p = schermi.pollici(m)
        riga(tr("Physical Size"), ("%d × %d mm · %s\"" % (m["mm"][0], m["mm"][1], p)) if p else None)
        riga(tr("Current Mode"), "%d × %d · %s" % (m["larghezza"], m["altezza"], _hz(m["frequenza"])))
        lw, lh = schermi.dimensione_logica(self.conf[m["nome"]])
        riga(tr("Desktop Area"), "%d × %d" % (lw, lh))
        riga(tr("Position"), "%d, %d" % (m["x"], m["y"]))
        riga(tr("Variable Refresh Rate"), tr("On") if m["vrr"] else tr("Off"))
        return e

    # ------------------------------------------------------------ modifiche
    def scegli(self, nome):
        if nome != self.scelto:
            self.scelto = nome
            self._ridisegna_dettaglio()

    def _cambia(self, nome, **valori):
        self.conf[nome].update(valori)
        if valori.get("acceso") is False and self.principale == nome:
            altri = [n for n, c in self.conf.items() if c["acceso"] and not c["specchio"]]
            self.principale = altri[0] if altri else self.principale
        if valori.get("acceso") is True and self.conf[nome]["specchio"] is None:
            self._accosta(nome)
        if "scala" in valori or "rotazione" in valori:
            self._compatta()
        GLib.idle_add(self._dopo_modifica)

    def _dopo_modifica(self):
        self._ridisegna_dettaglio()
        return False

    def _risoluzione(self, m, wh):
        freq = schermi.frequenze(m, *wh)
        self._cambia(m["nome"], larghezza=wh[0], altezza=wh[1],
                     frequenza=freq[0] if freq else self.conf[m["nome"]]["frequenza"])
        self._compatta()

    def _principale(self, nome, attivo):
        # uno schermo principale c'e' sempre: spegnere l'interruttore di
        # quello attuale non fa nulla (si sceglie accendendolo su un altro)
        if attivo:
            self.principale = nome
        GLib.idle_add(self._dopo_modifica)

    def _modo_attuale(self):
        accesi = [n for n, c in self.conf.items() if c["acceso"]]
        if len(accesi) == 1:
            return 2 + [m["nome"] for m in self.schermi].index(accesi[0])
        if any(c["specchio"] for c in self.conf.values()):
            return 1
        return 0

    def _cambia_modo(self, i):
        if i == self._modo_attuale():
            return
        nomi = [m["nome"] for m in self.schermi]
        fonte = self.principale if self.principale in nomi else nomi[0]
        if i == 0:                               # uniti, uno accanto all'altro
            for n in nomi:
                self.conf[n].update(acceso=True, specchio=None)
            x = 0
            for n in [fonte] + [n for n in nomi if n != fonte]:
                c = self.conf[n]
                c.update(x=x, y=0)
                x += schermi.dimensione_logica(c)[0]
        elif i == 1:                             # tutti copiano il principale
            for n in nomi:
                self.conf[n].update(acceso=True, specchio=None if n == fonte else fonte)
        else:                                    # uno solo
            solo = nomi[i - 2]
            for n in nomi:
                self.conf[n].update(acceso=(n == solo), specchio=None)
            self.principale = solo
            self.scelto = solo
        GLib.idle_add(self._dopo_modifica)

    def _annulla(self):
        self.conf = copy.deepcopy(self.originale)
        self.principale = self.principale_orig
        self._ridisegna_dettaglio()

    # -------------------------------------------------- disposizione
    def _rett(self, nome, x=None, y=None):
        c = self.conf[nome]
        w, h = schermi.dimensione_logica(c)
        return (c["x"] if x is None else x, c["y"] if y is None else y, w, h)

    def posiziona(self, nome, x, y):
        """Lascia lo schermo dov'e' stato lasciato, agganciato al lato piu'
        vicino di un altro schermo, senza sovrapposizioni."""
        altri = [n for n, c in self.conf.items() if n != nome and c["acceso"] and not c["specchio"]]
        if not altri:
            return
        _x, _y, w, h = self._rett(nome)
        candidati = []
        for o in altri:
            ox, oy, ow, oh = self._rett(o)
            def vicino(v, a, b):
                v = max(a, min(v, b))
                return v
            ty = vicino(y, oy - h + 40, oy + oh - 40)
            tx = vicino(x, ox - w + 40, ox + ow - 40)
            for cx, cy in ((ox + ow, ty), (ox - w, ty), (tx, oy + oh), (tx, oy - h)):
                # allineamento dei bordi se e' quasi allineato
                if abs(cy - oy) < oh * 0.08:
                    cy = oy
                if abs((cy + h) - (oy + oh)) < oh * 0.08:
                    cy = oy + oh - h
                if abs(cx - ox) < ow * 0.08:
                    cx = ox
                if abs((cx + w) - (ox + ow)) < ow * 0.08:
                    cx = ox + ow - w
                candidati.append((cx, cy))
        def sovrappone(cx, cy):
            for o in altri:
                ox, oy, ow, oh = self._rett(o)
                if cx < ox + ow and cx + w > ox and cy < oy + oh and cy + h > oy:
                    return True
            return False
        buoni = [p for p in candidati if not sovrappone(*p)]
        if not buoni:
            GLib.idle_add(self._dopo_modifica)
            return
        bx, by = min(buoni, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
        self.conf[nome].update(x=int(bx), y=int(by))
        self._normalizza()
        GLib.idle_add(self._dopo_modifica)

    def _accosta(self, nome):
        """Uno schermo riacceso va a destra degli altri."""
        altri = [n for n, c in self.conf.items() if n != nome and c["acceso"] and not c["specchio"]]
        if altri:
            destra = max(self._rett(o)[0] + self._rett(o)[2] for o in altri)
            self.conf[nome].update(x=destra, y=min(self._rett(o)[1] for o in altri))

    def _compatta(self):
        """Dopo un cambio di misura (scala, rotazione, risoluzione) gli schermi
        affiancati si riaccostano: niente buchi ne' sovrapposizioni."""
        accesi = sorted((n for n, c in self.conf.items() if c["acceso"] and not c["specchio"]),
                        key=lambda n: (self.conf[n]["x"], self.conf[n]["y"]))
        if len(accesi) < 2:
            if accesi:
                self.conf[accesi[0]].update(x=0, y=0)
            return
        # disposti in fila (il caso comune): si rimettono uno dopo l'altro
        in_fila = len({self.conf[n]["y"] for n in accesi}) == 1
        if in_fila:
            x = self.conf[accesi[0]]["x"]
            for n in accesi:
                self.conf[n]["x"] = x
                x += self._rett(n)[2]
        self._normalizza()

    def _normalizza(self):
        accesi = [n for n, c in self.conf.items() if c["acceso"] and not c["specchio"]]
        if not accesi:
            return
        mx = min(self.conf[n]["x"] for n in accesi)
        my = min(self.conf[n]["y"] for n in accesi)
        for n in accesi:
            self.conf[n]["x"] -= mx
            self.conf[n]["y"] -= my

    # --------------------------------------------------------- applicazione
    def _applica(self):
        if self._occupato or not self.modificato():
            return
        errore = schermi.controlla(self.conf)
        if errore:
            self._avviso(tr("At least one display must stay on and show its own picture."))
            return
        self._occupato = True
        self.bottone_applica.set_sensitive(False)
        prima, princ_prima = copy.deepcopy(self.originale), self.principale_orig
        nuova, princ = copy.deepcopy(self.conf), self.principale

        def lavoro():
            ok, msg = schermi.applica(nuova, princ)
            ok_v, diff = schermi.verifica(nuova) if ok else (False, [msg])
            GLib.idle_add(self._applicata, ok and ok_v, diff, prima, princ_prima, nuova, princ)
        threading.Thread(target=lavoro, daemon=True).start()

    def _applicata(self, ok, diff, prima, princ_prima, nuova, princ):
        if not ok:
            # lo schermo non ha preso le impostazioni: si torna subito indietro
            self._ripristina(prima, princ_prima,
                             tr("The display didn't accept these settings. The previous ones are back."))
            return False
        self._chiedi_conferma(prima, princ_prima, nuova, princ)
        return False

    def _chiedi_conferma(self, prima, princ_prima, nuova, princ):
        restano = [SECONDI_CONFERMA]
        d = Adw.AlertDialog(heading=tr("Keep These Display Settings?"),
                            body=self._testo_conto(restano[0]))
        d.add_response("revert", tr("Revert"))
        d.add_response("keep", tr("Keep Changes"))
        d.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("revert")
        d.set_close_response("revert")
        fatto = [False]

        def risposta(_d, r):
            if fatto[0]:
                return
            fatto[0] = True
            if r == "keep":
                try:
                    schermi.salva(nuova, princ)
                    self._avviso(tr("Display settings saved."))
                except OSError as e:
                    self._avviso(str(e))
                self._occupato = False
                self.ricarica()
            else:
                self._ripristina(prima, princ_prima, tr("Previous display settings restored."))

        def conto():
            if fatto[0]:
                return False
            restano[0] -= 1
            if restano[0] <= 0:
                d.close()
                risposta(d, "revert")
                return False
            d.set_body(self._testo_conto(restano[0]))
            return True
        d.connect("response", risposta)
        d.present(self.get_root())
        GLib.timeout_add_seconds(1, conto)

    def _testo_conto(self, n):
        return tr("The previous settings come back in {n} seconds unless you keep these.").format(n=n)

    def _ripristina(self, prima, princ_prima, messaggio):
        def lavoro():
            schermi.applica(prima, princ_prima)
            schermi.verifica(prima)
            GLib.idle_add(fine)

        def fine():
            self._occupato = False
            self.ricarica()
            self._avviso(messaggio)
            return False
        threading.Thread(target=lavoro, daemon=True).start()

    def _avviso(self, testo):
        toasts = getattr(self.get_root(), "toasts", None)
        if toasts is not None:
            toasts.add_toast(Adw.Toast(title=testo, timeout=4, use_markup=False))
