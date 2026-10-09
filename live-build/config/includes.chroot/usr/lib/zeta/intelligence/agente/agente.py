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

from i18n import tr

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
        if os.path.exists(LOG) and os.path.getsize(LOG) > 1_000_000:
            os.replace(LOG, LOG + ".1")          # il registro resta corto
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "azione": nome, "args": sicuri,
                                "ok": esito.ok, "esito": esito.messaggio[:300], "origine": origine},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def esegui(nome, args, conferma=None, origine="locale", autorizzato=False) -> C.Esito:
    cap = C.REGISTRO.get(nome)
    if cap is None:
        return C.Esito(False, tr("I don't know how to do “{action}”.").format(action=nome))
    args = {k: v for k, v in (args or {}).items() if v is not None and v != ""}
    manca = [p for p in cap.obbligatori if not args.get(p)]
    if manca:
        return C.Esito(False, tr("I'm missing some information: {what}.").format(
            what=", ".join(C.etichetta(p) for p in manca)))
    if cap.controlla:
        es = cap.controlla(args)
        if es is not None:
            _registra(nome, args, es, origine)
            return es
    if cap.rischio == "conferma" and not autorizzato:
        testo = cap.anteprima(args) if cap.anteprima else cap.descrizione
        r = Richiesta(preview=testo, impact=tr("Your confirmation is needed."))
        if not (conferma and conferma(r)):
            es = C.Esito(False, tr("Canceled: nothing was done."))
            _registra(nome, args, es, origine)
            return es
    try:
        es = cap.esegui(args)
    except Exception as e:  # noqa: BLE001 - un'azione non deve mai far cadere ZETA
        es = C.Esito(False, tr("Error during “{action}”: {error}").format(action=nome, error=e))
    _registra(nome, args, es, origine)
    return es


def esegui_tutte(azioni, conferma=None, origine="locale") -> str:
    risposte = []
    for nome, args in azioni:
        es = esegui(nome, args, conferma, origine)
        risposte.append(es.messaggio)
        if not es.ok and len(azioni) > 1:
            risposte.append(tr("Stopping here: I didn't do the remaining actions."))
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
    "You are the command engine of an operating system. Read the user's request (it may be in any "
    "language) and choose ONE action from the list, with its arguments taken from the user's words. "
    "Copy argument values exactly as the user wrote them, in the user's language: do not translate them. "
    "If the request does not ask to do something on the computer (a question, a conversation, a text "
    "to write), choose \"nessuna\". Never invent file, app or network names the user did not say.\n"
    "Answer only with JSON: {\"azione\": \"name\", \"argomenti\": {...}}\n\nActions:\n")


# Parole che devono comparire nella richiesta perche' il modello possa
# scegliere quell'azione. Il modello locale e' piccolo: da solo sceglieva
# «screenshot» per qualunque frase (provato). Un'azione senza parole qui non
# puo' essere scelta dal modello: la fa solo la comprensione locale.
# Italiano e inglese: la richiesta puo' arrivare in tutte e due le lingue.
PAROLE = {
    "open_application": r"apr|avvi|lanc|usa|ascolt|guard|open|launch|start|run|use|listen|watch|play",
    "close_application": r"chiud|esc|termin|basta|smetti|close|quit|exit|stop",
    "restart_application": r"riavvi|riapr|ripart|restart|reopen|relaunch",
    "focus_application": r"pass|torn|vai|mostr|primo piano|switch|go to|go back|bring|show|focus",
    "minimize_window": r"ridu|minimizz|nascond|togli di mezzo|minimi[sz]|hide|out of the way",
    "maximize_window": r"ingrand|massimizz|grande|allarg|maximi[sz]|enlarge|bigger",
    "fullscreen_window": r"schermo intero|tutto schermo|full ?screen",
    "open_folder": r"apr|mostr|vedere|vedi|cartell|download|scaricat|document|immagin|foto|music|video|scrivania|"
                   r"open|show|see|folder|picture|photo|desktop",
    "open_file": r"apr|mostr|vedere|legg|guard|open|show|see|read|view",
    "search_files": r"cerc|trov|dove|dov'|search|find|look for|where|locate",
    "show_location": r"dove|dov'|posizione|where|location",
    "create_folder": r"cre[ai]|nuov|create|make|new",
    "create_file": r"cre[ai]|nuov|create|make|new",
    "rename_item": r"rinomin|nome|rename|name",
    "copy_item": r"copi|duplic|copy|duplicat",
    "move_item": r"spost|metti|trasfer|move|put|transfer",
    "delete_item": r"elimin|cancell|butt|cestin|rimuov|delet|remov|trash|erase|throw",
    "open_settings": r"impostazion|preferenz|configur|settings|preferenc",
    "set_volume": r"volum|audio|suono|muto|silenz|forte|piano|alza|abbass|sound|mute|unmute|silen|loud|quiet|"
                  r"turn up|turn down",
    "set_brightness": r"luminos|luce|scuro|chiaro|brightness|bright|dim|dark|light",
    "set_theme": r"tema|scuro|chiaro|modalita|theme|dark|light|mode",
    "lock_screen": r"blocc|lock",
    "suspend_system": r"sospen|standby|dormi|suspend|sleep",
    "wifi_on": r"wi.?fi|wireless|rete|network",
    "wifi_off": r"wi.?fi|wireless|rete|network",
    "wifi_connect": r"connett|colleg|rete|wi.?fi|connect|join|network",
    "wifi_disconnect": r"disconnett|scolleg|stacc|disconnect",
    "wifi_list": r"reti|wi.?fi|networks",
    "network_status": r"rete|internet|connes|colleg|ip|network|connect|online",
    "bluetooth_on": r"bluetooth", "bluetooth_off": r"bluetooth",
    "bluetooth_devices": r"bluetooth|dispositiv|device",
    "bluetooth_connect": r"bluetooth|cuffi|auricolar|mouse|tastier|cass|headphone|earbud|headset|keyboard|speaker",
    "bluetooth_disconnect": r"bluetooth|cuffi|auricolar|mouse|tastier|cass|headphone|earbud|headset|keyboard|speaker",
    "system_status": r"ram|memoria|cpu|processore|disco|spazio|batteria|stato del|come sta il|come va il|lent|"
                     r"memory|processor|disk|space|storage|battery|status|slow",
    "list_processes": r"process|consum|rallent|lent|pesant|usa|occupa|slow|heavy|using|hog",
    "list_running_applications": r"apert|aperti|in esecuzione|finestre|running|windows",
    "list_installed_applications": r"installat|installed",
    "is_installed": r"installat|c'e|ce l|installed|do i have",
    "current_time": r"ore|ora|giorno|data|time|day|date|clock",
    "screenshot": r"screenshot|schermata|cattura|screen ?shot|capture",
    "dock_add": r"dock", "dock_remove": r"dock",
    "set_wallpaper": r"sfondo|wallpaper|background",
    "set_default_app": r"predefinit|default", "list_default_apps": r"predefinit|default",
    "open_url": r"sito|www|http|pagina|internet|site|web|page",
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
            return ActionResult(False, tr("Unknown action: {name}").format(name=name))
        args = {k: v for k, v in (args or {}).items() if v is not None and v != ""}
        if cap.controlla and not authorized:
            es = cap.controlla(args)
            if es is not None:
                return ActionResult(es.ok, es.messaggio)
        if cap.rischio == "conferma" and not authorized:
            testo = cap.anteprima(args) if cap.anteprima else cap.descrizione
            return ActionResult(True, "", needs_confirmation=True, preview=testo,
                                impact=tr("Your confirmation is needed."))
        es = esegui(name, args, None, origine="strumenti", autorizzato=True)
        return ActionResult(es.ok, es.messaggio)
