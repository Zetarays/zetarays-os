# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Settings › Fonts: the font library.

Every font of the computer shown in its own typeface, with a sample text
that can be changed, a search, "Add Fonts…" (the files are copied into
~/.local/share/fonts and are ready at once in every app) and removal of the
fonts added by the user. System fonts belong to the system packages and are
not removed here.

The list is read only when the page is opened, and built a few rows at a
time: Settings must open instantly even with hundreds of fonts installed.
"""
import os
import shutil
import subprocess
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from i18n import ntr, tr  # noqa: E402

CARTELLA = os.path.join(GLib.get_user_data_dir(), "fonts")
ESTENSIONI = (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".pfb")
CAMPIONE = "The quick brown fox jumps over the lazy dog 0123456789"


def _dell_utente(percorso):
    casa = os.path.expanduser("~")
    return percorso.startswith((CARTELLA + os.sep, os.path.join(casa, ".fonts") + os.sep))


def famiglie():
    """{famiglia: {"stili": set, "file": set, "utente": bool}} da fontconfig."""
    try:
        r = subprocess.run(["fc-list", "--format", "%{family[0]}\\t%{style[0]}\\t%{file}\\n"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for riga in r.stdout.splitlines():
        parti = riga.split("\t")
        if len(parti) != 3 or not parti[0].strip():
            continue
        fam, stile, file = parti[0].strip(), parti[1].strip(), parti[2].strip()
        voce = out.setdefault(fam, {"stili": set(), "file": set(), "utente": False})
        voce["stili"].add(stile)
        voce["file"].add(file)
        voce["utente"] = voce["utente"] or _dell_utente(file)
    return out


def _aggiorna_cache():
    subprocess.run(["fc-cache", "-f", CARTELLA], capture_output=True, timeout=120)


class FontsPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self._caricata = False
        self._righe = []
        self._campione = CAMPIONE

        intro = Adw.PreferencesGroup(
            title=tr("Fonts"),
            description=tr("The fonts of this computer, each shown in its own typeface. "
                           "Fonts you add are ready at once in every app."))
        aggiungi = Gtk.Button(label=tr("Add Fonts…"), valign=Gtk.Align.CENTER,
                              css_classes=["suggested-action"])
        aggiungi.connect("clicked", lambda *_: self._scegli_file())
        intro.set_header_suffix(aggiungi)
        self.cerca = Adw.EntryRow(title=tr("Search fonts"))
        self.cerca.connect("changed", lambda *_: self._filtra())
        intro.add(self.cerca)
        self.prova = Adw.EntryRow(title=tr("Sample text"))
        self.prova.set_text(CAMPIONE)
        self.prova.connect("changed", lambda *_: self._nuovo_campione())
        intro.add(self.prova)
        self.add(intro)

        self.gruppo = Adw.PreferencesGroup()
        self.lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE,
                                 css_classes=["boxed-list"])
        self.lista.set_filter_func(self._visibile)
        self.attesa = Adw.ActionRow(title=tr("Reading the fonts…"))
        self.lista.append(self.attesa)
        self.gruppo.add(self.lista)
        self.add(self.gruppo)

        # «Add Fonts…» also by dropping files on the page
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._rilascio)
        self.add_controller(drop)

        self.connect("map", lambda *_: self._carica())

    # ---- elenco
    def _carica(self, forza=False):
        if self._caricata and not forza:
            return
        self._caricata = True

        def lavora():
            dati = famiglie()
            GLib.idle_add(self._mostra, dati)
        threading.Thread(target=lavora, daemon=True).start()

    def _mostra(self, dati):
        for r in self._righe + [self.attesa]:
            if r.get_parent() is not None:
                self.lista.remove(r)
        self._righe = []
        voci = sorted(dati.items(), key=lambda kv: (not kv[1]["utente"], kv[0].casefold()))
        self.gruppo.set_description(ntr("{n} font family", "{n} font families", len(voci))
                                    .format(n=len(voci)))

        def a_blocchi(i=0):
            for fam, v in voci[i:i + 40]:
                self._riga(fam, v)
            if i + 40 < len(voci):
                GLib.idle_add(a_blocchi, i + 40)
            return False
        a_blocchi()
        return False

    def _riga(self, famiglia, voce):
        riga = Adw.ActionRow(use_markup=True)
        riga.famiglia = famiglia
        riga.set_title(GLib.markup_escape_text(famiglia))
        n = len(voce["stili"])
        dove = tr("Added by you") if voce["utente"] else tr("System")
        riga.set_subtitle(GLib.markup_escape_text(
            ntr("{n} style", "{n} styles", n).format(n=n) + " · " + dove))
        # anteprima a destra, di larghezza fissa: il nome e i dettagli a
        # sinistra restano interi
        prova = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=30,
                          width_chars=30,
                          margin_top=4, margin_bottom=4)
        prova.add_css_class("zeta-font-prova")
        riga.prova = prova
        self._imposta_prova(riga)
        riga.add_suffix(prova)
        if voce["utente"]:
            via = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text=tr("Remove"))
            via.add_css_class("flat")
            via.connect("clicked", lambda *_a, v=voce, f=famiglia: self._rimuovi(f, v))
            riga.add_suffix(via)
        self.lista.append(riga)
        self._righe.append(riga)

    def _imposta_prova(self, riga):
        testo = GLib.markup_escape_text(self._campione or riga.famiglia)
        famiglia = GLib.markup_escape_text(riga.famiglia).replace('"', "&quot;")
        riga.prova.set_markup('<span font_family="%s" size="large">%s</span>' % (famiglia, testo))

    def _nuovo_campione(self):
        self._campione = self.prova.get_text().strip() or CAMPIONE
        for r in self._righe:
            self._imposta_prova(r)

    def _visibile(self, riga):
        q = self.cerca.get_text().strip().casefold()
        return not q or not hasattr(riga, "famiglia") or q in riga.famiglia.casefold()

    def _filtra(self):
        self.lista.invalidate_filter()

    # ---- aggiungere e togliere
    def _scegli_file(self):
        filtro = Gtk.FileFilter(name=tr("Fonts"))
        for e in ESTENSIONI:
            filtro.add_suffix(e.lstrip("."))
        filtri = Gio.ListStore.new(Gtk.FileFilter)
        filtri.append(filtro)
        dialogo = Gtk.FileDialog(title=tr("Add Fonts"), filters=filtri, modal=True)
        dialogo.open_multiple(self.get_root(), None, self._scelti)

    def _scelti(self, dialogo, esito):
        try:
            files = dialogo.open_multiple_finish(esito)
        except GLib.Error:
            return                       # annullato
        self._installa([f.get_path() for f in files if f.get_path()])

    def _rilascio(self, _t, valore, _x, _y):
        files = valore.get_files() if hasattr(valore, "get_files") else []
        self._installa([f.get_path() for f in files if f.get_path()])
        return True

    def _installa(self, percorsi):
        validi = [p for p in percorsi if p.lower().endswith(ESTENSIONI) and os.path.isfile(p)]
        if not validi:
            self._avviso(tr("No font files: choose .ttf, .otf, .ttc or .woff files."))
            return

        def lavora():
            os.makedirs(CARTELLA, exist_ok=True)
            copiati = 0
            for p in validi:
                dest = os.path.join(CARTELLA, os.path.basename(p))
                try:
                    if os.path.abspath(p) != os.path.abspath(dest):
                        shutil.copy2(p, dest)
                    copiati += 1
                except OSError:
                    continue
            _aggiorna_cache()
            GLib.idle_add(self._installati, copiati)
        threading.Thread(target=lavora, daemon=True).start()

    def _installati(self, n):
        self._avviso(ntr("{n} font added: it is ready in every app.",
                         "{n} fonts added: they are ready in every app.", n).format(n=n))
        self._carica(forza=True)
        return False

    def _rimuovi(self, famiglia, voce):
        def lavora():
            for f in voce["file"]:
                if _dell_utente(f):
                    try:
                        Gio.File.new_for_path(f).trash(None)     # recuperabile dal Cestino
                    except GLib.Error:
                        pass
            _aggiorna_cache()
            GLib.idle_add(lambda: (self._avviso(tr("“{name}” moved to the Trash.").format(name=famiglia)),
                                   self._carica(forza=True)) and False)
        threading.Thread(target=lavora, daemon=True).start()

    def _avviso(self, testo):
        toasts = getattr(self.get_root(), "toasts", None)
        if toasts is not None:
            toasts.add_toast(Adw.Toast(title=testo, timeout=4, use_markup=False))
