# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — tema chiaro o scuro, condiviso da tutte le app di ZETA RAYS.

I colori veri stanno in ~/.config/zeta/colors.css, rigenerato da zeta-accent
ogni volta che cambia il colore d'accento o il tema. Qui li carichiamo e li
mettiamo a disposizione come @surface, @ink, @line… così ogni app segue il
tema senza colori scritti a mano.
"""
import os

TEMA_FILE = os.path.expanduser("~/.config/zeta/tema")
COLORS_FILE = os.path.expanduser("~/.config/zeta/colors.css")

FALLBACK = """
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


def is_light():
    try:
        with open(TEMA_FILE) as f:
            return f.read().strip() == "chiaro"
    except OSError:
        return False


def colors_css():
    try:
        with open(COLORS_FILE) as f:
            css = f.read()
        if "@define-color surface" in css:      # file di una versione vecchia
            return css
    except OSError:
        pass
    return FALLBACK


# Il fornitore dei colori si tiene da parte: ricarica() gli rimette dentro il
# file aggiornato invece di aggiungerne un altro sopra. Aggiungerne uno a ogni
# cambio di tema li avrebbe accumulati per tutta la vita della finestra.
_base = None


def _schema(font="", icons=""):
    """Chiaro o scuro per GTK e libadwaita, più font e icone se richiesti."""
    from gi.repository import Gtk
    usa_adw = False
    try:
        import gi
        gi.require_version("Adw", "1")
        from gi.repository import Adw
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if is_light() else Adw.ColorScheme.FORCE_DARK)
        usa_adw = True
    except (ImportError, ValueError):
        pass
    st = Gtk.Settings.get_default()
    if st is not None:
        # Con libadwaita il tema si sceglie SOLO con AdwStyleManager: impostare
        # anche la proprietà di GTK genera un avviso e non serve a nulla.
        if not usa_adw:
            st.set_property("gtk-application-prefer-dark-theme", not is_light())
        if font:
            st.set_property("gtk-font-name", font)
        if icons:
            st.set_property("gtk-icon-theme-name", icons)


def ricarica():
    """Rilegge tema e colori a finestra aperta (dopo «zeta-aspetto cambia-tema»).

    Senza questa, chi cambia il tema dal centro di controllo o da Impostazioni
    vedeva tutta la scrivania cambiare tranne la finestra da cui l'aveva appena
    cambiato, che restava dei colori di prima finché non la si riapriva.
    """
    if _base is None:
        return
    _schema()
    _base.load_from_string(colors_css())


def apply(app_css="", font="Roboto 10", icons="zeta"):
    """Carica i colori del tema e poi lo stile dell'app. Da chiamare in do_activate."""
    global _base
    from gi.repository import Gdk, Gtk
    display = Gdk.Display.get_default()
    _schema(font, icons)
    _base = Gtk.CssProvider()
    _base.load_from_string(colors_css())
    Gtk.StyleContext.add_provider_for_display(display, _base,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    if app_css:
        prov = Gtk.CssProvider()
        prov.load_from_string(app_css)
        Gtk.StyleContext.add_provider_for_display(display, prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
