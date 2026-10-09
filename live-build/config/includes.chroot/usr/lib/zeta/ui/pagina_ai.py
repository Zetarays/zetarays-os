# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — Impostazioni › AI: quale intelligenza usa ZETA, chiavi, modelli.

Tutto cio' che puo' metterci piu' di un attimo (rete, Ollama, cifratura delle
chiavi) va in un thread: la finestra non si ferma mai ad aspettare.
"""
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from i18n import tr  # noqa: E402
from intelligence import ollama_gestione as og  # noqa: E402
from intelligence.registry import (CATALOG, DEFAULT_SYSTEM, Registry,  # noqa: E402
                                   keyring_set, keyring_where, modello_predefinito,
                                   save_settings)


def _in_thread(lavoro, fine):
    """lavoro() in un thread; fine(risultato) di nuovo nella finestra."""
    def corri():
        try:
            r = lavoro()
        except Exception as e:  # noqa: BLE001 - nessun errore deve far cadere le Impostazioni
            r = e
        GLib.idle_add(lambda: (fine(r), False)[1])
    threading.Thread(target=corri, daemon=True).start()


def _gb(x):
    return ("%.1f GB" % x) if x >= 0.1 else ("%.0f MB" % (x * 1000))


class PaginaAI:
    def __init__(self, finestra):
        self.w = finestra
        self.reg = Registry()
        self.page = Adw.PreferencesPage()
        self._gruppo_scelta()
        self._gruppo_ollama()
        self._gruppo_cloud()
        self._gruppo_comportamento()

    def toast(self, t):
        self.w.toast(t)

    # --- opzioni salvate in intelligence.json -------------------------------
    def _opz(self, pid, chiave, predef):
        return self.reg.settings.get("providers", {}).get(pid, {}).get(chiave, predef)

    def _salva_opz(self, pid, chiave, valore):
        self.reg.set_option(pid, chiave, valore)

    # --- quale intelligenza --------------------------------------------------
    def _gruppo_scelta(self):
        g = Adw.PreferencesGroup(
            title=tr("Active Intelligence"),
            description=tr("Automatic uses Ollama, the model on this computer, which works even "
                           "without internet; if it isn't available, the first online service with a key."))
        self.ids = ["auto"] + list(CATALOG)
        nomi = [tr("Automatic")] + [
            (tr("{name} (on this computer)") if CATALOG[p][2] == "local"
             else tr("{name} (online)")).format(name=CATALOG[p][1])
            for p in CATALOG]
        riga = Adw.ComboRow(title=tr("ZETA uses"), model=Gtk.StringList.new(nomi))
        attuale = self.reg.settings.get("default", "auto") or "auto"
        riga.set_selected(self.ids.index(attuale) if attuale in self.ids else 0)
        self.riga_effettiva = Adw.ActionRow(title=tr("In use now"), subtitle="…")

        def scegli(c, _p):
            pid = self.ids[c.get_selected()]
            try:
                self.reg.scegli(pid)
            except (ValueError, OSError) as e:
                self.toast(tr("Choice not saved: {error}").format(error=e))
                return
            if pid == "auto":
                self.toast(tr("ZETA will choose automatically"))
            else:
                self.toast(tr("ZETA will use {name}").format(name=CATALOG[pid][1]))
            self._aggiorna_effettiva()
        riga.connect("notify::selected", scegli)
        g.add(riga)
        g.add(self.riga_effettiva)
        self.page.add(g)
        self._aggiorna_effettiva()

    def _aggiorna_effettiva(self):
        def lavoro():
            p = Registry().resolve_default()
            modello = p.config.model or modello_predefinito(p.config.name)
            if not modello and hasattr(p, "_model"):
                modello = p._model()          # Ollama: il primo modello installato
            return tr("{name} · model {model}").format(name=p.config.label,
                                                       model=modello or tr("default"))
        _in_thread(lavoro, lambda r: self.riga_effettiva.set_subtitle(
            r if isinstance(r, str) else tr("can't be determined")))

    # --- Ollama -------------------------------------------------------------
    def _gruppo_ollama(self):
        g = Adw.PreferencesGroup(title=tr("Ollama · On This Computer"),
                                 description=tr("Your questions stay on this computer."))
        self.o_stato = Adw.ActionRow(title=tr("Status"), subtitle=tr("checking…"))
        self.o_avvia = Gtk.Button(valign=Gtk.Align.CENTER, sensitive=False)
        self._o_attivo = False
        self.o_avvia.connect("clicked", self._o_avvia_ferma)
        self.o_libera = Gtk.Button(label=tr("Free Memory"), valign=Gtk.Align.CENTER,
                                   tooltip_text=tr("Unloads the model from memory: it stays installed "
                                                   "and reloads with the next question"))
        self.o_libera.connect("clicked", self._o_libera)
        self.o_stato.add_suffix(self.o_libera)
        self.o_stato.add_suffix(self.o_avvia)
        g.add(self.o_stato)

        self.o_modelli = Adw.ExpanderRow(title=tr("Installed Models"), subtitle="…")
        g.add(self.o_modelli)
        self._righe_modelli = []

        self.o_scarica = Adw.EntryRow(title=tr("Download a model (e.g. qwen3:4b, gemma3:4b, llama3.2:3b)"),
                                      show_apply_button=True)
        self.o_scarica.connect("apply", self._o_scarica)
        g.add(self.o_scarica)
        self.o_prog_riga = Adw.ActionRow(title=tr("Download"), visible=False)
        self.o_prog = Gtk.ProgressBar(valign=Gtk.Align.CENTER, hexpand=True, show_text=True)
        self.o_ferma_dl = Gtk.Button(label=tr("Cancel"), valign=Gtk.Align.CENTER)
        self.o_ferma_dl.connect("clicked", lambda *_: setattr(self, "_dl_fermo", True))
        self.o_prog_riga.add_suffix(self.o_prog)
        self.o_prog_riga.add_suffix(self.o_ferma_dl)
        g.add(self.o_prog_riga)

        g.add(self._opzioni("ollama", locale=True))
        prova = Adw.ActionRow(title=tr("Test Connection"), subtitle=tr("A short question to the model"))
        self._bottone_prova(prova, "ollama")
        g.add(prova)
        self.page.add(g)
        self._o_aggiorna()

    def _o_aggiorna(self):
        def lavoro():
            return {"inst": og.installato(), "attivo": og.servizio_attivo(), "ver": og.versione(),
                    "modelli": og.modelli(), "caricati": og.caricati(), "ris": og.risorse_processo()}

        def fine(d):
            if isinstance(d, Exception):
                self.o_stato.set_subtitle(tr("Error: {error}").format(error=d))
                return
            if not d["inst"]:
                self.o_stato.set_subtitle(tr("Ollama isn't installed"))
                self.o_avvia.set_visible(False)
                self.o_libera.set_visible(False)
                return
            self.o_avvia.set_sensitive(True)
            self._o_attivo = bool(d["attivo"])
            self.o_avvia.set_label(tr("Stop") if d["attivo"] else tr("Start"))
            if d["attivo"]:
                car = ", ".join("%s (%s)" % (m["nome"], _gb(m["gb"])) for m in d["caricati"])
                self.o_stato.set_subtitle(
                    tr("Running · version {version} · {loaded} · processes: {ram} of RAM").format(
                        version=d["ver"] or "?",
                        loaded=(tr("in memory: {models}").format(models=car) if car
                                else tr("no model in memory")),
                        ram=_gb(d["ris"]["ram_gb"])))
            else:
                self.o_stato.set_subtitle(tr("Stopped: ZETA will use an online service, if one is set up"))
            self.o_libera.set_sensitive(bool(d["caricati"]))
            self._o_modelli(d["modelli"])
        _in_thread(lavoro, fine)

    def _o_modelli(self, modelli):
        for r in self._righe_modelli:
            self.o_modelli.remove(r)
        self._righe_modelli = []
        in_uso = self._opz("ollama", "model", "") or (modelli[0]["nome"] if modelli else "")
        self.o_modelli.set_subtitle(tr("{n} · in use: {model}").format(n=len(modelli), model=in_uso)
                                    if modelli else tr("none: download one below"))
        for m in modelli:
            r = Adw.ActionRow(title=m["nome"], subtitle="%s · %s %s" % (
                _gb(m["gb"]), m["parametri"] or "", m["quantizzazione"] or ""))
            if m["nome"] == in_uso:
                r.add_suffix(Gtk.Label(label=tr("In Use"), css_classes=["dim-label"], valign=Gtk.Align.CENTER))
            else:
                usa = Gtk.Button(label=tr("Use"), valign=Gtk.Align.CENTER)
                usa.connect("clicked", lambda _b, n=m["nome"]: self._o_usa(n))
                r.add_suffix(usa)
            via = Gtk.Button(icon_name="edit-delete-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text=tr("Remove the model"), css_classes=["flat"])
            via.connect("clicked", lambda _b, n=m["nome"]: self._o_rimuovi(n))
            r.add_suffix(via)
            self.o_modelli.add_row(r)
            self._righe_modelli.append(r)

    def _o_usa(self, nome):
        self._salva_opz("ollama", "model", nome)
        self.toast(tr("ZETA will use the model {name}").format(name=nome))
        self._o_aggiorna()
        self._aggiorna_effettiva()

    def _o_rimuovi(self, nome):
        d = Adw.AlertDialog(heading=tr("Remove {name}?").format(name=nome),
                            body=tr("The model will be deleted from disk. You can download it again."))
        d.add_response("no", tr("Cancel"))
        d.add_response("si", tr("Remove"))
        d.set_response_appearance("si", Adw.ResponseAppearance.DESTRUCTIVE)

        def risposta(_d, r):
            if r != "si":
                return
            def fine(res):
                ok, msg = res if isinstance(res, tuple) else (False, str(res))
                self.toast(msg)
                if ok and self._opz("ollama", "model", "") == nome:
                    self._salva_opz("ollama", "model", "")
                self._o_aggiorna()
            _in_thread(lambda: og.rimuovi(nome), fine)
        d.connect("response", risposta)
        d.present(self.w)

    def _o_scarica(self, riga):
        nome = riga.get_text().strip()
        if not nome:
            return
        self._dl_fermo = False
        riga.set_sensitive(False)
        self.o_prog_riga.set_visible(True)
        self.o_prog_riga.set_title(tr("Downloading {name}").format(name=nome))
        self.o_prog.set_fraction(0)
        self.o_prog.set_text(tr("starting…"))

        def avanzamento(testo, frazione):
            def ui():
                self.o_prog.set_text(testo[:60])
                if frazione is not None:
                    self.o_prog.set_fraction(frazione)
                else:
                    self.o_prog.pulse()
                return False
            GLib.idle_add(ui)

        def fine(res):
            ok, msg = res if isinstance(res, tuple) else (False, str(res))
            riga.set_sensitive(True)
            self.o_prog_riga.set_visible(False)
            if ok:
                riga.set_text("")
            self.toast(msg)
            self._o_aggiorna()
        _in_thread(lambda: og.scarica(nome, avanzamento, lambda: self._dl_fermo), fine)

    def _o_avvia_ferma(self, b):
        azione = "stop" if self._o_attivo else "start"
        b.set_sensitive(False)

        def fine(res):
            ok, msg = res if isinstance(res, tuple) else (False, str(res))
            self.toast(msg)
            GLib.timeout_add(1500, lambda: (self._o_aggiorna(), self._aggiorna_effettiva(), False)[2])
        _in_thread(lambda: og.servizio(azione), fine)

    def _o_libera(self, b):
        b.set_sensitive(False)
        _in_thread(og.libera_memoria, lambda n: (self.toast(tr("Memory freed") if n else
                                                           tr("No model in memory")),
                                                 self._o_aggiorna()))

    # --- opzioni comuni (temperatura, lunghezza, tempo, streaming) -----------
    def _opzioni(self, pid, locale=False, dentro=None):
        """Righe delle opzioni. Con «dentro» (la scheda di un servizio) vanno
        direttamente li': libadwaita non mostra il contenuto di una riga
        espandibile messa dentro un'altra (provato: restava vuota)."""
        e = dentro or Adw.ExpanderRow(title=tr("Advanced Options"),
                                      subtitle=tr("Temperature, length, timeout, streaming"))

        def spin(titolo, sotto, chiave, predef, minimo, massimo, passo, cifre=0):
            r = Adw.SpinRow.new_with_range(minimo, massimo, passo)
            r.set_title(titolo)
            r.set_subtitle(sotto)
            r.set_digits(cifre)
            r.set_value(float(self._opz(pid, chiave, predef) or predef))
            r.connect("notify::value", lambda s, _p: self._salva_opz(
                pid, chiave, round(s.get_value(), cifre) if cifre else int(s.get_value())))
            e.add_row(r)

        spin(tr("Temperature"), tr("0 = precise, repeatable answers; 1 and above = more creative"),
             "temperature", 0.7, 0.0, 2.0, 0.1, 1)
        spin(tr("Maximum Reply Length"), tr("in tokens (about 3/4 of a word each)"),
             "max_tokens", 220 if locale else 4096, 16, 32768, 16)
        spin(tr("Maximum Wait Time"), tr("seconds; 0 = default (2 minutes, 5 when streaming)"),
             "timeout", 0, 0, 900, 5)
        if locale:
            spin(tr("Context"), tr("conversation tokens the model remembers; 0 = the model's "
                 "default. Larger = more memory used"), "context", 0, 0, 131072, 512)
        s = Adw.SwitchRow(title=tr("Streaming"), subtitle=tr("The reply appears as it's written"))
        s.set_active(bool(self._opz(pid, "stream", True)))
        s.connect("notify::active", lambda w, _p: self._salva_opz(pid, "stream", w.get_active()))
        e.add_row(s)
        return e

    def _bottone_prova(self, riga, pid):
        b = Gtk.Button(label=tr("Test"), valign=Gtk.Align.CENTER)

        def prova(btn):
            btn.set_sensitive(False)
            riga.set_subtitle(tr("testing…"))

            def fine(res):
                ok, msg = res if isinstance(res, tuple) else (False, str(res))
                btn.set_sensitive(True)
                riga.set_subtitle(("✓ " if ok else "✗ ") + msg)
            _in_thread(lambda: Registry().test(pid), fine)
        b.connect("clicked", prova)
        riga.add_suffix(b)

    # --- servizi in rete ----------------------------------------------------
    def _gruppo_cloud(self):
        g = Adw.PreferencesGroup(
            title=tr("Online Services"),
            description=tr("Keys are encrypted: only your user can read them, only on this "
                           "computer. Questions go only to the chosen service."))
        self._espansori = {}
        for pid, (_cls, nome, tipo) in CATALOG.items():
            if tipo != "cloud":
                continue
            e = Adw.ExpanderRow(title=nome, subtitle="…")
            self._espansori[pid] = e

            chiave = Adw.PasswordEntryRow(title=tr("API Key") if pid != "personalizzato"
                                          else tr("API Key (optional for services on this computer)"),
                                          show_apply_button=True)
            chiave.connect("apply", lambda r, p=pid: self._salva_chiave(p, r))
            e.add_row(chiave)
            togli = Adw.ActionRow(title=tr("Remove the saved key"))
            bt = Gtk.Button(label=tr("Remove"), valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
            bt.connect("clicked", lambda _b, p=pid: self._togli_chiave(p))
            togli.add_suffix(bt)
            e.add_row(togli)

            predef = modello_predefinito(pid)
            campi = [("model", tr("Model (default: {model})").format(model=predef) if predef
                      else tr("Model"))]
            campi.append(("endpoint",
                          tr("Service address, e.g. http://localhost:1234/v1/chat/completions")
                          if pid == "personalizzato"
                          else tr("Service address (empty = the official one)")))
            for k, titolo in campi:
                r = Adw.EntryRow(title=titolo, show_apply_button=True)
                r.set_text(str(self._opz(pid, k, "") or ""))
                r.connect("apply", lambda w, p=pid, k=k: (
                    self._salva_opz(p, k, w.get_text().strip()),
                    self.toast(tr("Saved: press “Test” to check")), self._stato_cloud(p)))
                e.add_row(r)
            self._opzioni(pid, dentro=e)
            prova = Adw.ActionRow(title=tr("Test Connection"),
                                  subtitle=tr("A real, very small request"))
            self._bottone_prova(prova, pid)
            e.add_row(prova)
            g.add(e)
            self._stato_cloud(pid)
        self.page.add(g)

    def _stato_cloud(self, pid):
        def lavoro():
            p = Registry().get(pid)
            return bool(p.config.api_key), p.config.model or modello_predefinito(pid)

        def fine(r):
            if isinstance(r, Exception):
                return
            ha, modello = r
            self._espansori[pid].set_subtitle(
                tr("key saved · {model}").format(model=modello) if ha else
                (tr("no key") if pid == "personalizzato" else tr("key missing")))
        _in_thread(lavoro, fine)

    def _salva_chiave(self, pid, riga):
        val = riga.get_text().strip()
        if not val:
            self.toast(tr("Enter the key before saving it"))
            return
        riga.set_sensitive(False)

        def fine(ok):
            riga.set_sensitive(True)
            if ok is True:
                riga.set_text("")
                self.toast(tr("Key saved ({where})").format(where=keyring_where().split(" (")[0]))
            else:
                self.toast(tr("Key NOT saved: try again, or see “zeta diagnose”"))
            self._stato_cloud(pid)
        _in_thread(lambda: keyring_set(pid, val), fine)

    def _togli_chiave(self, pid):
        _in_thread(lambda: keyring_set(pid, ""),
                   lambda ok: (self.toast(tr("Key removed") if ok is True else tr("Not removed")),
                               self._stato_cloud(pid), self._aggiorna_effettiva()))

    # --- comportamento ------------------------------------------------------
    def _gruppo_comportamento(self):
        g = Adw.PreferencesGroup(title=tr("ZETA Behavior"))
        e = Adw.ExpanderRow(title=tr("System Instructions"),
                            subtitle=tr("How ZETA introduces itself and behaves, with every service"))
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                          left_margin=8, right_margin=8)
        tv.get_buffer().set_text(self.reg.settings.get("system", DEFAULT_SYSTEM))
        sc = Gtk.ScrolledWindow(child=tv, min_content_height=130, margin_top=6, margin_bottom=6,
                                margin_start=6, margin_end=6)
        e.add_row(sc)
        pulsanti = Adw.ActionRow(title="")
        salva = Gtk.Button(label=tr("Save"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        ripristina = Gtk.Button(label=tr("Restore ZETA RAYS Defaults"), valign=Gtk.Align.CENTER)

        def _salva(_b):
            b = tv.get_buffer()
            testo = b.get_text(b.get_start_iter(), b.get_end_iter(), False).strip()
            s = dict(self.reg.settings)
            if testo and testo != DEFAULT_SYSTEM:
                s["system"] = testo
            else:
                s.pop("system", None)
            save_settings(s)
            self.reg.settings = s
            self.toast(tr("Instructions saved: they apply from the next question"))

        def _ripristina(_b):
            tv.get_buffer().set_text(DEFAULT_SYSTEM)
            _salva(None)
        salva.connect("clicked", _salva)
        ripristina.connect("clicked", _ripristina)
        pulsanti.add_suffix(ripristina)
        pulsanti.add_suffix(salva)
        e.add_row(pulsanti)
        g.add(e)
        g.add(Adw.ActionRow(title=tr("Conversation Memory"),
                            subtitle=tr("Stays on this computer (clear it with “zeta --forget”)")))
        self.gruppo_comportamento = g
        self.page.add(g)


def costruisci(finestra):
    """La pagina AI e il gruppo «Comportamento» (per aggiungervi altre righe)."""
    p = PaginaAI(finestra)
    return p.page, p.gruppo_comportamento
