# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings > Language & Region.

Language, regional formats (dates, numbers, currency), keyboard layout and,
for Chinese, Japanese and Korean, the input method (Fcitx 5). Language and
keyboard are system settings, written by /usr/libexec/zeta-lingua through
pkexec; they apply everywhere (login screen, desktop, terminal, apps) after
logging out and back in. ZETA's own apps are translated into English and
Italian: with another language the system, Firefox, Thunderbird and the
GTK/Qt apps use it, and ZETA's apps stay in English rather than mixing.
"""
import gettext
import json
import os
import re
import subprocess
import threading

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import language as lingua_ui, tr  # noqa: E402
from system import applicazioni as reg, power  # noqa: E402

LINGUE = "/usr/share/zeta/lingue.json"
EVDEV = "/usr/share/X11/xkb/rules/evdev.lst"
CATALOGHI_ZETA = "/usr/share/locale/%s/LC_MESSAGES/zetarays.mo"
HELPER = "/usr/libexec/zeta-lingua"
FILE_IM = os.path.expanduser("~/.config/zeta/metodo-input")
PROFILO_FCITX = os.path.expanduser("~/.config/fcitx5/profile")
IM_NOMI = {"mozc": "Mozc (日本語)", "pinyin": "Pinyin (简体中文)", "chewing": "Chewing / Zhuyin (繁體中文)",
           "hangul": "Hangul (한국어)"}


def lingue():
    try:
        with open(LINGUE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return [{"locale": "en_US.UTF-8", "name": "English (United States)", "keyboard": "us", "im": ""}]


def leggi_kv(percorso):
    """KEY=value files of /etc/default (quotes removed)."""
    valori = {}
    try:
        with open(percorso, encoding="utf-8") as f:
            for riga in f:
                m = re.match(r'^\s*([A-Z_]+)=(.*)$', riga)
                if m:
                    valori[m.group(1)] = m.group(2).strip().strip('"\'')
    except OSError:
        pass
    return valori


def _nome_layout(codice, descrizione):
    """«German (de)», ma «English (US)» e non «English (US)  (us)»: il codice
    si aggiunge solo quando il nome non lo dice gia'."""
    if "(%s)" % codice.lower() in descrizione.lower():
        return descrizione
    return "%s (%s)" % (descrizione, codice)


def layout_xkb():
    """[(code, description)] of every keyboard layout XKB knows, with the
    descriptions translated by xkeyboard-config itself."""
    out, sezione = [], ""
    try:
        with open(EVDEV, encoding="utf-8") as f:
            for riga in f:
                riga = riga.rstrip("\n")
                if riga.startswith("!"):
                    sezione = riga[1:].strip()
                    continue
                if sezione == "layout" and riga.strip():
                    codice, _, desc = riga.strip().partition(" ")
                    out.append((codice, gettext.dgettext("xkeyboard-config", desc.strip())))
    except OSError:
        pass
    return sorted(out, key=lambda t: t[1].casefold()) or [("us", "English (US)")]


def zeta_tradotta(loc):
    base = loc.split(".")[0]
    if base.startswith("en"):
        return True
    return any(os.path.exists(CATALOGHI_ZETA % x) for x in (base, base.split("_")[0]))


def anteprima(loc):
    """Date, time and number as they will look in these formats."""
    codice = ("import locale, time\n"
              "locale.setlocale(locale.LC_ALL, '')\n"
              "print(time.strftime('%A %x  %X'), '·', locale.format_string('%.2f', 1234567.89, grouping=True))")
    try:
        r = subprocess.run(["python3", "-c", codice], capture_output=True, text=True, timeout=5,
                           env=dict(os.environ, LC_ALL=loc))
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def scrivi_profilo_fcitx(tastiera, im):
    """Fcitx 5 starts with the keyboard and the chosen input method
    (Ctrl+Space switches between them)."""
    os.makedirs(os.path.dirname(PROFILO_FCITX), exist_ok=True)
    primo = tastiera.split(",")[0] or "us"
    testo = ("[Groups/0]\nName=Default\nDefault Layout=%s\nDefaultIM=%s\n\n"
             "[Groups/0/Items/0]\nName=keyboard-%s\nLayout=\n\n"
             "[Groups/0/Items/1]\nName=%s\nLayout=\n\n"
             "[GroupOrder]\n0=Default\n") % (primo, im, primo, im)
    with open(PROFILO_FCITX + ".tmp", "w", encoding="utf-8") as f:
        f.write(testo)
    os.replace(PROFILO_FCITX + ".tmp", PROFILO_FCITX)


class LanguagePage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()
        self.lingue = lingue()
        attuale = leggi_kv("/etc/default/locale")
        self.loc_attuale = attuale.get("LANG", "en_US.UTF-8")
        self.fmt_attuale = attuale.get("LC_TIME", self.loc_attuale)
        tast = leggi_kv("/etc/default/keyboard")
        self.tast_attuale = tast.get("XKBLAYOUT", "us")

        # --- language
        g = Adw.PreferencesGroup(
            title=tr("Language"),
            description=tr("The language of the whole system: desktop, apps, terminal and messages "
                           "after you log out and back in; the login screen after a restart."))
        # Apply sits next to the first title: visible without scrolling
        self.applica = Gtk.Button(label=tr("Apply"), css_classes=["suggested-action"],
                                  valign=Gtk.Align.CENTER)
        self.applica.connect("clicked", lambda *_: self._applica())
        g.set_header_suffix(self.applica)
        self.lingua = Adw.ComboRow(title=tr("Language"),
                                   model=Gtk.StringList.new([l["name"] for l in self.lingue]))
        self.lingua.set_selected(self._indice(self.loc_attuale))
        self.lingua.connect("notify::selected", lambda *_: self._cambiata_lingua())
        g.add(self.lingua)
        self.nota = Adw.ActionRow(title="", use_markup=False)
        self.nota.add_css_class("dim-label")
        g.add(self.nota)
        self.add(g)

        # --- formats
        gf = Adw.PreferencesGroup(title=tr("Formats"),
                                  description=tr("How dates, times, numbers and currency are written."))
        self.formati = Adw.ComboRow(title=tr("Region"), model=Gtk.StringList.new(
            [tr("Same as the language")] + [l["name"] for l in self.lingue]))
        if self.fmt_attuale != self.loc_attuale:
            self.formati.set_selected(self._indice(self.fmt_attuale) + 1)
        self.formati.connect("notify::selected", lambda *_: self._aggiorna_anteprima())
        gf.add(self.formati)
        self.esempio = Adw.ActionRow(title=tr("Example"), use_markup=False)
        self.esempio.add_css_class("property")
        gf.add(self.esempio)
        self.add(gf)

        # --- keyboard
        # Keyboards: a list, as on Windows and macOS (Italian, English US,
        # English UK...). Alt+Shift or the indicator in the bar switch
        # between them; the first one is the one used at login.
        self.gk = Adw.PreferencesGroup(
            title=tr("Keyboards"),
            description=tr("Add the keyboards you use. Alt+Shift, or a click on the indicator "
                           "in the bar, switches between them; the first one is the default."))
        self.layout = layout_xkb()
        self.nomi_tast = {c: _nome_layout(c, d) for c, d in self.layout}
        self.scelti = [c for c in self.tast_attuale.split(",") if c in self.nomi_tast] or ["us"]
        self._righe_tast = []
        codici = [c for c, _d in self.layout]
        modello = Gtk.StringList.new([self.nomi_tast[c] for c in codici])
        self.aggiungi_tast = Adw.ComboRow(
            title=tr("Add a keyboard"), model=modello, enable_search=True,
            expression=Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        if "us" in codici:
            self.aggiungi_tast.set_selected(codici.index("us"))
        piu = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER,
                         tooltip_text=tr("Add"))
        piu.add_css_class("flat")
        piu.connect("clicked", lambda *_: self._aggiungi_tastiera())
        self.aggiungi_tast.add_suffix(piu)
        self._disegna_tastiere()
        self.add(self.gk)

        # --- input method
        gi_ = Adw.PreferencesGroup(
            title=tr("Input Method"),
            description=tr("To type Chinese, Japanese or Korean. Ctrl+Space switches between the "
                           "keyboard and the input method."))
        self.im_attivo = Adw.SwitchRow(title=tr("Use an input method"))
        self.im = Adw.ComboRow(title=tr("Input method"),
                               model=Gtk.StringList.new(list(IM_NOMI.values())))
        im_salvato = self._im_salvato()
        self.im_attivo.set_active(bool(im_salvato))
        if im_salvato in IM_NOMI:
            self.im.set_selected(list(IM_NOMI).index(im_salvato))
        gi_.add(self.im_attivo)
        gi_.add(self.im)
        # Fcitx's own settings (more input methods, shortcuts); its entries
        # are hidden from the app menu, they belong here
        avanzate = Adw.ActionRow(title=tr("Input method settings…"), activatable=True)
        avanzate.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        avanzate.connect("activated", lambda *_: reg.lancia(["fcitx5-config-qt"]))
        gi_.add(avanzate)
        self.add(gi_)

        self._cambiata_lingua(iniziale=True)

    # ---- helpers
    def _indice(self, loc):
        for i, l in enumerate(self.lingue):
            if l["locale"] == loc:
                return i
        return 0

    def _im_salvato(self):
        try:
            with open(FILE_IM, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def _scelta(self):
        l = self.lingue[self.lingua.get_selected()]
        i = self.formati.get_selected()
        fmt = self.lingue[i - 1]["locale"] if i > 0 else l["locale"]
        return l, fmt

    # ---- keyboards
    def _disegna_tastiere(self):
        for r in self._righe_tast + [self.aggiungi_tast]:
            if r.get_parent() is not None:
                self.gk.remove(r)
        self._righe_tast = []
        for i, codice in enumerate(self.scelti):
            riga = Adw.ActionRow(title=self.nomi_tast.get(codice, codice), use_markup=False,
                                 subtitle=tr("Default") if i == 0 else "")
            if i > 0:
                su = Gtk.Button(icon_name="go-up-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text=tr("Move up"))
                su.add_css_class("flat")
                su.connect("clicked", lambda *_a, n=i: self._sposta_tastiera(n))
                riga.add_suffix(su)
            if len(self.scelti) > 1:
                via = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER,
                                 tooltip_text=tr("Remove"))
                via.add_css_class("flat")
                via.connect("clicked", lambda *_a, c=codice: self._togli_tastiera(c))
                riga.add_suffix(via)
            self.gk.add(riga)
            self._righe_tast.append(riga)
        # at most four keyboards (the limit of the keyboard system, XKB)
        self.aggiungi_tast.set_sensitive(len(self.scelti) < 4)
        self.gk.add(self.aggiungi_tast)

    def _aggiungi_tastiera(self):
        codice = self.layout[self.aggiungi_tast.get_selected()][0]
        if codice not in self.scelti and len(self.scelti) < 4:
            self.scelti.append(codice)
            self._disegna_tastiere()

    def _togli_tastiera(self, codice):
        if len(self.scelti) > 1 and codice in self.scelti:
            self.scelti.remove(codice)
            self._disegna_tastiere()

    def _sposta_tastiera(self, n):
        self.scelti[n - 1], self.scelti[n] = self.scelti[n], self.scelti[n - 1]
        self._disegna_tastiere()

    def _tastiera_subito(self, tastiera):
        """The new keyboards in this session at once (no need to log out):
        Hyprland, the file it reads at login, and the indicator in the bar."""
        opzioni = "grp:alt_shift_toggle" if "," in tastiera else ""
        varianti = ",".join("" for _ in tastiera.split(","))
        try:
            cartella = os.path.expanduser("~/.config/hypr")
            os.makedirs(cartella, exist_ok=True)
            with open(os.path.join(cartella, "zeta_tastiera.lua"), "w", encoding="utf-8") as f:
                f.write('return { layout = "%s", variant = "%s", options = "%s" }\n'
                        % (tastiera, varianti, opzioni))
        except OSError:
            pass
        reg.lancia(["hyprctl", "eval",
                    "hl.config({ input = { kb_layout = \"%s\", kb_variant = \"%s\", "
                    "kb_options = \"%s\" } })" % (tastiera, varianti, opzioni)])
        reg.lancia(["zeta-dock", "apply"])

    def _cambiata_lingua(self, iniziale=False):
        l, _fmt = self._scelta()
        if zeta_tradotta(l["locale"]):
            self.nota.set_title(tr("Everything is shown in this language."))
        else:
            self.nota.set_title(tr("The system, Firefox, Thunderbird and most apps use this language; "
                                   "the ZETA RAYS apps are not translated into it yet and stay in English."))
        if not iniziale:
            # the usual keyboard and input method of the new language
            proposti = [c for c in l["keyboard"].split(",") if c in self.nomi_tast]
            if proposti:
                self.scelti = proposti
                self._disegna_tastiere()
            if l["im"]:
                self.im_attivo.set_active(True)
                self.im.set_selected(list(IM_NOMI).index(l["im"]))
        self._aggiorna_anteprima()

    def _aggiorna_anteprima(self):
        _l, fmt = self._scelta()
        self.esempio.set_subtitle(anteprima(fmt) or fmt)

    def _toast(self, testo, logout=False):
        w = self.get_root()
        toasts = getattr(w, "toasts", None)
        if toasts is None:
            return
        t = Adw.Toast(title=testo, timeout=0 if logout else 4, use_markup=False)
        if logout:
            t.set_button_label(tr("Log Out"))
            t.connect("button-clicked", lambda *_: power.logout())
        toasts.add_toast(t)

    def _helper(self, *argv):
        r = subprocess.run(["pkexec", HELPER, "--lang=%s" % lingua_ui()] + list(argv),
                           capture_output=True, text=True)
        try:
            esito = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            esito = {}
        if r.returncode == 126:                  # password window closed by the user
            return None
        if r.returncode == 127 and not r.stdout.strip():
            return {"error": tr("The change needs an administrator's password, and it was not accepted.")}
        return esito if r.returncode == 0 else {"error": esito.get("error") or tr("Not changed.")}

    def _applica(self):
        l, fmt = self._scelta()
        tastiera = ",".join(self.scelti)
        self.applica.set_sensitive(False)

        def lavora():
            esiti = []
            cambia_lingua = (l["locale"] != self.loc_attuale or fmt != self.fmt_attuale)
            if cambia_lingua:
                esiti.append(self._helper("language", l["locale"], *([fmt] if fmt != l["locale"] else [])))
            if tastiera != self.tast_attuale and (not esiti or esiti[-1] and "error" not in esiti[-1]):
                esiti.append(self._helper("keyboard", tastiera))
            GLib.idle_add(fine, esiti, cambia_lingua)

        def fine(esiti, cambia_lingua):
            self.applica.set_sensitive(True)
            self._salva_im(tastiera)
            if any(e is None for e in esiti):
                return False
            errori = [e["error"] for e in esiti if "error" in e]
            if errori:
                self._toast(errori[0])
                return False
            if tastiera != self.tast_attuale:
                self._tastiera_subito(tastiera)
            self.loc_attuale, self.fmt_attuale, self.tast_attuale = l["locale"], fmt, tastiera
            if cambia_lingua:
                self._toast(tr("Saved. Log out and back in to use the new settings everywhere."),
                            logout=True)
            elif esiti:
                self._toast(tr("Saved. The keyboards are ready: Alt+Shift switches between them."))
            else:
                self._toast(tr("Saved."))
            return False

        threading.Thread(target=lavora, daemon=True).start()

    def _salva_im(self, tastiera):
        """The input method is the user's own setting (no password)."""
        im = list(IM_NOMI)[self.im.get_selected()] if self.im_attivo.get_active() else ""
        if im == self._im_salvato():
            return
        os.makedirs(os.path.dirname(FILE_IM), exist_ok=True)
        if im:
            with open(FILE_IM, "w", encoding="utf-8") as f:
                f.write(im + "\n")
            scrivi_profilo_fcitx(tastiera, im)
            reg.lancia(["fcitx5", "-d", "--replace"])
        else:
            try:
                os.unlink(FILE_IM)
            except OSError:
                pass
            subprocess.run(["pkill", "-x", "fcitx5"], capture_output=True)
