# SPDX-License-Identifier: GPL-3.0-or-later
"""Capire la richiesta, in locale: frase -> [(capacita', argomenti)].

Veloce (millisecondi), senza rete, deterministico. Riconosce il verbo, poi
l'oggetto; i nomi (app, cartelle, file) si controllano sul sistema vero
nelle capacita'. Frasi composte («apri firefox e chiudi il terminale»)
diventano piu' azioni in fila. Se non capisce restituisce None: allora si
chiede al modello di scegliere fra le stesse capacita'.
"""
from __future__ import annotations

import os
import re

from . import stato as S

# parole di cortesia all'inizio e alla fine: si tolgono
_INIZIO = re.compile(r"^(?:(?:zeta|ehi|ok|allora|per favore|per piacere|puoi|potresti|mi puoi|"
                     r"riesci a|vorrei|voglio|devi|please|can you)[ ,]+)+")
_FONDO = re.compile(r"[ ,]*(?:per favore|per piacere|grazie|please|subito|adesso)?[ .!?]*$")

# verbi (dopo norm: minuscole, senza accenti)
V_APRI = r"(?:apri|aprimi|avvia|avviami|lancia|fai partire|esegui|open|launch|start)"
V_CHIUDI = r"(?:chiudi|chiudimi|esci da|termina|quit|close)"
V_RIAVVIA = r"(?:riavvia|riapri|restart|reboot)"
V_PASSA = r"(?:passa a|vai su|vai a|torna a|torna su|metti in primo piano|mostrami|switch to|focus)"
V_CREA = r"(?:crea|creami|fai|nuova|nuovo|create|make)"
V_CERCA = r"(?:cerca|cercami|trova|trovami|dove si trova|dov'e|dove e|search|find)"
V_ELIMINA = r"(?:elimina|cancella|rimuovi il file|rimuovi la cartella|butta|cestina|delete)"
V_ACCENDI = r"(?:accendi|attiva|abilita|turn on|enable)"
V_SPEGNI = r"(?:spegni|disattiva|disabilita|turn off|disable)"

_ART = r"(?:il |lo |la |l'|i |gli |le |un |una |uno |del |della |dello |dei |delle )?"
_COMPUTER = r"(?:il |lo )?(?:computer|pc|sistema|portatile|mini pc)"


def _pulisci(testo):
    t = S.norm(testo)
    t = t.replace("’", "'")
    t = _INIZIO.sub("", t)
    t = _FONDO.sub("", t)
    return t.strip()


def _numero(t):
    m = re.search(r"(\d{1,3})\s*(?:%|per ?cento)?", t)
    return int(m.group(1)) if m else None


def _luogo(t):
    """«sulla scrivania», «nei documenti», «in download» -> nome del luogo."""
    m = re.search(r"\b(?:sulla|sul|nella|nel|nei|negli|in|dentro|su|alla|al|dalla|dal|dai)\s+"
                  r"(?:cartella\s+)?(scrivania|desktop|documenti|download|downloads|scaricati|immagini|"
                  r"foto|musica|video|home|cartella personale|modelli|pubblici)\b", t)
    return m.group(1) if m else None


def _togli_luogo(t):
    return re.sub(r"\s+(?:sulla|sul|nella|nel|nei|negli|in|dentro|su|alla|al|dalla|dal|dai)\s+"
                  r"(?:cartella\s+)?(?:scrivania|desktop|documenti|download|downloads|scaricati|immagini|"
                  r"foto|musica|video|home|cartella personale|modelli|pubblici)\b", "", t).strip()


# Un nome che contiene «e poi», «poi», «e apri…» non e' un nome: e' il resto di
# una frase composta non capita. «crea una cartella viaggi e poi aprila»
# creava la cartella «viaggi e poi aprila» (visto). Meglio non capire.
_COLLANTE = re.compile(r"\b(?:e poi|poi|e dopo|dopodiche|e (?:apri|chiudi|avvia|elimina|sposta|copia|mostra)\w*)\b")


def _nome_valido(n):
    return bool(n) and not _COLLANTE.search(n)


def _nome_oggetto(t):
    """toglie «il file», «la cartella», articoli e virgolette"""
    t = re.sub(r"^(?:il |lo |la |l'|i |gli |le |un |una |uno )?(?:file |cartella |documento |immagine |foto )?",
               "", t.strip())
    return t.strip().strip("«»\"'")


def _sistema(t):
    """Energia: solo se si nomina il computer (o il verbo e' da solo)."""
    if re.fullmatch(r"(?:riavvia|reboot|restart)(?: " + _COMPUTER + r")?", t) or \
            re.fullmatch(r"(?:riavvia(?:mi)?|fai ripartire) " + _COMPUTER, t):
        return "restart_system", {}
    if re.fullmatch(r"(?:spegni|arresta|shutdown|spegnimento)(?: " + _COMPUTER + r")?", t):
        return "shutdown_system", {}
    if re.fullmatch(r"(?:sospendi|metti in (?:sospensione|standby)|standby|vai in standby)(?: " + _COMPUTER + r")?", t):
        return "suspend_system", {}
    if re.fullmatch(r"(?:blocca|lock)(?: " + _COMPUTER + r"| lo schermo| la sessione| schermo)?", t):
        return "lock_screen", {}
    if re.fullmatch(r"(?:esci|disconnettimi|logout|log out|chiudi la sessione|esci dalla sessione|"
                    r"termina la sessione)(?: dalla sessione)?", t):
        return "logout", {}
    return None


def _rete(t):
    wifi = r"(?:il |la )?(?:wi[ -]?fi|rete wireless|wireless)"
    if re.fullmatch(V_ACCENDI + " " + wifi, t):
        return "wifi_on", {}
    if re.fullmatch(V_SPEGNI + " " + wifi, t):
        return "wifi_off", {}
    if re.fullmatch(r"(?:disconnetti|scollega|staccati da|disconnettiti da)(?:ti)?(?: dal| dalla| il| la)? "
                    r"(?:wi[ -]?fi|rete(?: wi[ -]?fi)?|internet)", t):
        return "wifi_disconnect", {}
    m = re.fullmatch(r"(?:connetti|collega|connettiti|collegati|connect)(?:ti)?(?: al| alla| a)? "
                     r"(?:(?:rete )?(?:wi[ -]?fi )?|rete )?(.+?)(?: con (?:la )?password (.+))?", t)
    if m and not re.match(r"(?:le |il |la |lo |i )?(?:cuffie|auricolari|mouse|tastiera|casse|altoparlant|"
                          r"telefono|dispositivo|bluetooth)", m.group(1)):
        return "wifi_connect", {"rete": m.group(1).strip("«»\"' "), "password": m.group(2)}
    if re.search(r"\b(?:reti|wi[ -]?fi) (?:disponibili|vicine|intorno)\b|quali (?:reti|wi[ -]?fi)", t):
        return "wifi_list", {}
    if re.search(r"(?:stato della rete|sono connesso|sono collegato|c'e internet|funziona internet|"
                 r"indirizzo ip|il mio ip|che rete|a che rete|rete attuale)", t):
        return "network_status", {}
    bt = r"(?:il )?bluetooth"
    if re.fullmatch(V_ACCENDI + " " + bt, t):
        return "bluetooth_on", {}
    if re.fullmatch(V_SPEGNI + " " + bt, t):
        return "bluetooth_off", {}
    if re.search(r"dispositivi bluetooth|bluetooth (?:collegati|vicini|associati)", t):
        return "bluetooth_devices", {}
    m = re.fullmatch(r"(?:connetti|collega|associa)(?: le| il| la| lo| i)? (.+?)(?: (?:via|con il|al) bluetooth)?", t)
    if m and re.search(r"cuffie|auricolari|mouse|tastiera|casse|altoparlant|bluetooth", t):
        return "bluetooth_connect", {"dispositivo": re.sub(r"^(?:cuffie|auricolari|mouse|tastiera|casse) ", "", m.group(1))
                                     if len(m.group(1).split()) > 1 else m.group(1)}
    m = re.fullmatch(r"(?:scollega|disconnetti)(?: le| il| la| lo| i)? (.+?)(?: bluetooth)?", t)
    if m and re.search(r"cuffie|auricolari|mouse|tastiera|casse|altoparlant|bluetooth", t):
        return "bluetooth_disconnect", {"dispositivo": m.group(1)}
    return None


def _regolazioni(t):
    if re.search(r"\b(?:impostazioni|preferenze|settings)\b", t):
        return None                    # «impostazioni audio» e' una pagina, non il volume
    n = _numero(t)
    # «metti la musica un po' piu' forte», «piu' piano»: il volume, detto a parole
    if not re.search(r"\b(?:volume|luminosita|luce)\b", t):
        if re.search(r"\b(?:piu forte|alza la musica|alza l'audio|alza il suono)\b", t):
            return "set_volume", {"variazione": 10}
        if re.search(r"\b(?:piu piano|abbassa la musica|abbassa l'audio|abbassa il suono)\b", t):
            return "set_volume", {"variazione": -10}
    # «c'e' qualcosa che rallenta il computer?», «perche' e' cosi' lento?»
    if re.search(r"\brallent\w*|\b(?:e|va|sta andando|diventato) (?:cosi |molto |troppo )?(?:lento|lenta|piano)\b|"
                 r"\b(?:impallato|bloccato|pesante)\b", t) and not re.search(r"\b(?:video|musica|internet|rete|wi ?fi)\b", t):
        return "list_processes", {"per": "cpu"}
    if re.search(r"\b(?:volume|audio|suono)\b", t):
        if re.search(r"\b(?:muto|silenzia|togli l'audio|togli il volume|zittisci)\b", t) or t in ("muto", "silenzio"):
            return "set_volume", {"muto": True}
        if re.search(r"\b(?:riattiva|rimetti|togli il muto)\b", t):
            return "set_volume", {"muto": False}
        if n is not None and re.search(r"\b(?:al|a|allo)\s+\d", t):
            return "set_volume", {"livello": n}          # «alza il volume al 60%»: 60, non +60
        if re.search(r"\b(?:alza|aumenta|piu alto|su)\b", t):
            return "set_volume", {"variazione": n if n is not None else 10}
        if re.search(r"\b(?:abbassa|diminuisci|riduci|piu basso|giu)\b", t):
            return "set_volume", {"variazione": -(n if n is not None else 10)}
        if n is not None:
            return "set_volume", {"livello": n}
        return "set_volume", {}
    if t in ("muto", "silenzio", "silenzia"):
        return "set_volume", {"muto": True}
    if re.search(r"\b(?:luminosita|luce dello schermo|brightness)\b", t):
        if n is not None and re.search(r"\b(?:al|a|allo)\s+\d", t):
            return "set_brightness", {"livello": n}
        if re.search(r"\b(?:alza|aumenta|piu)\b", t):
            return "set_brightness", {"variazione": n if n is not None else 10}
        if re.search(r"\b(?:abbassa|diminuisci|riduci|meno)\b", t):
            return "set_brightness", {"variazione": -(n if n is not None else 10)}
        return "set_brightness", ({"livello": n} if n is not None else {})
    m = re.search(r"\btema (chiaro|scuro)\b|\b(?:modalita|modo) (chiara|scura)\b", t)
    if m:
        return "set_theme", {"tema": m.group(1) or m.group(2)}
    m = re.fullmatch(r"(?:cambia|metti|imposta)(?: lo)? sfondo(?: con| a| in)? (.+)", t)
    if m:
        return "set_wallpaper", {"immagine": _nome_oggetto(m.group(1))}
    if re.search(r"\b(?:screenshot|schermata|foto dello schermo|cattura lo schermo)\b", t):
        return "screenshot", {}
    if re.search(r"\bche (?:ore|ora) (?:sono|e)\b|\bche giorno\b|\bche data\b", t):
        return "current_time", {}
    if re.search(r"\b(?:quanta|quanto) (?:ram|memoria)\b|\b(?:uso|stato) della (?:ram|memoria)\b|\bram libera\b", t):
        return "system_status", {"cosa": "ram"}
    if re.search(r"\b(?:spazio (?:libero|su disco)|quanto spazio|disco pieno|stato del disco)\b", t):
        return "system_status", {"cosa": "disco"}
    if re.search(r"\b(?:batteria)\b", t):
        return "system_status", {"cosa": "batteria"}
    if re.search(r"\b(?:uso della cpu|quanto (?:lavora|e carico) il processore|cpu)\b", t) and \
            not re.search(r"\bprocess", t):
        return "system_status", {"cosa": "cpu"}
    if re.search(r"\bstato del (?:sistema|computer)\b|\bcome sta il computer\b|\bcome va il (?:sistema|computer)\b", t):
        return "system_status", {}
    if re.search(r"\bprocess|\bchi (?:usa|consuma)|\bcosa (?:sta usando|consuma|usa)\b", t):
        return "list_processes", {"per": "memoria" if re.search(r"memoria|ram", t) else "cpu"}
    return None


_DEST = (r"(?:in|nella|nel|nei|negli|sulla|sul|su|dentro|alla|al)\s+(?:cartella\s+)?")


_URL = r"((?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:[/?#]\S*)?)"


def _file(t):
    luogo = _luogo(t)
    # «apri il sito www.debian.org», «vai su wikipedia.org», «apri https://…»
    m = re.fullmatch(r"(?:" + V_APRI + r"\s+(?:il sito(?: web)?|la pagina(?: web)?|il link|l'indirizzo)|"
                     r"vai su|vai a|visita|naviga su|portami su)\s+" + _URL, t)
    if m:
        return "open_url", {"url": m.group(1)}
    # dopo un semplice «apri» «nota.txt» e' un file: e' un sito solo se lo dice
    m = re.fullmatch(V_APRI + r"\s+" + _URL, t)
    if m and re.match(r"(?:https?://|www\.)|.*\.(?:com|org|net|it|eu|io|dev|info|gov|edu|co|uk|de|fr|es|ch|"
                      r"app|ai|me|tv|news|blog|wiki)(?:[/?#]|$)", m.group(1)):
        return "open_url", {"url": m.group(1)}
    m = re.fullmatch(V_APRI + r"\s+(?:il sito|la pagina web|il link|l'indirizzo)\s+(.+)", t)
    if m:
        return "open_url", {"url": m.group(1)}
    # «mi fai vedere le foto che ho scaricato», «fammi vedere i documenti»
    m = re.match(r"(?:mi fai vedere|fammi vedere|fai vedere|mostrami|mostra)\s+(.+)", t)
    if m:
        resto = m.group(1)
        if re.search(r"\bscaricat|\bdownload", resto):
            return "open_folder", {"cartella": "download"}
        for parola, cartella in (("foto", "immagini"), ("immagini", "immagini"), ("documenti", "documenti"),
                                 ("musica", "musica"), ("canzoni", "musica"), ("video", "video"),
                                 ("filmati", "video"), ("scrivania", "scrivania"), ("desktop", "scrivania"),
                                 ("cestino", "cestino")):
            if re.search(r"\b%s\b" % parola, resto):
                return "open_folder", {"cartella": cartella}
    m = re.fullmatch(V_CREA + r" (?:una |la )?(?:nuova )?cartella(?: chiamata| di nome| con nome)? (.+)", t)
    if m and _nome_valido(_nome_oggetto(_togli_luogo(m.group(1)))):
        return "create_folder", {"nome": _nome_oggetto(_togli_luogo(m.group(1))), "dove": luogo or "home"}
    m = re.fullmatch(V_CREA + r" (?:un |il )?(?:nuovo )?file(?: di testo)?(?: chiamato| di nome| con nome)? (.+?)"
                     r"(?: con (?:scritto|dentro|il testo) (.+))?", t)
    if m and _nome_valido(_nome_oggetto(_togli_luogo(m.group(1)))):
        return "create_file", {"nome": _nome_oggetto(_togli_luogo(m.group(1))), "dove": luogo or "documenti",
                               "testo": m.group(2) or ""}
    m = re.fullmatch(r"(?:rinomina|cambia (?:il )?nome (?:a|al|alla|del|della))\s+(.+?)\s+(?:in|come|con)\s+(.+)", t)
    if m and _nome_valido(m.group(2)):
        return "rename_item", {"elemento": _nome_oggetto(_togli_luogo(m.group(1))),
                               "nuovo_nome": _nome_oggetto(m.group(2)), "dove": luogo}
    m = re.fullmatch(r"(?:copia|duplica)\s+(.+?)\s+" + _DEST + r"(.+)", t)
    if m and _nome_valido(m.group(2)):
        return "copy_item", {"elemento": _nome_oggetto(m.group(1)), "destinazione": m.group(2)}
    m = re.fullmatch(r"(?:sposta|metti|trasferisci)\s+(.+?)\s+" + _DEST + r"(.+)", t)
    if m and not re.search(r"cestino", m.group(2)) and _nome_valido(m.group(2)):
        return "move_item", {"elemento": _nome_oggetto(m.group(1)), "destinazione": m.group(2)}
    m = re.fullmatch(V_ELIMINA + r"\s+(.+?)(?:\s+(?:dalla|dal|dai|dalle|da)\s+(?:cartella\s+)?(.+))?", t) or \
        re.fullmatch(r"(?:sposta|metti|butta)\s+(.+?)\s+nel cestino", t)
    if m:
        dove = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        return "delete_item", {"elemento": _nome_oggetto(_togli_luogo(m.group(1))), "dove": dove or luogo}
    m = re.fullmatch(r"(?:dove si trova|dov'e|dove e|mostrami dove (?:si trova|e)|mostra la posizione di|"
                     r"apri la cartella (?:di|che contiene))\s+(.+)", t)
    if m:
        return "show_location", {"elemento": _nome_oggetto(m.group(1))}
    m = re.fullmatch(V_CERCA + r"\s+(?:il |i |un |dei |tutti i )?(?:file|documenti|cartelle|foto|immagini)?\s*"
                     r"(?:chiamat[oi] |di nome |con nome |che si chiama(?:no)? )?(.+)", t)
    if m and m.group(1) not in ("", "file"):
        return "search_files", {"testo": _nome_oggetto(_togli_luogo(m.group(1))), "dove": luogo}
    m = re.fullmatch(r"(?:scarica|download)\s+(https?://\S+)(?:\s+.*)?", t)
    if m:
        return "download_file", {"url": m.group(1), "dove": luogo or "download"}
    return None


def _app_e_finestre(t):
    if re.fullmatch(r"(?:chiudi|chiudimi)(?: tutte le finestre| tutto| tutti i programmi| tutte le app)", t):
        return "close_all_windows", {}
    if re.fullmatch(r"(?:chiudi|chiudimi)(?: questa| la)? finestra(?: attiva| corrente)?", t):
        return "close_window", {}
    m = re.fullmatch(r"(?:forza la chiusura (?:di|del|della|dello)|chiudi (?:a forza|d'autorita|forzatamente)|"
                     r"uccidi|termina forzatamente)\s+(.+)", t)
    if m:
        return "force_close_application", {"app": m.group(1)}
    m = re.fullmatch(r"(?:riduci(?: a icona)?|minimizza|nascondi)(?: la finestra(?: di)?)?(?: (.+))?", t)
    if m:
        return "minimize_window", {"app": m.group(1) or ""}
    m = re.fullmatch(r"(?:ingrandisci|massimizza|allarga)(?: la finestra(?: di)?)?(?: (.+))?", t)
    if m:
        return "maximize_window", {"app": m.group(1) or ""}
    m = re.fullmatch(r"(?:metti a )?schermo intero(?: (?:per|a) (.+))?|(?:metti|porta) (.+) a schermo intero", t)
    if m:
        return "fullscreen_window", {"app": m.group(1) or m.group(2) or ""}
    ruoli = (r"(browser|posta|email|posta elettronica|gestore (?:dei )?file|file|terminale|editor(?: di testo)?|"
             r"lettore video|lettore multimediale|lettore pdf|pdf|visualizzatore (?:di )?immagini|immagini)")
    m = re.fullmatch(r"(?:imposta|usa|metti|rendi|scegli)\s+(.+?)\s+come\s+(?:il |la |l'|lo )?" + ruoli +
                     r"(?: predefinit[oa]| di sistema)?", t)
    if m:
        return "set_default_app", {"app": m.group(1), "ruolo": m.group(2)}
    m = re.fullmatch(r"(?:imposta|cambia|metti)\s+(?:il |la |l'|lo )?" + ruoli +
                     r"\s+predefinit[oa]\s+(?:in|con|a|su)\s+(.+)", t)
    if m:
        return "set_default_app", {"ruolo": m.group(1), "app": m.group(2)}
    if re.search(r"\b(?:app|applicazioni|programmi) predefinit[ei]\b|\bqual e il (?:browser|terminale|gestore file)"
                 r" predefinito\b", t) and not re.search(r"\bimpostazioni\b", t):
        return "list_default_apps", {}
    m = re.fullmatch(V_PASSA + r"\s+(.+)", t)
    if m and S.trova_app(m.group(1)):
        return "focus_application", {"app": m.group(1)}
    if re.search(r"\b(?:che|quali) (?:app|applicazioni|programmi|finestre) (?:sono |ho )?(?:aperte|aperti|in esecuzione)\b|"
                 r"\b(?:app|programmi|finestre) aperte?\b", t):
        return "list_running_applications", {}
    if re.search(r"\b(?:che|quali) (?:app|applicazioni|programmi) (?:sono |ho )?installat", t):
        return "list_installed_applications", {}
    m = re.fullmatch(r"(?:e installato|c'e|ho) (.+?)(?: installato)?\??", t)
    if m and re.search(r"installat", t):
        return "is_installed", {"app": m.group(1)}
    m = re.fullmatch(r"(?:installa|installami)\s+(?:il |lo |la |l')?(?:programma |pacchetto |app )?(.+)", t)
    if m:
        return "install_package", {"pacchetto": m.group(1)}
    m = re.fullmatch(r"(?:disinstalla|rimuovi il programma|rimuovi il pacchetto)\s+(.+)", t)
    if m:
        return "remove_package", {"pacchetto": m.group(1)}
    m = re.fullmatch(r"(?:aggiungi|metti)\s+(.+?)\s+(?:al|nel|sul) dock", t)
    if m:
        return "dock_add", {"app": m.group(1)}
    m = re.fullmatch(r"(?:togli|rimuovi|leva)\s+(.+?)\s+dal dock", t)
    if m:
        return "dock_remove", {"app": m.group(1)}
    # impostazioni (anche «impostazioni del wifi», «apri le impostazioni audio»)
    m = re.fullmatch(r"(?:" + V_APRI + r"\s+)?(?:le )?(?:impostazioni|preferenze|settings)"
                     r"(?:\s+(?:di |del |della |dello |dei |delle |per |su |sul |sulla )?(.+))?", t)
    if m:
        return "open_settings", {"pagina": m.group(1) or ""}
    # riavvia un'app (il computer lo prende _sistema, che viene prima)
    m = re.fullmatch(V_RIAVVIA + r"\s+(.+)", t)
    if m:
        return "restart_application", {"app": m.group(1)}
    m = re.fullmatch(V_CHIUDI + r"\s+(.+)", t)
    if m:
        return "close_application", {"app": m.group(1)}
    m = re.fullmatch(V_APRI + r"\s+(.+)", t)
    if m:
        ogg = m.group(1).strip()
        if re.match(r"https?://|www\.", ogg):
            return "open_url", {"url": ogg}
        pulito = re.sub(r"^(?:la |il |le |i |lo )?(?:cartella |cartelle )?(?:dei |delle |del |della )?", "", ogg)
        if S.norm(pulito) in ("cestino",) or _luogo("in " + pulito) == pulito or re.match(r"(?:la |le )?cartella", ogg):
            return "open_folder", {"cartella": pulito}
        if re.search(r"\.[a-z0-9]{2,5}$", ogg) or re.match(r"(?:il |lo |la |l')?(?:file|documento|immagine|foto) ", ogg):
            return "open_file", {"elemento": _nome_oggetto(_togli_luogo(ogg)), "dove": _luogo(t)}
        return "open_application", {"app": ogg}
    return None


_REGOLE = (_sistema, _rete, _regolazioni, _file, _app_e_finestre)


def _due_versioni(testo):
    """(minuscolo, con le maiuscole) della stessa lunghezza: le posizioni
    trovate nel primo valgono anche nel secondo."""
    import unicodedata
    basso, alto, spazio = [], [], False
    for ch in unicodedata.normalize("NFC", (testo or "").replace("’", "'")):
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn") or ch
        if base.isspace():
            if spazio or not basso:
                continue
            spazio, base = True, " "
        else:
            spazio = False
        for b in base:
            lb = b.lower()
            if len(lb) != 1:
                lb = b
            basso.append(lb)
            alto.append(b)
    return "".join(basso).rstrip(), "".join(alto).rstrip()


def _una(basso, alto):
    i = 0
    m = _INIZIO.match(basso)
    if m:
        i = m.end()
    m = _FONDO.search(basso, i)
    j = m.start() if m else len(basso)
    t, c = basso[i:j].strip(), alto[i:j].strip()
    for regola in _REGOLE:
        r = regola(t)
        if r:
            nome, args = r
            # i nomi (file, cartelle, reti, password, indirizzi) come li ha scritti l'utente
            for k, v in list(args.items()):
                if isinstance(v, str) and v:
                    pos = t.find(v)
                    if pos >= 0:
                        args[k] = c[pos:pos + len(v)]
            return nome, args
    return None


_UNITA = {"zero": 0, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
          "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "tredici": 13,
          "quattordici": 14, "quindici": 15, "sedici": 16, "diciassette": 17, "diciotto": 18,
          "diciannove": 19}
_DECINE = {"venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50, "sessanta": 60,
           "settanta": 70, "ottanta": 80, "novanta": 90}


def _valore(parola):
    """«sessantacinque» -> 65, «ventotto» -> 28, «cento» -> 100; None se non e' un numero."""
    p = parola.lower()
    if p == "cento":
        return 100
    if p in _UNITA and p not in ("uno", "una"):
        return _UNITA[p]
    for nome, v in _DECINE.items():
        radice = nome[:-1]                       # «vent», «trent»: ventuno, ventotto
        if p == nome:
            return v
        for r in (nome, radice):
            if p.startswith(r) and p[len(r):] in _UNITA and p[len(r):] not in ("una",):
                return v + _UNITA[p[len(r):]]
    return None


def _numeri_in_cifre(testo):
    """La voce scrive i numeri a parole: «al sessanta per cento» -> «al 60 per cento».
    Solo dopo «al», «di», «volume»… o prima di «per cento»: «apri due
    finestre» resta com'e'."""
    parole = re.split(r"(\s+)", testo)
    prima = {"al", "allo", "a", "del", "di", "su", "volume", "luminosita", "luminosità"}
    for k in range(0, len(parole), 2):
        v = _valore(parole[k])
        if v is None:
            continue
        prec = parole[k - 2].lower() if k >= 2 else ""
        dopo = parole[k + 2].lower() if k + 2 < len(parole) else ""
        if prec in prima or dopo == "per" or dopo.startswith("percent"):
            parole[k] = str(v)
    return "".join(parole)


def capire(testo: str):
    """[(capacita', argomenti), ...] oppure None se la frase non e' un comando noto."""
    basso, alto = _due_versioni(_numeri_in_cifre(testo or ""))
    if not basso:
        return None
    composta = _composta(basso, alto)
    if composta:
        return composta
    intera = _una(basso, alto)
    return [intera] if intera else None


def _composta(basso, alto):
    """«apri firefox e poi chiudi il terminale» -> due azioni (solo se ogni
    pezzo e' un comando riconosciuto)."""
    pezzi_b = re.split(r"\s*(?:,\s*)?(?:\be poi\b|\bpoi\b|\be dopo\b|;|\be\b(?= (?:apri|chiudi|avvia|spegni|accendi|"
                       r"alza|abbassa|crea|copia|sposta|elimina|cerca|blocca|riavvia|metti|passa|riduci|ingrandisci)))\s*",
                       basso)
    if len(pezzi_b) < 2:
        return None
    azioni, pos = [], 0
    for p in pezzi_b:
        k = basso.find(p, pos)
        pos = k + len(p)
        r = _una(p, alto[k:k + len(p)]) or _pronome(p, azioni)
        if not r:
            return None                  # un pezzo non capito: si prova la frase intera
        azioni.append(r)
    return azioni


def _pronome(pezzo, prima):
    """«...e poi aprila»: si apre proprio cio' che e' stato appena creato,
    copiato o spostato (con il percorso esatto, non cercandolo per nome)."""
    if not prima or not re.fullmatch(r"(?:e )?apri(?:la|lo|li|le|mela|melo)|aprimela|aprimelo|"
                                     r"(?:e )?mostra(?:mela|melo|la|lo)", pezzo.strip()):
        return None
    nome, args = prima[-1]
    from . import capacita as C
    if nome in ("create_folder", "create_file"):
        base = C.cartella_di(args.get("dove") or "home") or S.HOME
        percorso = os.path.join(base, args.get("nome", ""))
    elif nome in ("copy_item", "move_item"):
        base = C.cartella_di(args.get("destinazione", ""))
        if not base:
            return None
        percorso = os.path.join(base, os.path.basename(args.get("elemento", "")))
    else:
        return None
    return ("open_folder", {"cartella": percorso}) if nome == "create_folder" else \
        ("open_file", {"elemento": percorso})
