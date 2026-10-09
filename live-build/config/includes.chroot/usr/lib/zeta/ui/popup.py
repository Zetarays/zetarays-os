# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — base comune per i pannelli a sovrapposizione (centro di controllo, energia).

- gtk4-layer-shell va caricato prima di libwayland: il processo si rilancia con
  LD_PRELOAD. Quella variabile NON deve arrivare ai programmi avviati dal
  pannello (le app GTK3 caricherebbero GTK4 e si chiuderebbero subito):
  clean_env() la toglie appena il pannello è partito.
- Colori d'accento condivisi con il launcher (~/.config/zeta/colors.css).
"""
import glob
import os
import sys

MARK = "ZETA_LAYER_PRELOADED"


def preload_layer_shell():
    if MARK in os.environ:
        return
    libs = glob.glob("/usr/lib/*/libgtk4-layer-shell.so.0")
    if not libs:
        return
    env = dict(os.environ, **{MARK: "1"})
    env["LD_PRELOAD"] = (libs[0] + " " + os.environ.get("LD_PRELOAD", "")).strip()
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


# Pannelli residenti: «ZETA_PANNELLO_NASCOSTO=1 zeta-energia» lo avvia e lo
# tiene pronto in memoria senza mostrarlo (lo fa la sessione); poi
# «zeta-pannello energia» lo mostra in un attimo (azione «mostra»).
NASCOSTO = "ZETA_PANNELLO_NASCOSTO"


def avvio_nascosto():
    """True una volta sola, per il processo avviato dalla sessione."""
    return os.environ.pop(NASCOSTO, None) == "1"


def azione_mostra(app, alterna):
    """Aggiunge all'app l'azione «mostra» (usata da zeta-pannello)."""
    from gi.repository import Gio
    a = Gio.SimpleAction.new("mostra", None)
    a.connect("activate", lambda *_: alterna())
    app.add_action(a)


def clean_env():
    """Da chiamare dopo l'avvio di GTK: i figli partono con l'ambiente normale."""
    pre = os.environ.get("LD_PRELOAD", "")
    kept = " ".join(p for p in pre.split() if "gtk4-layer-shell" not in p)
    if kept:
        os.environ["LD_PRELOAD"] = kept
    else:
        os.environ.pop("LD_PRELOAD", None)
    os.environ.pop(MARK, None)


DEFAULT_COLORS = """
@define-color accent #3A8DFF;
@define-color accent_ink #FFFFFF;
@define-color accent_soft rgba(58,141,255,0.14);
@define-color accent_line rgba(58,141,255,0.35);
@define-color surface rgba(18,18,20,0.94);
@define-color surface_2 rgba(255,255,255,0.04);
@define-color ink #EDEDEA;
@define-color ink_2 #C8C8CC;
@define-color ink_dim #8A8A8E;
@define-color line rgba(255,255,255,0.08);
@define-color hover rgba(255,255,255,0.07);
@define-color hover_2 rgba(255,255,255,0.14);
@define-color glass rgba(18,18,20,0.78);
@define-color scrim rgba(0,0,0,0.45);
@define-color scrim_strong rgba(0,0,0,0.74);
"""

# Stile comune dei pannelli ZETA RAYS: vetro scuro, Roboto, angoli morbidi.
# Stile comune dei pannelli ZETA RAYS: i colori vengono dal tema scelto
# (~/.config/zeta/colors.css, generato da zeta-accent: scuro o chiaro).
BASE_CSS = """
window.zeta-overlay { background: transparent; }
.zeta-overlay * { font-family: "Roboto", sans-serif; color: @ink; }
.zeta-card { background: @surface; border: 1px solid @line;
             border-radius: 20px; box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35); }
.zeta-section { background: @surface_2; border-radius: 14px; }
.zeta-caption { font-size: 11px; color: @ink_dim; font-weight: 500; }
.zeta-dim { color: @ink_dim; }
.zeta-small { font-size: 12px; }
.zeta-title { font-size: 13px; font-weight: 500; }
button.zeta-flat { background: none; border: none; box-shadow: none; padding: 6px 8px; border-radius: 10px; }
button.zeta-flat:hover { background: @hover; }
button.zeta-round { min-width: 36px; min-height: 36px; padding: 0; border-radius: 999px;
                    background: @hover; border: none; box-shadow: none; }
button.zeta-round:hover { background: @hover_2; }
button.zeta-round.on { background: @accent; }
button.zeta-round.on image { color: @accent_ink; }
button.zeta-tile { padding: 10px 12px; border-radius: 14px; border: none; box-shadow: none;
                   background: @hover; }
button.zeta-tile:hover { background: @hover_2; }
button.zeta-tile.on { background: @accent_soft; }
button.zeta-tile .tile-icon { min-width: 30px; min-height: 30px; border-radius: 999px;
                              background: @hover_2; }
button.zeta-tile.on .tile-icon { background: @accent; }
button.zeta-tile.on .tile-icon image { color: @accent_ink; }
button.zeta-tile:disabled { opacity: 0.45; }
.zeta-row { padding: 7px 10px; border-radius: 10px; }
button.zeta-row { background: none; border: none; box-shadow: none; }
button.zeta-row:hover { background: @hover; }
.zeta-check { color: @accent; }
scale { padding: 0; }
scale trough { min-height: 6px; border-radius: 999px; background: @hover_2; }
scale highlight { border-radius: 999px; background: @accent; }
scale slider { min-width: 16px; min-height: 16px; margin: -6px; border-radius: 999px;
               background: #FFFFFF; border: 1px solid @line;
               box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35); }
entry.zeta-entry { min-height: 34px; border-radius: 10px; background: @hover;
                   border: 1px solid @line; padding: 0 10px; box-shadow: none; }
entry.zeta-entry:focus-within { border-color: @accent; }
button.zeta-primary { background: @accent; color: @accent_ink; border: none; border-radius: 10px;
                      padding: 6px 16px; box-shadow: none; }
button.zeta-primary label { color: @accent_ink; font-weight: 500; }
separator { background: @line; min-height: 1px; }
"""


# I due fornitori restano a portata di mano: ricarica() ci rimette dentro il
# file aggiornato invece di aggiungerne altri sopra, che a ogni cambio di tema
# si sarebbero accumulati per tutta la vita del pannello.
_colors = None
_style = None


def _leggi_colori(provider):
    path = os.path.expanduser("~/.config/zeta/colors.css")
    if os.path.exists(path):
        provider.load_from_path(path)
    else:
        provider.load_from_string(DEFAULT_COLORS)


def _chiaro():
    try:
        return open(os.path.expanduser("~/.config/zeta/tema")).read().strip() == "chiaro"
    except OSError:
        return False


def load_css(extra=""):
    global _colors, _style
    from gi.repository import Gdk, Gtk
    settings = Gtk.Settings.get_default()
    # I pannelli sono GTK4 puro (senza libadwaita): qui la proprietà serve.
    try:
        settings.set_property("gtk-application-prefer-dark-theme", not _chiaro())
    except TypeError:
        pass
    settings.set_property("gtk-icon-theme-name", "zeta")
    settings.set_property("gtk-font-name", "Roboto 10")
    display = Gdk.Display.get_default()
    _colors = Gtk.CssProvider()
    _leggi_colori(_colors)
    _style = Gtk.CssProvider()
    _style.load_from_string(BASE_CSS + extra)
    Gtk.StyleContext.add_provider_for_display(display, _colors, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    Gtk.StyleContext.add_provider_for_display(display, _style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)


def ricarica():
    """Rilegge i colori a pannello aperto, dopo un cambio di tema.

    Serve a chi il tema lo cambia da sé (il centro di controllo): senza questa,
    tutta la scrivania cambiava e restava dei colori di prima proprio il
    pannello da cui si era appena premuto.
    """
    if _colors is None:
        return
    from gi.repository import Gtk
    settings = Gtk.Settings.get_default()
    try:
        settings.set_property("gtk-application-prefer-dark-theme", not _chiaro())
    except TypeError:
        pass
    _leggi_colori(_colors)


def make_overlay(window, namespace, keyboard=True):
    """Finestra a tutto schermo, trasparente, sopra a tutto (layer shell)."""
    try:
        import gi
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LS
    except (ValueError, ImportError):
        LS = None
    window.add_css_class("zeta-overlay")
    if LS and LS.is_supported():
        LS.init_for_window(window)
        LS.set_namespace(window, namespace)
        LS.set_layer(window, LS.Layer.OVERLAY)
        LS.set_keyboard_mode(window, LS.KeyboardMode.EXCLUSIVE if keyboard else LS.KeyboardMode.NONE)
        LS.set_exclusive_zone(window, -1)
        for edge in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
            LS.set_anchor(window, edge, True)
    else:
        window.fullscreen()


def _monitor_del_cursore():
    """(x del cursore rispetto al suo monitor, larghezza logica del monitor,
    nome del monitor). Con piu' monitor «hyprctl cursorpos» da' coordinate
    globali: senza togliere la posizione del monitor un menu finiva fuori."""
    import json
    import subprocess
    try:
        cur = json.loads(subprocess.run(["hyprctl", "-j", "cursorpos"], capture_output=True,
                                        text=True, timeout=2).stdout)
        mons = json.loads(subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True,
                                         text=True, timeout=2).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0, None, None
    cx, cy = cur.get("x", 0), cur.get("y", 0)
    scelto = None
    for m in mons:
        scala = m.get("scale") or 1
        w, h = m.get("width", 0) / scala, m.get("height", 0) / scala
        if m.get("transform", 0) % 2:
            w, h = h, w
        if m.get("x", 0) <= cx < m.get("x", 0) + w and m.get("y", 0) <= cy < m.get("y", 0) + h:
            scelto = (m, w)
            break
        if scelto is None and m.get("focused"):
            scelto = (m, w)
    if scelto is None:
        return cx, None, None
    m, w = scelto
    return cx - m.get("x", 0), w, m.get("name")


def menu_al_cursore(window, card, larghezza=220):
    """Un menu della barra (Dock, finestre ridotte, Posta) sotto il cursore,
    sul monitor del cursore e SEMPRE intero dentro lo schermo: vicino al
    bordo destro si sposta a sinistra invece di uscire. Va chiamato dopo
    make_overlay."""
    x, larg_mon, nome = _monitor_del_cursore()
    card.set_size_request(larghezza, -1)
    if larg_mon:
        inizio = min(x - larghezza / 2, larg_mon - larghezza - 8)
    else:
        inizio = x - larghezza / 2
    card.set_margin_start(int(max(8, inizio)))
    card.set_margin_end(8)
    if nome:
        try:
            import gi
            gi.require_version("Gtk4LayerShell", "1.0")
            from gi.repository import Gdk, Gtk4LayerShell as LS
            monitori = Gdk.Display.get_default().get_monitors()
            for i in range(monitori.get_n_items()):
                gm = monitori.get_item(i)
                if gm.get_connector() == nome:
                    LS.set_monitor(window, gm)
                    break
        except (ValueError, ImportError, AttributeError):
            pass


def close_on_outside(window, card, on_close):
    """Esc o un clic fuori dal riquadro chiudono il pannello."""
    from gi.repository import Gdk, Gtk
    keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    keys.connect("key-pressed", lambda _c, kv, _k, _s: (on_close(), True)[1]
                 if kv == Gdk.KEY_Escape else False)
    window.add_controller(keys)
    click = Gtk.GestureClick()

    def released(_g, _n, x, y):
        w = window.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None:
            if w is card:
                return
            w = w.get_parent()
        on_close()
    click.connect("released", released)
    window.add_controller(click)
