# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — menu del tasto destro per le app, uguale ovunque.

Lo usano il menu delle app (logo nella barra) e la ricerca: stesse voci e
stesso aspetto. E' disegnato DENTRO la finestra (sopra il contenuto, con un
Gtk.Overlay) e non come menu a comparsa: il menu delle app e la ricerca sono
strati a tutto schermo con la tastiera esclusiva, e li' il popup di GTK
riceveva il clic ma lo perdeva (la voce si evidenziava, il menu si chiudeva,
l'azione non partiva; da tastiera invece funzionava). Le azioni veloci
(Scrivania, Dock, togli dal menu) si fanno qui; quelle che aprono una finestra
(Informazioni, Disinstalla) le apre «zeta-app» come finestra normale.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from system import applicazioni as reg  # noqa: E402

CSS = """
.zeta-menu-app { background: @surface; border: 1px solid @line; border-radius: 12px;
                 padding: 6px; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45); }
.zeta-menu-voce { background: none; border: none; box-shadow: none; padding: 7px 14px;
                  border-radius: 8px; min-height: 0; }
.zeta-menu-voce:hover, .zeta-menu-voce:focus-visible { background: @hover_2; }
.zeta-menu-voce label { font-size: 13px; color: @ink; }
.zeta-menu-voce.pericolo label { color: #FF6B6B; }
.zeta-menu-sep { margin: 4px 8px; background: @line; min-height: 1px; }
"""
_stile = [False]


def _carica_stile():
    if _stile[0]:
        return
    prov = Gtk.CssProvider()
    prov.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
    _stile[0] = True


class MenuInterno:
    """Menu disegnato sopra il contenuto di una finestra (Gtk.Overlay)."""

    def __init__(self, overlay):
        self.overlay = overlay
        self.box = None
        _carica_stile()

    def aperto(self):
        return self.box is not None

    def contiene(self, widget):
        while widget is not None:
            if widget is self.box:
                return True
            widget = widget.get_parent()
        return False

    def chiudi(self):
        if self.box is not None:
            self.overlay.remove_overlay(self.box)
            self.box = None

    def apri(self, widget, x, y, voci):
        self.chiudi()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                      halign=Gtk.Align.START, valign=Gtk.Align.START)
        box.add_css_class("zeta-menu-app")
        primo = None
        for voce in voci:
            if voce is None:
                sep = Gtk.Box()
                sep.add_css_class("zeta-menu-sep")
                box.append(sep)
                continue
            # (etichetta, azione) o (etichetta, azione, True) per una voce pericolosa
            etichetta, fn = voce[0], voce[1]
            b = Gtk.Button(child=Gtk.Label(label=etichetta, xalign=0))
            b.add_css_class("zeta-menu-voce")
            if len(voce) > 2 and voce[2]:
                b.add_css_class("pericolo")
            b.connect("clicked", lambda _b, f=fn: (self.chiudi(), f()))
            box.append(b)
            primo = primo or b
        # posizione: dove si e' cliccato, ma sempre dentro la finestra
        punto = widget.translate_coordinates(self.overlay, x, y)   # (ok, x, y)
        if punto and len(punto) == 3 and not punto[0]:
            punto = None
        px, py = (punto[-2], punto[-1]) if punto else (x, y)
        larg = box.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        alt = box.measure(Gtk.Orientation.VERTICAL, larg)[1]
        W, H = self.overlay.get_width(), self.overlay.get_height()
        box.set_margin_start(int(max(8, min(px, W - larg - 8))))
        box.set_margin_top(int(max(8, min(py, H - alt - 8))))
        self.overlay.add_overlay(box)
        self.box = box
        if primo is not None:
            GLib.idle_add(lambda: (primo.grab_focus(), False)[1])


def _zeta_app(*argv):
    reg.lancia(["zeta-app", *argv])


def avviso(titolo, testo=""):
    reg.lancia(["notify-send", "-a", "ZETA RAYS", "-i", "zeta-app", titolo, testo])


def voci_app(app, avvia, dopo=None):
    """Voci del menu per un'app del registro. avvia: come avviarla da qui;
    dopo: chiamata dopo ogni azione (per chiudere il menu delle app)."""
    def fatto(fn):
        def f():
            fn()
            if dopo:
                dopo()
        return f

    def esito(risultato):
        ok, msg = risultato
        avviso(msg)

    voci = [(tr("Open"), fatto(lambda: avvia(app))),
            (tr("Open file location"), fatto(lambda: reg.mostra_nel_gestore_file(reg.posizione(app)))),
            None]
    sulla = reg.sulla_scrivania(app) or reg.appimage_sulla_scrivania(app)
    if sulla:
        voci.append((tr("Already on the Desktop"),
                     fatto(lambda: reg.mostra_nel_gestore_file(sulla))))
    else:
        voci.append((tr("Add to Desktop"), fatto(lambda: esito(reg.aggiungi_scrivania(app)))))
    if reg.nel_dock(app):
        voci.append((tr("Remove from Dock"), fatto(lambda: esito(reg.togli_dock(app)))))
    else:
        voci.append((tr("Add to Dock"), fatto(lambda: esito(reg.aggiungi_dock(app)))))
    voci += [None, (tr("Get info"), fatto(lambda: _zeta_app("info", app.id))),
             (tr("Change icon…"), fatto(lambda: _zeta_app("cambia-icona", app.id)))]
    if app.icona_personale:
        voci.append((tr("Restore icon"), fatto(lambda: esito(reg.ripristina_icona(app)))))
    if not app.protetta:
        voci.append((tr("Remove from Applications"), fatto(
            lambda: (reg.nascondi(app), avviso(tr("“{name}” removed from the menu").format(name=app.nome),
                                               tr("Put it back from Settings › Default Apps.")))))
        )
        si, _perche = reg.disinstallabile(app)
        if si:
            voci.append((tr("Uninstall…"), fatto(lambda: _zeta_app("disinstalla", app.id)), True))
    return voci
