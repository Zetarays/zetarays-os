# SPDX-License-Identifier: GPL-3.0-or-later
"""La catena di ZETA Core: richiesta -> capire -> azione -> verifica -> risposta.

  1. capire in locale (capire.py): millisecondi, senza rete;
  2. se non basta, il modello sceglie UNA azione dal catalogo (risposta JSON
     vincolata ai nomi delle capacita'); gli argomenti che sceglie devono
     comparire nella richiesta (niente nomi inventati);
  3. le azioni «conferma» chiedono il permesso prima;
  4. la risposta e' quella della verifica, mai un «fatto» di cortesia.
Ogni azione finisce in ~/.local/share/zeta/actions.log (le password no).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from . import capacita as C
from . import stato as S

LOG = os.path.expanduser("~/.local/share/zeta/actions.log")
SEGRETI = {"password", "psk", "chiave", "token"}


@dataclass
class Richiesta:
    """Cio' che si mostra quando serve una conferma (stessi campi di prima:
    la finestra di ZETA e il terminale li sanno gia' mostrare)."""
    preview: str
    impact: str
    ok: bool = True
    output: str = ""
    needs_confirmation: bool = True


def _registra(nome, args, esito, origine):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        sicuri = {k: ("***" if k in SEGRETI and v else v) for k, v in (args or {}).items()}
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "azione": nome, "args": sicuri,
                                "ok": esito.ok, "esito": esito.messaggio[:300], "origine": origine},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def esegui(nome, args, conferma=None, origine="locale", autorizzato=False) -> C.Esito:
    cap = C.REGISTRO.get(nome)
    if cap is None:
        return C.Esito(False, "Non so fare «%s»." % nome)
    args = {k: v for k, v in (args or {}).items() if v is not None and v != ""}
    manca = [p for p in cap.obbligatori if not args.get(p)]
    if manca:
        return C.Esito(False, "Mi manca un'informazione: %s." % ", ".join(cap.parametri.get(p, p) for p in manca))
    if cap.controlla:
        es = cap.controlla(args)
        if es is not None:
            _registra(nome, args, es, origine)
            return es
    if cap.rischio == "conferma" and not autorizzato:
        testo = cap.anteprima(args) if cap.anteprima else cap.descrizione
        r = Richiesta(preview=testo, impact="Serve la tua conferma.")
        if not (conferma and conferma(r)):
            es = C.Esito(False, "Annullato: non ho fatto nulla.")
            _registra(nome, args, es, origine)
            return es
    try:
        es = cap.esegui(args)
    except Exception as e:  # noqa: BLE001 - un'azione non deve mai far cadere ZETA
        es = C.Esito(False, "Errore durante «%s»: %s" % (nome, e))
    _registra(nome, args, es, origine)
    return es


def esegui_tutte(azioni, conferma=None, origine="locale") -> str:
    risposte = []
    for nome, args in azioni:
        es = esegui(nome, args, conferma, origine)
        risposte.append(es.messaggio)
        if not es.ok and len(azioni) > 1:
            risposte.append("Mi fermo qui: le azioni successive non le ho fatte.")
            break
    return "\n".join(risposte)


# ------------------------------------------------------------ il modello sceglie
def _catalogo(nomi=None):
    righe = []
    for c in C.REGISTRO.values():
        if nomi is not None and c.nome not in nomi:
            continue
        par = ", ".join("%s%s" % (k, "" if k in c.obbligatori else "?") for k in c.parametri)
        righe.append("%s(%s): %s" % (c.nome, par, c.descrizione))
    return "\n".join(righe)


ISTRUZIONI = (
    "Sei il motore di comandi di un sistema operativo. Leggi la richiesta dell'utente e scegli "
    "UNA azione dall'elenco, con i suoi argomenti presi dalle parole dell'utente. Se la richiesta "
    "non chiede di fare qualcosa sul computer (una domanda, una conversazione, un testo da scrivere), "
    "scegli \"nessuna\". Non inventare nomi di file, app o reti che l'utente non ha detto.\n"
    "Rispondi solo con JSON: {\"azione\": \"nome\", \"argomenti\": {...}}\n\nAzioni:\n")


# Parole che devono comparire nella richiesta perche' il modello possa
# scegliere quell'azione. Il modello locale e' piccolo: da solo sceglieva
# «screenshot» per qualunque frase (provato). Un'azione senza parole qui non
# puo' essere scelta dal modello: la fa solo la comprensione locale.
PAROLE = {
    "open_application": r"apr|avvi|lanc|usa|ascolt|guard",
    "close_application": r"chiud|esc|termin|basta|smetti",
    "restart_application": r"riavvi|riapr|ripart",
    "focus_application": r"pass|torn|vai|mostr|primo piano",
    "minimize_window": r"ridu|minimizz|nascond|togli di mezzo",
    "maximize_window": r"ingrand|massimizz|grande|allarg",
    "fullscreen_window": r"schermo intero|tutto schermo",
    "open_folder": r"apr|mostr|vedere|vedi|cartell|download|scaricat|document|immagin|foto|music|video|scrivania",
    "open_file": r"apr|mostr|vedere|legg|guard",
    "search_files": r"cerc|trov|dove|dov'",
    "show_location": r"dove|dov'|posizione",
    "create_folder": r"cre[ai]|nuov",
    "create_file": r"cre[ai]|nuov",
    "rename_item": r"rinomin|nome",
    "copy_item": r"copi|duplic",
    "move_item": r"spost|metti|trasfer",
    "delete_item": r"elimin|cancell|butt|cestin|rimuov",
    "open_settings": r"impostazion|preferenz|configur|settings",
    "set_volume": r"volum|audio|suono|muto|silenz|forte|piano|alza|abbass",
    "set_brightness": r"luminos|luce|scuro|chiaro|brightness",
    "set_theme": r"tema|scuro|chiaro|modalita",
    "lock_screen": r"blocc",
    "suspend_system": r"sospen|standby|dormi",
    "wifi_on": r"wi.?fi|wireless|rete",
    "wifi_off": r"wi.?fi|wireless|rete",
    "wifi_connect": r"connett|colleg|rete|wi.?fi",
    "wifi_disconnect": r"disconnett|scolleg|stacc",
    "wifi_list": r"reti|wi.?fi",
    "network_status": r"rete|internet|connes|colleg|ip",
    "bluetooth_on": r"bluetooth", "bluetooth_off": r"bluetooth", "bluetooth_devices": r"bluetooth|dispositiv",
    "bluetooth_connect": r"bluetooth|cuffi|auricolar|mouse|tastier|cass",
    "bluetooth_disconnect": r"bluetooth|cuffi|auricolar|mouse|tastier|cass",
    "system_status": r"ram|memoria|cpu|processore|disco|spazio|batteria|stato del|come sta il|come va il|lent",
    "list_processes": r"process|consum|rallent|lent|pesant|usa|occupa",
    "list_running_applications": r"apert|aperti|in esecuzione|finestre",
    "list_installed_applications": r"installat",
    "is_installed": r"installat|c'e|ce l",
    "current_time": r"ore|ora|giorno|data",
    "screenshot": r"screenshot|schermata|cattura",
    "dock_add": r"dock", "dock_remove": r"dock",
    "set_wallpaper": r"sfondo",
    "set_default_app": r"predefinit", "list_default_apps": r"predefinit",
    "open_url": r"sito|www|http|pagina|internet",
    "download_file": r"scaric|download",
}


def _plausibile(nome: str, testo: str) -> bool:
    import re
    p = PAROLE.get(nome)
    return bool(p and re.search(r"\b(?:%s)" % p, S.norm(testo)))


def _radicato(valore: str, testo: str) -> bool:
    """Un argomento scelto dal modello deve venire dalla richiesta."""
    v = [w for w in S.norm(str(valore)).replace(".", " ").split() if len(w) > 1]
    t = S.norm(testo)
    if not v:
        return True
    presenti = sum(1 for w in v if w in t)
    return presenti / len(v) >= 0.6


def scegli_con_modello(testo: str, provider) -> list | None:
    """Solo per il modello locale (Ollama): risposta JSON vincolata ai nomi."""
    try:
        from ..providers.ollama import OllamaProvider
    except ImportError:
        return None
    if not isinstance(provider, OllamaProvider) or not provider.available():
        return None
    import urllib.request
    # solo le azioni di cui la frase parla: se non ce n'e' nessuna si conversa
    # e basta, senza far aspettare una scelta inutile
    candidate = [n for n in C.REGISTRO if _plausibile(n, testo)]
    if not candidate:
        return None
    nomi = candidate + ["nessuna"]
    schema = {"type": "object", "properties": {"azione": {"type": "string", "enum": nomi},
                                                "argomenti": {"type": "object"}},
              "required": ["azione"]}
    corpo = {"model": provider._model(), "stream": False, "format": schema,
             "keep_alive": provider.KEEP_ALIVE,
             "options": {"temperature": 0, "num_predict": 120},
             "messages": [{"role": "system", "content": ISTRUZIONI + _catalogo(candidate)},
                          {"role": "user", "content": testo}]}
    try:
        req = urllib.request.Request(provider._base() + "/api/chat", data=json.dumps(corpo).encode(),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as r:
            risposta = json.loads(r.read().decode()).get("message", {}).get("content", "")
        scelta = json.loads(risposta)
    except Exception:  # noqa: BLE001 - se il modello non risponde si torna alla conversazione
        return None
    nome = scelta.get("azione")
    args = scelta.get("argomenti") or {}
    if nome not in C.REGISTRO or not isinstance(args, dict) or not _plausibile(nome, testo):
        return None
    cap = C.REGISTRO[nome]
    args = {k: v for k, v in args.items() if k in cap.parametri}
    for k, v in args.items():
        if isinstance(v, str) and k not in ("testo",) and not _radicato(v, testo):
            return None              # nome inventato: meglio chiedere che sbagliare
    if any(not args.get(p) for p in cap.obbligatori):
        return None
    return [(nome, args)]


# ------------------------------------------------------------ per i servizi in rete (tool calling)
class MotoreAgente:
    """Le capacita' come «strumenti» per i modelli che li sanno chiamare
    (Claude, OpenAI, Gemini...). Stessa interfaccia del vecchio motore."""

    def tool_specs(self):
        from ..providers.base import ToolSpec
        out = []
        for c in C.REGISTRO.values():
            props = {k: {"type": "string", "description": d} for k, d in c.parametri.items()}
            out.append(ToolSpec(name=c.nome, description=c.descrizione,
                                schema={"type": "object", "properties": props, "required": c.obbligatori}))
        return out

    def run(self, name, args, *, authorized=False):
        from ..actions import ActionResult
        cap = C.REGISTRO.get(name)
        if cap is None:
            return ActionResult(False, "Azione sconosciuta: %s" % name)
        args = {k: v for k, v in (args or {}).items() if v is not None and v != ""}
        if cap.controlla and not authorized:
            es = cap.controlla(args)
            if es is not None:
                return ActionResult(es.ok, es.messaggio)
        if cap.rischio == "conferma" and not authorized:
            testo = cap.anteprima(args) if cap.anteprima else cap.descrizione
            return ActionResult(True, "", needs_confirmation=True, preview=testo, impact="Serve la tua conferma.")
        es = esegui(name, args, None, origine="strumenti", autorizzato=True)
        return ActionResult(es.ok, es.messaggio)
