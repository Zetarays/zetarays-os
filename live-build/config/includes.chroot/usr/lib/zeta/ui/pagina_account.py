# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › Account: name, user and picture.

The picture (round, 512 px) is shown in the power and account menu, on the
lock screen and at login. It can be a photo of the user (.jpg or .png, cut
to a circle from the centre) or a plain circle in one of the four system
colours (the palette in ui/accento.py), by default the accent colour.
"""
import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from system import avatar  # noqa: E402
from ui import accento  # noqa: E402

CSS = """
.av-colore { min-width: 40px; min-height: 40px; padding: 0; border-radius: 999px; }
.av-colore.av-chiaro { box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.22); }
.av-colore.av-scelto { outline: 2px solid @accent_bg_color; outline-offset: 3px; }
""" + "".join(".av-colore-%s { background: %s; }\n" % (k, c) for k, c, _n in accento.TAVOLOZZA)
_css_caricato = False


def _carica_css():
    global _css_caricato
    if _css_caricato:
        return
    prov = Gtk.CssProvider()
    prov.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_caricato = True


def _immagine(percorso, lato):
    """Immagine di misura fissa (il file e' gia' tondo, con la trasparenza).
    Gtk.Image con pixel_size: un Gtk.Picture si allarga alla misura vera."""
    img = Gtk.Image(pixel_size=lato, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    _carica(img, percorso)
    return img


def _carica(img, percorso):
    try:
        # sempre dal disco: dopo un cambio il file ha lo stesso nome
        img.set_from_paintable(Gdk.Texture.new_from_filename(percorso))
    except GLib.Error:
        img.set_from_icon_name("zeta-account")


class AccountPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        nome, utente = avatar.nome_completo()

        testa = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
        self.grande = _immagine(avatar.percorso(), 128)
        box.append(self.grande)
        box.append(Gtk.Label(label=nome, css_classes=["title-2"]))
        box.append(Gtk.Label(label="%s · %s" % (utente, os.uname().nodename),
                             css_classes=["dim-label"]))
        testa.add(box)
        self.add(testa)

        gruppo = Adw.PreferencesGroup(
            title=tr("Picture"),
            description=tr("Shown in the account menu, on the lock screen and at login."))
        scegli = Adw.ActionRow(title=tr("Choose a Picture…"),
                               subtitle=tr("A .jpg or .png photo, cut to a circle from the centre"),
                               activatable=True)
        scegli.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        scegli.connect("activated", lambda *_: self._scegli_file())
        gruppo.add(scegli)

        self.add(gruppo)

        # un cerchio pieno in un colore del sistema, senza disegni
        _carica_css()
        colori = Adw.PreferencesGroup(
            title=tr("Color"),
            description=tr("Or a plain circle in one of the system colors."))
        self.segui = Adw.SwitchRow(title=tr("Same as the Accent Color"),
                                   subtitle=tr("Changes when you change the accent color"))
        self.segui.connect("notify::active", self._segui_cambiato)
        colori.add(self.segui)
        fila = Gtk.Box(spacing=18, halign=Gtk.Align.START, margin_top=14, margin_bottom=14,
                       margin_start=14, margin_end=14)
        self.bottoni = []
        for chiave, colore, _nome in accento.TAVOLOZZA:
            b = Gtk.Button(css_classes=["av-colore", "av-colore-" + chiave],
                           tooltip_text=accento.nome(chiave), valign=Gtk.Align.CENTER)
            if colore == "#FFFFFF":
                b.add_css_class("av-chiaro")       # il bianco si vede anche sul chiaro
            b.colore = colore
            b.connect("clicked", lambda btn: self._usa(lambda c=btn.colore: avatar.imposta_colore(c)))
            fila.append(b)
            self.bottoni.append(b)
        colori.add(Adw.PreferencesRow(activatable=False, child=fila))
        self.add(colori)
        self._segna()

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._rilascio)
        self.add_controller(drop)
        self.connect("map", lambda *_: (_carica(self.grande, avatar.percorso()), self._segna()))

    def _scegli_file(self):
        filtro = Gtk.FileFilter(name=tr("Pictures (.jpg, .png)"))
        for est in ("png", "jpg", "jpeg", "PNG", "JPG", "JPEG"):
            filtro.add_suffix(est)
        filtri = Gio.ListStore.new(Gtk.FileFilter)
        filtri.append(filtro)
        dialogo = Gtk.FileDialog(title=tr("Choose a Picture"), filters=filtri, modal=True)
        dialogo.open(self.get_root(), None, self._scelto)

    def _scelto(self, dialogo, esito):
        try:
            f = dialogo.open_finish(esito)
        except GLib.Error:
            return                                   # annullato
        if f and f.get_path():
            p = f.get_path()
            self._usa(lambda: avatar.imposta_da_file(p))

    def _rilascio(self, _t, valore, _x, _y):
        files = valore.get_files() if hasattr(valore, "get_files") else []
        if files and files[0].get_path():
            p = files[0].get_path()
            self._usa(lambda: avatar.imposta_da_file(p))
            return True
        return False

    def _usa(self, lavoro):
        def filo():
            ok, msg = lavoro()
            GLib.idle_add(self._fatto, ok, msg)
        threading.Thread(target=filo, daemon=True).start()

    def _segna(self):
        """Interruttore e colore evidenziato secondo la scelta salvata."""
        scelta = avatar.scelta()
        self._aggiorno = True
        self.segui.set_active(scelta == "accento")
        self._aggiorno = False
        attuale = avatar.colore_attuale() if scelta != "foto" else None
        for b in self.bottoni:
            if b.colore == attuale:
                b.add_css_class("av-scelto")
            else:
                b.remove_css_class("av-scelto")

    def _segui_cambiato(self, riga, _p):
        if getattr(self, "_aggiorno", False):
            return
        if riga.get_active():
            self._usa(lambda: avatar.imposta_colore("accento"))
        else:
            # resta il colore di adesso, ma fisso
            c = avatar.colore_attuale()
            if any(c == x for _k, x, _n in accento.TAVOLOZZA):
                self._usa(lambda: avatar.imposta_colore(c))
            else:
                self._usa(lambda: avatar.imposta_colore(accento.PREDEFINITO))

    def _fatto(self, ok, msg):
        _carica(self.grande, avatar.percorso())
        self._segna()
        toasts = getattr(self.get_root(), "toasts", None)
        if toasts is not None:
            toasts.add_toast(Adw.Toast(title=msg, timeout=3, use_markup=False))
        # il menu di account (zeta-energia) rilegge l'immagine a ogni
        # apertura; la schermata di blocco la legge da ~/.face
        return False
