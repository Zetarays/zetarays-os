# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — ZETA.

Unisce provider, motore azioni e memoria. Gestisce il giro di conversazione con
strumenti (allowlist) e la conferma per le azioni di livello 3/4.
"""
from __future__ import annotations

import re
from typing import Callable

from . import intents
from .providers.ollama import MemoriaInsufficiente
from .actions import ActionEngine, ActionResult
from .memory import Memory
from .providers.base import ProviderError, Message, Provider, Reply, ToolCall
from .registry import Registry
from .agente import agente as _agente
from .agente.capire import capire as _capire

# Azioni del vecchio riconoscimento che restano utili e sicure (le altre le fa
# il nuovo agente, con la verifica): ricerca sul web e nei file, colore
# d'accento, schermo spento, informazioni. Risposte «di conoscenza» (action
# None, es. «come apro il terminale») restano valide.
_VECCHIE_OK = {"open_url", "search_content", "set_accent", "screen_off", "system_info", "uptime",
               "current_date", "open_system_monitor", "open_security", "volume_status",
               "battery_status", "disk_usage", "ip_address", "cpu_usage", "memory_usage"}

# azioni la cui uscita testuale È la risposta (informazioni), non un semplice "fatto"
_INFO_ACTIONS = {"cpu_usage", "memory_usage", "disk_usage", "ip_address",
                 "uptime", "system_info", "network_status", "list_applications",
                 "security_status", "process_list", "list_windows",
                 "current_time", "current_date", "battery_status",
                 "volume_status", "find_files", "set_volume"}


NOT_CONFIGURED = (
    "ZETA non ha ancora un modello collegato.\n"
    "Per usarlo apri Impostazioni › AI e inserisci la chiave di un servizio (Claude, OpenAI, Gemini),\n"
    "oppure installa Ollama con un modello locale, che funziona anche senza Internet.")


class Assistant:
    def __init__(self, provider: Provider | None = None):
        self.registry = Registry()
        self.provider = provider or self.registry.resolve_default()
        # strumenti per i modelli che sanno chiamarli: le capacita' dell'agente
        self.engine = _agente.MotoreAgente()
        self.vecchio = ActionEngine()
        self.memory = Memory()
        self.history: list[Message] = self._pulisci(self.memory.load_history())

    @classmethod
    def _pulisci(cls, storia: list[Message]) -> list[Message]:
        """Toglie dalla cronologia le risposte che erano chiamate di funzione
        scritte come testo (e la domanda che le aveva causate): rilette dal
        modello, lo spingevano a rispondere di nuovo cosi'."""
        out: list[Message] = []
        for m in storia:
            if m.role == "assistant" and cls._chiamata_grezza(m.content):
                if out and out[-1].role == "user":
                    out.pop()
                continue
            out.append(m)
        return out

    def local_command(self, text: str,
                      confirm: Callable[[ActionResult], bool] | None = None) -> str | None:
        """Esegue un comando riconosciuto localmente, senza modello AI.

        Prima il nuovo agente (azione vera + verifica); poi, per poche cose
        rimaste solo li', il vecchio riconoscimento. None = non e' un comando.
        """
        azioni = _capire(text)
        if azioni:
            return _agente.esegui_tutte(azioni, confirm, origine="locale")
        intent = intents.parse(text)
        if intent is None or (intent.action is not None and intent.action not in _VECCHIE_OK):
            return None
        if intent.action is None:
            # domanda con una risposta certa (dove si trova, come si fa):
            # si risponde e basta, senza eseguire nulla
            return intent.reply
        res = self.vecchio.run(intent.action, intent.args)
        if res.needs_confirmation:
            approved = confirm(res) if confirm else False
            if not approved:
                return "Operazione annullata."
            res = self.vecchio.run(intent.action, intent.args, authorized=True)
        if not res.ok:
            return "Non è riuscito: %s" % res.output
        out = (res.output or "").strip()
        if out and intent.action in _INFO_ACTIONS:
            return out
        return intent.reply

    def respond(self, text: str,
                confirm: Callable[[ActionResult], bool] | None = None,
                allow_ai: bool = True,
                on_text: Callable[[str], None] | None = None) -> str:
        """Un turno completo: prima i comandi locali, poi (se serve) il modello AI."""
        vuoto = self._non_dice_nulla(text)
        if vuoto is not None:
            return vuoto
        local = self.local_command(text, confirm)
        if local is not None:
            self.memory.save_turn(text, local, azione=True)
            return local
        if not allow_ai:
            return ("Non ho capito il comando. Prova ad esempio: «apri i documenti», "
                    "«quanta RAM sto usando», «apri il terminale», «chiudi la finestra».")
        # modello locale: sceglie un'azione dal catalogo (se la frase ne chiede
        # una), altrimenti si conversa. I servizi in rete usano gli strumenti.
        if not getattr(self.provider, "usa_strumenti", True):
            azioni = _agente.scegli_con_modello(text, self.provider)
            if azioni:
                risposta = _agente.esegui_tutte(azioni, confirm, origine="modello")
                self.memory.save_turn(text, risposta, azione=True)
                return risposta
        return self.ask(text, on_text=on_text, confirm=confirm)

    @staticmethod
    def _non_dice_nulla(text: str) -> str | None:
        """Scarta subito ciò su cui non c'è nulla da rispondere.

        Senza questo controllo una riga vuota o fatta di soli simboli finiva al
        modello linguistico: decine di secondi di attesa per una risposta senza
        senso.
        """
        t = (text or "").strip()
        if not t:
            return ("Non hai scritto nulla. Prova con «apri i documenti», "
                    "«che ore sono», «quanta RAM sto usando».")
        if not any(c.isalnum() for c in t):
            return ("Non ho capito «%s». Prova a scriverlo a parole: "
                    "«apri le impostazioni», «che ore sono»." % t[:30])
        return None

    def provider_label(self) -> str:
        p = self.provider
        extra = " (locale)" if p.config.kind == "local" else ""
        return "%s%s" % (p.config.label, extra)

    def ask(self, text: str, on_text: Callable[[str], None] | None = None,
            confirm: Callable[[ActionResult], bool] | None = None) -> str:
        """Un turno completo: invio, eventuali strumenti, risposta finale.

        `on_text` riceve i pezzi della risposta man mano che arrivano, quando
        il fornitore lo permette (streaming); altrimenti una volta sola, alla
        fine.
        """
        inizio = len(self.history)
        self.history.append(Message("user", text))
        if (on_text and not getattr(self.provider, "usa_strumenti", True)
                and getattr(self.provider.config, "stream", True)):
            final = self._stream_turn(on_text).strip()
            return self._chiudi_turno(text, final, inizio)
        tools = self.engine.tool_specs()

        # primo giro (con strumenti; senza streaming perché può servire un tool)
        reply = self._turn(tools)
        # eventuali azioni richieste
        guard = 0
        eseguite = bool(reply.tool_calls)
        while reply.tool_calls and guard < 6:
            guard += 1
            results = self._execute_tools(reply.tool_calls, confirm)
            self.history.append(Message("assistant", self._describe_calls(reply)))
            self.history.append(Message("user", self._format_results(results)))
            reply = self._turn(tools)

        final = reply.text.strip()
        if on_text and final and not self._chiamata_grezza(final):
            on_text(final)
        return self._chiudi_turno(text, final, inizio, eseguite)

    # Un modello piccolo, a volte, invece di rispondere scrive una chiamata di
    # funzione come testo: {"type":"function","name":...}. Mostrarla non
    # serve a nessuno, e salvarla nella cronologia e' peggio: il modello la
    # rilegge e continua a imitarla nelle risposte successive (visto davvero).
    @staticmethod
    def _chiamata_grezza(testo: str) -> bool:
        t = testo.lstrip()[:120].replace(" ", "")
        return t.startswith("{") and ('"function"' in t or t.startswith('{"name":'))

    # «Ho aperto Firefox» detto dal modello senza che nessuna azione sia
    # partita e' una bugia: il modello non tocca il computer. Si lascia la
    # risposta ma si dice chiaramente che non e' successo nulla.
    _PROMESSA = re.compile(
        r"(?i)(?:^\s*fatto\b|\b(?:ho|l'ho|li ho|le ho)\s+(?:gia'?\s+|appena\s+)?(?:aperto|chiuso|"
        r"eliminato|cancellato|creato|spostato|copiato|installato|disinstallato|spento|acceso|"
        r"riavviato|avviato|impostato|attivato|disattivato|collegato|scollegato|bloccato|"
        r"salvato|scaricato|rinominato|alzato|abbassato|cambiato)\b)")

    @classmethod
    def _onesta(cls, final: str, eseguite: bool) -> str:
        if eseguite or not final:
            return final
        # «non ho aperto nulla» e' onesto: contano solo le frasi affermative
        promesse = [m for m in cls._PROMESSA.finditer(final)
                    if not re.search(r"(?i)\bnon\s+(?:l'|li\s+|le\s+|lo\s+)?$", final[max(0, m.start() - 8):m.start()])]
        if not promesse:
            return final
        return (final + "\n\n(Nota: non ho eseguito nessuna azione sul computer. "
                "Se vuoi che la faccia, chiedimelo come comando, ad esempio «apri Firefox».)")

    def _chiudi_turno(self, text: str, final: str, inizio: int, eseguite: bool = False) -> str:
        final = self._onesta(final, eseguite)
        if self._chiamata_grezza(final):
            # tutto il turno resta fuori dalla cronologia: non ha avuto risposta
            del self.history[inizio:]
            return ("Non sono riuscito a capire la richiesta. Prova a dirla in "
                    "un altro modo, oppure con un comando: «apri il terminale», "
                    "«quanta RAM sto usando».")
        self.history.append(Message("assistant", final))
        self.memory.save_turn(text, final)
        return final

    # --- interni ---
    def _stream_turn(self, on_text: Callable[[str], None]) -> str:
        """Un giro in streaming. Gli errori diventano una risposta leggibile,
        come in `_turn`; se lo streaming si interrompe a meta' si tiene quello
        che e' gia' arrivato e si dice che manca il resto."""
        ricevuto: list[str] = []

        def pezzo(c: str) -> None:
            ricevuto.append(c)
            on_text(c)
        try:
            return self.provider.stream(self.history, pezzo).text
        except MemoriaInsufficiente as e:
            return str(e)
        except Exception:  # noqa: BLE001
            if ricevuto:
                return "".join(ricevuto) + "\n\n(La risposta si e' interrotta.)"
            return self._turn([]).text

    def _turn(self, tools) -> Reply:
        try:
            return self.provider.chat(self.history, tools)
        except MemoriaInsufficiente as e:
            # Caso tipico del sistema live: poca memoria e niente scambio su
            # disco. Si dice com'è, invece di far arrancare il computer.
            return Reply(text=str(e))
        except ProviderError as e:
            # 1) modello predefinito che non esiste piu': se ne sceglie uno
            #    fra quelli che il servizio offre davvero e si riprova
            if self._ripiega_su_altro_modello(e):
                try:
                    return self.provider.chat(self.history, tools)
                except ProviderError as e2:
                    e = e2
            # 2) servizio in rete irraggiungibile: risponde il modello locale
            locale = self._risposta_locale(e)
            if locale is not None:
                return locale
            # 3) altrimenti il motivo VERO (chiave non valida, modello non
            #    trovato, troppe richieste...): prima diventava sempre «non
            #    riesco a contattare… controlla la connessione», anche con la
            #    chiave sbagliata
            return Reply(text=str(e))
        except Exception:  # noqa: BLE001
            if not self.provider.available():
                return Reply(text=NOT_CONFIGURED)
            return Reply(text="Non riesco a contattare %s in questo momento. Controlla la connessione "
                              "a Internet o la configurazione in Impostazioni › AI." % self.provider_label())

    def _ripiega_su_altro_modello(self, e: "ProviderError") -> bool:
        """Solo se l'utente non ha scelto un modello (si usa il predefinito) e il
        servizio dice che il modello non c'e'. Il modello trovato si salva."""
        msg = str(e).lower()
        if self.provider.config.model or e.status not in (400, 404):
            return False
        if not any(k in msg for k in ("model", "modello", "not found", "non trovato")):
            return False
        from .providers.base import scegli_modello
        nome = self.provider.config.name
        scelto = scegli_modello(nome, self.provider.modelli_offerti())
        if not scelto:
            return False
        self.provider.config.model = scelto
        try:
            self.registry.set_option(nome, "model", scelto)
        except Exception:  # noqa: BLE001 - vale comunque per questa sessione
            pass
        return True

    def _risposta_locale(self, e: "ProviderError") -> Reply | None:
        """Rete assente o servizio fuori uso (non: chiave sbagliata, limiti): se
        il modello locale c'e', risponde lui e lo si dice."""
        if self.provider.config.kind != "cloud" or not e.retryable or e.status == 429:
            return None
        try:
            locale = self.registry.get("ollama")
            if not locale.available():
                return None
            r = locale.chat(self.history, None)
        except Exception:  # noqa: BLE001
            return None
        r.text = ("(%s non risponde: %s Ha risposto il modello locale.)\n\n%s"
                  % (self.provider_label(), str(e).split(":", 1)[-1].strip(), r.text))
        return r

    def _execute_tools(self, calls: list[ToolCall],
                       confirm: Callable[[ActionResult], bool] | None) -> list[tuple[str, ActionResult]]:
        out = []
        for call in calls:
            res = self.engine.run(call.name, call.arguments)
            if res.needs_confirmation:
                approved = confirm(res) if confirm else False
                if approved:
                    res = self.engine.run(call.name, call.arguments, authorized=True)
                else:
                    res = ActionResult(False, "Azione annullata dall'utente.")
            out.append((call.name, res))
        return out

    def _describe_calls(self, reply: Reply) -> str:
        return reply.text or "Eseguo le azioni richieste."

    def _format_results(self, results: list[tuple[str, ActionResult]]) -> str:
        parts = []
        for name, res in results:
            head = "OK" if res.ok else "ERRORE"
            parts.append("[%s] %s: %s" % (head, name, res.output))
        return "\n".join(parts)
