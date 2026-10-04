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
            title="Intelligenza attiva",
            description="Automatica usa Ollama, il modello sul computer, che funziona anche "
                        "senza Internet; se non è disponibile, il primo servizio in rete con una chiave.")
        self.ids = ["auto"] + list(CATALOG)
        nomi = ["Automatica (Ollama, sul computer)"] + [
            "%s (%s)" % (CATALOG[p][1], "sul computer" if CATALOG[p][2] == "local" else "in rete")
            for p in CATALOG]
        riga = Adw.ComboRow(title="ZETA usa", model=Gtk.StringList.new(nomi))
        attuale = self.reg.settings.get("default", "auto") or "auto"
        riga.set_selected(self.ids.index(attuale) if attuale in self.ids else 0)
        self.riga_effettiva = Adw.ActionRow(title="In uso adesso", subtitle="…")

        def scegli(c, _p):
            pid = self.ids[c.get_selected()]
            try:
                self.reg.scegli(pid)
            except (ValueError, OSError) as e:
                self.toast("Scelta non salvata: %s" % e)
                return
            self.toast("ZETA userà %s" % ("la scelta automatica" if pid == "auto" else CATALOG[pid][1]))
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
            return "%s · modello %s" % (p.config.label, modello or "predefinito")
        _in_thread(lavoro, lambda r: self.riga_effettiva.set_subtitle(
            r if isinstance(r, str) else "non determinabile"))

    # --- Ollama -------------------------------------------------------------
    def _gruppo_ollama(self):
        g = Adw.PreferencesGroup(title="Ollama · sul computer",
                                 description="Le domande restano su questo computer.")
        self.o_stato = Adw.ActionRow(title="Stato", subtitle="controllo…")
        self.o_avvia = Gtk.Button(valign=Gtk.Align.CENTER, sensitive=False)
        self.o_avvia.connect("clicked", self._o_avvia_ferma)
        self.o_libera = Gtk.Button(label="Libera memoria", valign=Gtk.Align.CENTER,
                                   tooltip_text="Toglie il modello dalla memoria: resta installato "
                                                "e si ricarica alla prossima domanda")
        self.o_libera.connect("clicked", self._o_libera)
        self.o_stato.add_suffix(self.o_libera)
        self.o_stato.add_suffix(self.o_avvia)
        g.add(self.o_stato)

        self.o_modelli = Adw.ExpanderRow(title="Modelli installati", subtitle="…")
        g.add(self.o_modelli)
        self._righe_modelli = []

        self.o_scarica = Adw.EntryRow(title="Scarica un modello (es. llama3.2:3b, qwen2.5:1.5b)",
                                      show_apply_button=True)
        self.o_scarica.connect("apply", self._o_scarica)
        g.add(self.o_scarica)
        self.o_prog_riga = Adw.ActionRow(title="Download", visible=False)
        self.o_prog = Gtk.ProgressBar(valign=Gtk.Align.CENTER, hexpand=True, show_text=True)
        self.o_ferma_dl = Gtk.Button(label="Annulla", valign=Gtk.Align.CENTER)
        self.o_ferma_dl.connect("clicked", lambda *_: setattr(self, "_dl_fermo", True))
        self.o_prog_riga.add_suffix(self.o_prog)
        self.o_prog_riga.add_suffix(self.o_ferma_dl)
        g.add(self.o_prog_riga)

        g.add(self._opzioni("ollama", locale=True))
        prova = Adw.ActionRow(title="Prova il collegamento", subtitle="Una domanda breve al modello")
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
                self.o_stato.set_subtitle("Errore: %s" % d)
                return
            if not d["inst"]:
                self.o_stato.set_subtitle("Ollama non è installato")
                self.o_avvia.set_visible(False)
                self.o_libera.set_visible(False)
                return
            self.o_avvia.set_sensitive(True)
            self.o_avvia.set_label("Ferma" if d["attivo"] else "Avvia")
            if d["attivo"]:
                car = ", ".join("%s (%s)" % (m["nome"], _gb(m["gb"])) for m in d["caricati"])
                self.o_stato.set_subtitle(
                    "Attivo · versione %s · %s · processi: %s di RAM" % (
                        d["ver"] or "?", ("in memoria: " + car) if car else "nessun modello in memoria",
                        _gb(d["ris"]["ram_gb"])))
            else:
                self.o_stato.set_subtitle("Fermo: ZETA userà un servizio in rete, se configurato")
            self.o_libera.set_sensitive(bool(d["caricati"]))
            self._o_modelli(d["modelli"])
        _in_thread(lavoro, fine)

    def _o_modelli(self, modelli):
        for r in self._righe_modelli:
            self.o_modelli.remove(r)
        self._righe_modelli = []
        in_uso = self._opz("ollama", "model", "") or (modelli[0]["nome"] if modelli else "")
        self.o_modelli.set_subtitle(("%d · in uso: %s" % (len(modelli), in_uso)) if modelli
                                    else "nessuno: scaricane uno qui sotto")
        for m in modelli:
            r = Adw.ActionRow(title=m["nome"], subtitle="%s · %s %s" % (
                _gb(m["gb"]), m["parametri"] or "", m["quantizzazione"] or ""))
            if m["nome"] == in_uso:
                r.add_suffix(Gtk.Label(label="In uso", css_classes=["dim-label"], valign=Gtk.Align.CENTER))
            else:
                usa = Gtk.Button(label="Usa", valign=Gtk.Align.CENTER)
                usa.connect("clicked", lambda _b, n=m["nome"]: self._o_usa(n))
                r.add_suffix(usa)
            via = Gtk.Button(icon_name="edit-delete-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="Rimuovi il modello", css_classes=["flat"])
            via.connect("clicked", lambda _b, n=m["nome"]: self._o_rimuovi(n))
            r.add_suffix(via)
            self.o_modelli.add_row(r)
            self._righe_modelli.append(r)

    def _o_usa(self, nome):
        self._salva_opz("ollama", "model", nome)
        self.toast("ZETA userà il modello %s" % nome)
        self._o_aggiorna()
        self._aggiorna_effettiva()

    def _o_rimuovi(self, nome):
        d = Adw.AlertDialog(heading="Rimuovere %s?" % nome,
                            body="Il modello viene cancellato dal disco. Si potrà riscaricare.")
        d.add_response("no", "Annulla")
        d.add_response("si", "Rimuovi")
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
        self.o_prog_riga.set_title("Download di %s" % nome)
        self.o_prog.set_fraction(0)
        self.o_prog.set_text("inizio…")

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
        azione = "stop" if b.get_label() == "Ferma" else "start"
        b.set_sensitive(False)

        def fine(res):
            ok, msg = res if isinstance(res, tuple) else (False, str(res))
            self.toast(msg)
            GLib.timeout_add(1500, lambda: (self._o_aggiorna(), self._aggiorna_effettiva(), False)[2])
        _in_thread(lambda: og.servizio(azione), fine)

    def _o_libera(self, b):
        b.set_sensitive(False)
        _in_thread(og.libera_memoria, lambda n: (self.toast("Memoria liberata" if n else
                                                           "Nessun modello in memoria"),
                                                 self._o_aggiorna()))

    # --- opzioni comuni (temperatura, lunghezza, tempo, streaming) -----------
    def _opzioni(self, pid, locale=False, dentro=None):
        """Righe delle opzioni. Con «dentro» (la scheda di un servizio) vanno
        direttamente li': libadwaita non mostra il contenuto di una riga
        espandibile messa dentro un'altra (provato: restava vuota)."""
        e = dentro or Adw.ExpanderRow(title="Opzioni avanzate",
                                      subtitle="Temperatura, lunghezza, tempo massimo, streaming")

        def spin(titolo, sotto, chiave, predef, minimo, massimo, passo, cifre=0):
            r = Adw.SpinRow.new_with_range(minimo, massimo, passo)
            r.set_title(titolo)
            r.set_subtitle(sotto)
            r.set_digits(cifre)
            r.set_value(float(self._opz(pid, chiave, predef) or predef))
            r.connect("notify::value", lambda s, _p: self._salva_opz(
                pid, chiave, round(s.get_value(), cifre) if cifre else int(s.get_value())))
            e.add_row(r)

        spin("Temperatura", "0 = risposte precise e ripetibili, 1 e oltre = più creative",
             "temperature", 0.7, 0.0, 2.0, 0.1, 1)
        spin("Lunghezza massima della risposta", "in token (circa 3/4 di parola ciascuno)",
             "max_tokens", 220 if locale else 4096, 16, 32768, 16)
        spin("Tempo massimo di attesa", "secondi; 0 = normale (2 minuti, 5 in streaming)",
             "timeout", 0, 0, 900, 5)
        if locale:
            spin("Contesto", "token di conversazione ricordati dal modello; 0 = quello del "
                 "modello. Più grande = più memoria occupata", "context", 0, 0, 131072, 512)
        s = Adw.SwitchRow(title="Streaming", subtitle="La risposta compare mentre viene scritta")
        s.set_active(bool(self._opz(pid, "stream", True)))
        s.connect("notify::active", lambda w, _p: self._salva_opz(pid, "stream", w.get_active()))
        e.add_row(s)
        return e

    def _bottone_prova(self, riga, pid):
        b = Gtk.Button(label="Prova", valign=Gtk.Align.CENTER)

        def prova(btn):
            btn.set_sensitive(False)
            riga.set_subtitle("provo…")

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
            title="Servizi in rete",
            description="Le chiavi sono cifrate: le legge solo il tuo utente, solo su questo "
                        "computer. Le domande vanno solo al servizio scelto.")
        self._espansori = {}
        for pid, (_cls, nome, tipo) in CATALOG.items():
            if tipo != "cloud":
                continue
            e = Adw.ExpanderRow(title=nome, subtitle="…")
            self._espansori[pid] = e

            chiave = Adw.PasswordEntryRow(title="Chiave API" if pid != "personalizzato"
                                          else "Chiave API (facoltativa per servizi sul computer)",
                                          show_apply_button=True)
            chiave.connect("apply", lambda r, p=pid: self._salva_chiave(p, r))
            e.add_row(chiave)
            togli = Adw.ActionRow(title="Rimuovi la chiave salvata")
            bt = Gtk.Button(label="Rimuovi", valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
            bt.connect("clicked", lambda _b, p=pid: self._togli_chiave(p))
            togli.add_suffix(bt)
            e.add_row(togli)

            predef = modello_predefinito(pid)
            campi = [("model", "Modello" + (" (predefinito: %s)" % predef if predef else ""))]
            campi.append(("endpoint", "Indirizzo del servizio" + (
                ", es. http://localhost:1234/v1/chat/completions" if pid == "personalizzato"
                else " (vuoto = quello ufficiale)")))
            for k, titolo in campi:
                r = Adw.EntryRow(title=titolo, show_apply_button=True)
                r.set_text(str(self._opz(pid, k, "") or ""))
                r.connect("apply", lambda w, p=pid, k=k: (
                    self._salva_opz(p, k, w.get_text().strip()),
                    self.toast("Salvato: premi «Prova» per verificare"), self._stato_cloud(p)))
                e.add_row(r)
            self._opzioni(pid, dentro=e)
            prova = Adw.ActionRow(title="Prova il collegamento",
                                  subtitle="Una richiesta vera, piccolissima")
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
                ("chiave salvata · %s" % modello) if ha else
                ("senza chiave" if pid == "personalizzato" else "manca la chiave"))
        _in_thread(lavoro, fine)

    def _salva_chiave(self, pid, riga):
        val = riga.get_text().strip()
        if not val:
            self.toast("Scrivi la chiave prima di salvarla")
            return
        riga.set_sensitive(False)

        def fine(ok):
            riga.set_sensitive(True)
            if ok is True:
                riga.set_text("")
                self.toast("Chiave salvata (%s)" % keyring_where().split(" (")[0])
            else:
                self.toast("Chiave NON salvata: riprova, o guarda «zeta diagnose»")
            self._stato_cloud(pid)
        _in_thread(lambda: keyring_set(pid, val), fine)

    def _togli_chiave(self, pid):
        _in_thread(lambda: keyring_set(pid, ""),
                   lambda ok: (self.toast("Chiave rimossa" if ok is True else "Non rimossa"),
                               self._stato_cloud(pid), self._aggiorna_effettiva()))

    # --- comportamento ------------------------------------------------------
    def _gruppo_comportamento(self):
        g = Adw.PreferencesGroup(title="Comportamento di ZETA")
        e = Adw.ExpanderRow(title="Istruzioni di sistema",
                            subtitle="Come ZETA si presenta e si comporta, con ogni servizio")
        tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                          left_margin=8, right_margin=8)
        tv.get_buffer().set_text(self.reg.settings.get("system", DEFAULT_SYSTEM))
        sc = Gtk.ScrolledWindow(child=tv, min_content_height=130, margin_top=6, margin_bottom=6,
                                margin_start=6, margin_end=6)
        e.add_row(sc)
        pulsanti = Adw.ActionRow(title="")
        salva = Gtk.Button(label="Salva", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        ripristina = Gtk.Button(label="Ripristina quelle di ZETA RAYS", valign=Gtk.Align.CENTER)

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
            self.toast("Istruzioni salvate: valgono dalla prossima domanda")

        def _ripristina(_b):
            tv.get_buffer().set_text(DEFAULT_SYSTEM)
            _salva(None)
        salva.connect("clicked", _salva)
        ripristina.connect("clicked", _ripristina)
        pulsanti.add_suffix(ripristina)
        pulsanti.add_suffix(salva)
        e.add_row(pulsanti)
        g.add(e)
        g.add(Adw.ActionRow(title="Memoria delle conversazioni",
                            subtitle="Resta su questo computer (si cancella con «zeta --oblio»)"))
        self.gruppo_comportamento = g
        self.page.add(g)


def costruisci(finestra):
    """La pagina AI e il gruppo «Comportamento» (per aggiungervi altre righe)."""
    p = PaginaAI(finestra)
    return p.page, p.gruppo_comportamento
