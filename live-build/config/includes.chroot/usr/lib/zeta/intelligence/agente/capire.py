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
import shutil

from . import stato as S

# Si capisce l'italiano e l'inglese, qualunque sia la lingua del sistema.

# parole di cortesia all'inizio e alla fine: si tolgono
_INIZIO = re.compile(r"^(?:(?:zeta|ehi|ok|allora|per favore|per piacere|puoi|potresti|mi puoi|"
                     r"riesci a|vorrei|voglio|devi|please|can you|hey|hi|okay|could you|would you|"
                     r"will you|can you please|i want to|i'd like to|i would like to|i need to|"
                     r"go ahead and|kindly)[ ,]+)+")
# (la parola finale deve essere una parola a se': «open snow» non perde «now»)
_FONDO = re.compile(r"[ ,]*(?:(?<![^ ,])(?:per favore|per piacere|grazie|please|subito|adesso|thanks|thank you|"
                    r"right now|now|for me))?[ .!?]*$")

# verbi (dopo norm: minuscole, senza accenti)
V_APRI = r"(?:apri|aprimi|avvia|avviami|lancia|fai partire|esegui|open up|open|launch|start|run)"
V_CHIUDI = r"(?:chiudi|chiudimi|esci da|termina|quit|close|exit)"
V_RIAVVIA = r"(?:riavvia|riapri|restart|reboot|relaunch|reopen)"
V_PASSA = r"(?:passa a|vai su|vai a|torna a|torna su|metti in primo piano|mostrami|switch to|focus on|focus|" \
          r"go to|go back to|bring up|show me)"
V_CREA = r"(?:crea|creami|fai|nuova|nuovo|create|make|new)"
V_CERCA = r"(?:cerca|cercami|trova|trovami|dove si trova|dov'e|dove e|search for|search|find me|find|" \
          r"look for|locate|where is|where's)"
V_ELIMINA = r"(?:elimina|cancella|rimuovi il file|rimuovi la cartella|butta|cestina|delete|erase|trash|" \
            r"remove the file|remove the folder|throw away|get rid of)"
V_ACCENDI = r"(?:accendi|attiva|abilita|turn on|enable|switch on|activate)"
V_SPEGNI = r"(?:spegni|disattiva|disabilita|turn off|disable|switch off|deactivate)"

_ART = r"(?:il |lo |la |l'|i |gli |le |un |una |uno |del |della |dello |dei |delle |the |a |an |my )?"
_COMPUTER = r"(?:il |lo |the |my |this )?(?:computer|pc|sistema|portatile|mini pc|system|laptop|machine)"

# i luoghi (cartelle note), in italiano e in inglese
_LUOGHI = (r"scrivania|desktop|documenti|download|downloads|scaricati|immagini|foto|musica|video|home|"
           r"cartella personale|modelli|pubblici|documents|pictures|photos|music|videos|templates|public|"
           r"home folder")
_PREP_LUOGO = (r"(?:sulla|sul|nella|nel|nei|negli|in|dentro|su|alla|al|dalla|dal|dai|"
               r"on|to|into|inside|from|onto)")


def _pulisci(testo):
    t = S.norm(testo)
    t = t.replace("’", "'")
    t = _INIZIO.sub("", t)
    t = _FONDO.sub("", t)
    return t.strip()


def _numero(t):
    m = re.search(r"(\d{1,3})\s*(?:%|per ?cento|percent)?", t)
    return int(m.group(1)) if m else None


def _luogo(t):
    """«sulla scrivania», «nei documenti», «in download», «on the desktop»,
    «in my documents folder» -> nome del luogo."""
    m = re.search(r"\b" + _PREP_LUOGO + r"\s+(?:(?:the|my)\s+)?(?:cartella\s+)?(" + _LUOGHI + r")\b", t)
    return m.group(1) if m else None


def _togli_luogo(t):
    return re.sub(r"\s+" + _PREP_LUOGO + r"\s+(?:(?:the|my)\s+)?(?:cartella\s+)?(?:" + _LUOGHI +
                  r")(?:\s+folder)?\b", "", t).strip()


# Un nome che contiene «e poi», «poi», «e apri…» non e' un nome: e' il resto di
# una frase composta non capita. «crea una cartella viaggi e poi aprila»
# creava la cartella «viaggi e poi aprila» (visto). Meglio non capire.
_COLLANTE = re.compile(r"\b(?:e poi|poi|e dopo|dopodiche|e (?:apri|chiudi|avvia|elimina|sposta|copia|mostra)\w*|"
                       r"and then|then|after that|and (?:open|close|start|launch|delete|move|copy|show)\w*)\b")


def _nome_valido(n):
    return bool(n) and not _COLLANTE.search(n)


def _nome_oggetto(t):
    """toglie «il file», «la cartella», articoli e virgolette"""
    t = re.sub(r"^(?:il |lo |la |l'|i |gli |le |un |una |uno )?(?:file |cartella |documento |immagine |foto )?",
               "", t.strip())
    t = re.sub(r"^(?:the |a |an |my |this )?(?:(?:file|folder|document|image|photo|picture) )?"
               r"(?:(?:called|named) )?", "", t)
    return t.strip().strip("«»\"'“”")


def _sistema(t):
    """Energia: solo se si nomina il computer (o il verbo e' da solo)."""
    if re.fullmatch(r"(?:riavvia|reboot|restart)(?: " + _COMPUTER + r")?", t) or \
            re.fullmatch(r"(?:riavvia(?:mi)?|fai ripartire) " + _COMPUTER, t):
        return "restart_system", {}
    if re.fullmatch(r"(?:spegni|arresta|shutdown|spegnimento|shut down|power off)(?: " + _COMPUTER + r")?", t) or \
            re.fullmatch(r"(?:turn off|switch off|shut down|power down) " + _COMPUTER, t) or \
            re.fullmatch(r"(?:turn|switch|shut) " + _COMPUTER + r" (?:off|down)", t):
        return "shutdown_system", {}
    if re.fullmatch(r"(?:sospendi|metti in (?:sospensione|standby)|standby|vai in standby|suspend|sleep|"
                    r"go to sleep)(?: " + _COMPUTER + r")?", t) or \
            re.fullmatch(r"put " + _COMPUTER + r" to sleep|put " + _COMPUTER + r" in standby", t):
        return "suspend_system", {}
    if re.fullmatch(r"(?:blocca|lock)(?: " + _COMPUTER + r"| lo schermo| la sessione| schermo|"
                    r" the screen| my screen| screen| the session)?|lock screen", t):
        return "lock_screen", {}
    if re.fullmatch(r"(?:esci|disconnettimi|logout|log out|chiudi la sessione|esci dalla sessione|"
                    r"termina la sessione|log me out|sign out|sign me out|end the session|close the session|"
                    r"exit the session)(?: dalla sessione| of the session| of my session)?", t):
        return "logout", {}
    return None


def _rete(t):
    wifi = r"(?:il |la |the )?(?:wi[ -]?fi|rete wireless|wireless)"
    if re.fullmatch(V_ACCENDI + " " + wifi, t) or re.fullmatch(r"(?:turn|switch) " + wifi + r" on", t):
        return "wifi_on", {}
    if re.fullmatch(V_SPEGNI + " " + wifi, t) or re.fullmatch(r"(?:turn|switch) " + wifi + r" off", t):
        return "wifi_off", {}
    if re.fullmatch(r"(?:disconnetti|scollega|staccati da|disconnettiti da)(?:ti)?(?: dal| dalla| il| la)? "
                    r"(?:wi[ -]?fi|rete(?: wi[ -]?fi)?|internet)", t) or \
            re.fullmatch(r"disconnect(?: me)?(?: from)?(?: the)? (?:wi[ -]?fi|(?:wi[ -]?fi )?network|internet)", t):
        return "wifi_disconnect", {}
    # dispositivi Bluetooth: «connetti le cuffie» non e' una rete
    dispositivi = (r"(?:le |il |la |lo |i |the |my )?(?:cuffie|auricolari|mouse|tastiera|casse|altoparlant|"
                   r"telefono|dispositivo|bluetooth|headphones|earbuds|headset|keyboard|speaker|phone|device)")
    m = re.fullmatch(r"(?:connetti|collega|connettiti|collegati)(?:ti)?(?: al| alla| a)? "
                     r"(?:(?:rete )?(?:wi[ -]?fi )?|rete )?(.+?)(?: con (?:la )?password (.+))?", t) or \
        re.fullmatch(r"(?:connect|join)(?: me)?(?: to)?(?: the)? (?:(?:wi[ -]?fi )?network |wi[ -]?fi )?"
                     r"(.+?)(?: (?:with|using)(?: the)? password (.+))?", t)
    if m and not re.match(dispositivi, m.group(1)) and \
            not re.search(r"\b(?:headphones|earbuds|headset|mouse|keyboard|speakers?)$", m.group(1)):
        return "wifi_connect", {"rete": m.group(1).strip("«»\"'“” "), "password": m.group(2)}
    if re.search(r"\b(?:reti|wi[ -]?fi) (?:disponibili|vicine|intorno)\b|quali (?:reti|wi[ -]?fi)", t) or \
            re.search(r"\b(?:available|nearby) (?:wi[ -]?fi )?networks\b|\b(?:which|what) (?:wi[ -]?fi )?networks\b|"
                      r"\b(?:networks|wi[ -]?fi networks?) (?:available|nearby|around)\b|"
                      r"\b(?:list|show)(?: me)?(?: the)? (?:wi[ -]?fi )?networks\b", t):
        return "wifi_list", {}
    if re.search(r"(?:stato della rete|sono connesso|sono collegato|c'e internet|funziona internet|"
                 r"indirizzo ip|il mio ip|che rete|a che rete|rete attuale)", t) or \
            re.search(r"\b(?:network status|am i (?:connected|online)|is (?:the )?internet working|"
                      r"do i have internet|ip address|my ip\b|which network|what network|current network)", t):
        return "network_status", {}
    bt = r"(?:il |the )?bluetooth"
    if re.fullmatch(V_ACCENDI + " " + bt, t) or re.fullmatch(r"(?:turn|switch) " + bt + r" on", t):
        return "bluetooth_on", {}
    if re.fullmatch(V_SPEGNI + " " + bt, t) or re.fullmatch(r"(?:turn|switch) " + bt + r" off", t):
        return "bluetooth_off", {}
    if re.search(r"dispositivi bluetooth|bluetooth (?:collegati|vicini|associati)", t) or \
            re.search(r"bluetooth devices|bluetooth (?:connected|nearby|paired)|paired devices", t):
        return "bluetooth_devices", {}
    tipi_bt = r"cuffie|auricolari|mouse|tastiera|casse|altoparlant|bluetooth|headphones|earbuds|headset|keyboard|speaker"
    m = re.fullmatch(r"(?:connetti|collega|associa)(?: le| il| la| lo| i)? (.+?)(?: (?:via|con il|al) bluetooth)?", t)
    if m and re.search(tipi_bt, t):
        return "bluetooth_connect", {"dispositivo": re.sub(r"^(?:cuffie|auricolari|mouse|tastiera|casse) ", "", m.group(1))
                                     if len(m.group(1).split()) > 1 else m.group(1)}
    m = re.fullmatch(r"(?:connect|pair)(?: my| the)? (.+?)(?: (?:via|over|with|using) bluetooth)?", t)
    if m and re.search(tipi_bt, t):
        nome = m.group(1)
        if len(nome.split()) > 1:      # «sony headphones» -> «sony»
            nome = re.sub(r"^(?:headphones|earbuds|headset|mouse|keyboard|speakers?) | "
                          r"(?:headphones|earbuds|headset|mouse|keyboard|speakers?)$", "", nome)
        return "bluetooth_connect", {"dispositivo": nome}
    m = re.fullmatch(r"(?:scollega|disconnetti)(?: le| il| la| lo| i)? (.+?)(?: bluetooth)?", t) or \
        re.fullmatch(r"(?:disconnect|unpair)(?: my| the)? (.+?)(?: bluetooth)?", t)
    if m and re.search(tipi_bt, t):
        return "bluetooth_disconnect", {"dispositivo": m.group(1)}
    return None


def _regolazioni(t):
    if re.search(r"\b(?:impostazioni|preferenze|settings|preferences)\b", t):
        return None                    # «impostazioni audio» e' una pagina, non il volume
    n = _numero(t)
    # «metti la musica un po' piu' forte», «piu' piano», «make it louder»: il volume, detto a parole
    if not re.search(r"\b(?:volume|luminosita|luce|brightness)\b", t):
        if re.search(r"\b(?:piu forte|alza la musica|alza l'audio|alza il suono)\b", t) or \
                re.search(r"\b(?:louder|turn (?:it|the music|the sound|the audio) up|"
                          r"turn up the (?:music|sound|audio))\b", t):
            return "set_volume", {"variazione": 10}
        if re.search(r"\b(?:piu piano|abbassa la musica|abbassa l'audio|abbassa il suono)\b", t) or \
                re.search(r"\b(?:quieter|softer|turn (?:it|the music|the sound|the audio) down|"
                          r"turn down the (?:music|sound|audio))\b", t):
            return "set_volume", {"variazione": -10}
    # «c'e' qualcosa che rallenta il computer?», «perche' e' cosi' lento?», «why is my computer so slow?»
    if (re.search(r"\brallent\w*|\b(?:e|va|sta andando|diventato) (?:cosi |molto |troppo )?(?:lento|lenta|piano)\b|"
                  r"\b(?:impallato|bloccato|pesante)\b", t) or
            re.search(r"\bslow(?:ing|s)? (?:down|it down|me down)\b|\bslowing\b|"
                      r"\b(?:is|so|very|too|running|really|being|got) (?:so |very |too |really )?slow\b|"
                      r"\b(?:frozen|sluggish|laggy|lagging)\b", t)) and \
            not re.search(r"\b(?:video|musica|internet|rete|wi ?fi|music|network|videos)\b", t):
        return "list_processes", {"per": "cpu"}
    if re.search(r"\b(?:volume|audio|suono|sound)\b", t):
        if re.search(r"\b(?:muto|silenzia|togli l'audio|togli il volume|zittisci|mute|silence|"
                     r"turn off the sound|turn the sound off)\b", t) or t in ("muto", "silenzio"):
            return "set_volume", {"muto": True}
        if re.search(r"\b(?:riattiva|rimetti|togli il muto|unmute|turn the sound back on|sound back on)\b", t):
            return "set_volume", {"muto": False}
        if n is not None and re.search(r"\b(?:al|a|allo|to|at)\s+\d", t):
            return "set_volume", {"livello": n}          # «alza il volume al 60%»: 60, non +60
        if re.search(r"\b(?:alza|aumenta|piu alto|su|up|raise|increase|higher|louder)\b", t):
            return "set_volume", {"variazione": n if n is not None else 10}
        if re.search(r"\b(?:abbassa|diminuisci|riduci|piu basso|giu|down|lower|decrease|reduce|quieter)\b", t):
            return "set_volume", {"variazione": -(n if n is not None else 10)}
        if n is not None:
            return "set_volume", {"livello": n}
        return "set_volume", {}
    if t in ("muto", "silenzio", "silenzia", "mute", "silence"):
        return "set_volume", {"muto": True}
    if t in ("unmute",):
        return "set_volume", {"muto": False}
    if re.search(r"\b(?:luminosita|luce dello schermo|brightness)\b", t):
        if n is not None and re.search(r"\b(?:al|a|allo|to|at)\s+\d", t):
            return "set_brightness", {"livello": n}
        if re.search(r"\b(?:alza|aumenta|piu|up|raise|increase|more|higher|brighter)\b", t):
            return "set_brightness", {"variazione": n if n is not None else 10}
        if re.search(r"\b(?:abbassa|diminuisci|riduci|meno|down|lower|decrease|reduce|less|dim|dimmer)\b", t):
            return "set_brightness", {"variazione": -(n if n is not None else 10)}
        return "set_brightness", ({"livello": n} if n is not None else {})
    m = re.search(r"\btema (chiaro|scuro)\b|\b(?:modalita|modo) (chiara|scura)\b", t)
    if m:
        return "set_theme", {"tema": m.group(1) or m.group(2)}
    m = re.search(r"\b(light|dark) (?:theme|mode)\b|\b(?:theme|mode) (?:to )?(light|dark)\b", t)
    if m:
        return "set_theme", {"tema": m.group(1) or m.group(2)}
    m = re.fullmatch(r"(?:cambia|metti|imposta)(?: lo)? sfondo(?: con| a| in)? (.+)", t) or \
        re.fullmatch(r"(?:change|set|switch)(?: the| my)? (?:wallpaper|background|desktop background)"
                     r"(?: to| with)? (.+)", t) or \
        re.fullmatch(r"(?:use|set|make) (.+?) as (?:the |my )?(?:wallpaper|background|desktop background)", t) or \
        re.fullmatch(r"(?:use|set|put|choose|apply)(?: the| a)? (.+?) (?:wallpaper|background)", t) or \
        re.fullmatch(r"(?:metti|usa|scegli|imposta)(?: lo| il)? sfondo (.+)", t)
    if m:
        return "set_wallpaper", {"immagine": _nome_oggetto(m.group(1))}
    if re.search(r"\b(?:screenshot|schermata|foto dello schermo|cattura lo schermo|screen ?shot|screen capture|"
                 r"capture the screen)\b", t):
        return "screenshot", {}
    if re.search(r"\bche (?:ore|ora) (?:sono|e)\b|\bche giorno\b|\bche data\b", t) or \
            re.search(r"\bwhat time is it\b|\bwhat(?:'s| is) the (?:time|date)\b|\bwhat day is (?:it|today)\b|"
                      r"\bwhat(?:'s| is) today(?:'s date)?\b|\bwhat date is it\b|\bthe time\b$", t):
        return "current_time", {}
    if re.search(r"\b(?:quanta|quanto) (?:ram|memoria)\b|\b(?:uso|stato) della (?:ram|memoria)\b|\bram libera\b", t) or \
            re.search(r"\bhow much (?:ram|memory)\b|\b(?:ram|memory) usage\b|\bfree (?:ram|memory)\b", t):
        return "system_status", {"cosa": "ram"}
    if re.search(r"\b(?:spazio (?:libero|su disco)|quanto spazio|disco pieno|stato del disco)\b", t) or \
            re.search(r"\b(?:free (?:disk )?space|disk space|how much space|disk (?:is )?full|disk usage|"
                      r"storage space)\b", t):
        return "system_status", {"cosa": "disco"}
    if re.search(r"\b(?:batteria|battery)\b", t):
        return "system_status", {"cosa": "batteria"}
    if re.search(r"\b(?:uso della cpu|quanto (?:lavora|e carico) il processore|cpu)\b", t) and \
            not re.search(r"\bprocess", t):
        return "system_status", {"cosa": "cpu"}
    if re.search(r"\bstato del (?:sistema|computer)\b|\bcome sta il computer\b|\bcome va il (?:sistema|computer)\b", t) or \
            re.search(r"\b(?:system|computer) status\b|\bhow is (?:the|my) (?:computer|system)(?: doing)?\b|"
                      r"\bstatus of the (?:system|computer)\b", t):
        return "system_status", {}
    if re.search(r"\bprocess|\bchi (?:usa|consuma)|\bcosa (?:sta usando|consuma|usa)\b", t) or \
            re.search(r"\bwho(?:'s| is) (?:using|eating|hogging)\b|\bwhat(?:'s| is) (?:using|eating|hogging)\b|"
                      r"\bwhich (?:apps|programs) (?:are )?using\b", t):
        return "list_processes", {"per": "memoria" if re.search(r"memoria|ram|memory", t) else "cpu"}
    return None


_DEST = (r"(?:in|nella|nel|nei|negli|sulla|sul|su|dentro|alla|al|to|into|inside|onto|on)\s+"
         r"(?:(?:the|my)\s+)?(?:cartella\s+)?")


_URL = r"((?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:[/?#]\S*)?)"


def _file(t):
    luogo = _luogo(t)
    # «apri il sito www.debian.org», «vai su wikipedia.org», «apri https://…»
    m = re.fullmatch(r"(?:" + V_APRI + r"\s+(?:il sito(?: web)?|la pagina(?: web)?|il link|l'indirizzo|"
                     r"the (?:web)?site|the (?:web ?)?page|the link|the address|(?:the )?website)|"
                     r"vai su|vai a|visita|naviga su|portami su|go to|visit|browse to|navigate to|take me to)\s+" + _URL, t)
    if m:
        return "open_url", {"url": m.group(1)}
    # dopo un semplice «apri» «nota.txt» e' un file: e' un sito solo se lo dice
    m = re.fullmatch(V_APRI + r"\s+" + _URL, t)
    if m and re.match(r"(?:https?://|www\.)|.*\.(?:com|org|net|it|eu|io|dev|info|gov|edu|co|uk|de|fr|es|ch|"
                      r"app|ai|me|tv|news|blog|wiki)(?:[/?#]|$)", m.group(1)):
        return "open_url", {"url": m.group(1)}
    m = re.fullmatch(V_APRI + r"\s+(?:il sito|la pagina web|il link|l'indirizzo|the (?:web)?site|the web ?page|"
                     r"the link|the address|website)\s+(.+)", t)
    if m:
        return "open_url", {"url": m.group(1)}
    # programs: where they are, which command starts them, which package
    m = re.fullmatch(r"(?:quale|che) comando (?:avvia|apre|lancia|fa partire|esegue)\s+(.+)", t) or \
        re.fullmatch(r"(?:which|what) command (?:launches|starts|opens|runs)\s+(.+)", t) or \
        re.fullmatch(r"(?:quale|che) pacchetto (?:contiene|fornisce|installa|ha)\s+(.+)", t) or \
        re.fullmatch(r"(?:which|what) package (?:provides|contains|installs|has|owns)\s+(.+)", t) or \
        re.fullmatch(r"(?:dov'e|dove e|dove si trova|mostrami|mostra|qual e)\s+(?:l'|il |lo |la )?"
                     r"(?:eseguibile|programma|file desktop|file \.desktop|voce del menu|comando)\s+"
                     r"(?:di|del|della|dello|per)\s+(.+)", t) or \
        re.fullmatch(r"(?:where is|where's|show me|show|what is|what's)\s+(?:the )?"
                     r"(?:executable|binary|program file|desktop file|\.desktop file|desktop entry|launcher|"
                     r"launch command)\s+(?:of|for)\s+(.+)", t) or \
        re.fullmatch(r"(?:where is|where's|where are)\s+(.+?)\s+installed", t) or \
        re.fullmatch(r"(?:dove e installato|dov'e installato|dove sono installati|dove si trova installato)\s+(.+)", t) or \
        re.fullmatch(r"(?:how do i (?:launch|start|run)|come (?:avvio|lancio|faccio partire))\s+(.+?)"
                     r"(?:\s+(?:from|dal) (?:the )?terminal(?:e)?)?", t)
    if m:
        return "where_is_program", {"app": _nome_oggetto(m.group(1))}
    if re.fullmatch(r"(?:trova|mostra|mostrami|elenca|cerca)\s+(?:le |tutte le )?(?:mie )?appimage", t) or \
            re.fullmatch(r"(?:find|show|list|search for)\s+(?:me )?(?:my |the |all |all my )?appimages?", t):
        return "list_appimages", {}
    # "where is firefox" / "dov'e nmap": a program, not a file
    m = re.fullmatch(r"(?:where is|where's|dove si trova|dov'e|dove e)\s+(?:the |il |lo |la |l')?(.+)", t)
    if m and _e_programma(m.group(1)):
        return "where_is_program", {"app": _nome_oggetto(m.group(1))}
    # «mi fai vedere le foto che ho scaricato», «fammi vedere i documenti»
    # «show me my photos», «let me see the downloads»
    m = re.match(r"(?:mi fai vedere|fammi vedere|fai vedere|mostrami|mostra|show me|let me see|can i see|show)\s+(.+)", t)
    if m:
        resto = m.group(1)
        if re.search(r"\bscaricat|\bdownload", resto):
            return "open_folder", {"cartella": "download"}
        for parola, cartella in (("foto", "immagini"), ("immagini", "immagini"), ("documenti", "documenti"),
                                 ("musica", "musica"), ("canzoni", "musica"), ("video", "video"),
                                 ("filmati", "video"), ("scrivania", "scrivania"), ("desktop", "scrivania"),
                                 ("cestino", "cestino"),
                                 ("photos", "immagini"), ("pictures", "immagini"), ("images", "immagini"),
                                 ("documents", "documenti"), ("music", "musica"), ("songs", "musica"),
                                 ("videos", "video"), ("movies", "video"), ("trash", "cestino")):
            if re.search(r"\b%s\b" % parola, resto):
                return "open_folder", {"cartella": cartella}
    m = re.fullmatch(V_CREA + r" (?:(?:una |la )?(?:nuova )?cartella(?: chiamata| di nome| con nome)?|"
                     r"(?:a |the )?(?:new )?(?:folder|directory)(?: called| named)?) (.+)", t)
    if m and _nome_valido(_nome_oggetto(_togli_luogo(m.group(1)))):
        return "create_folder", {"nome": _nome_oggetto(_togli_luogo(m.group(1))), "dove": luogo or "home"}
    m = re.fullmatch(V_CREA + r" (?:un |il )?(?:nuovo )?file(?: di testo)?(?: chiamato| di nome| con nome)? (.+?)"
                     r"(?: con (?:scritto|dentro|il testo) (.+))?", t) or \
        re.fullmatch(V_CREA + r" (?:a |the )?(?:new )?(?:text )?file(?: called| named)? (.+?)"
                     r"(?: (?:with the text|with text|containing|that says|saying) (.+))?", t)
    if m and _nome_valido(_nome_oggetto(_togli_luogo(m.group(1)))):
        return "create_file", {"nome": _nome_oggetto(_togli_luogo(m.group(1))), "dove": luogo or "documenti",
                               "testo": m.group(2) or ""}
    m = re.fullmatch(r"(?:rinomina|cambia (?:il )?nome (?:a|al|alla|del|della))\s+(.+?)\s+(?:in|come|con)\s+(.+)", t) or \
        re.fullmatch(r"(?:rename|change the name of)\s+(.+?)\s+(?:to|as|into)\s+(.+)", t)
    if m and _nome_valido(m.group(2)):
        return "rename_item", {"elemento": _nome_oggetto(_togli_luogo(m.group(1))),
                               "nuovo_nome": _nome_oggetto(m.group(2)), "dove": luogo}
    m = re.fullmatch(r"(?:copia|duplica|copy|duplicate)\s+(.+?)\s+" + _DEST + r"(.+)", t)
    if m and _nome_valido(m.group(2)):
        return "copy_item", {"elemento": _nome_oggetto(m.group(1)), "destinazione": m.group(2)}
    m = re.fullmatch(r"(?:sposta|metti|trasferisci|move|put|transfer)\s+(.+?)\s+" + _DEST + r"(.+)", t)
    if m and not re.search(r"cestino|trash|recycle bin", m.group(2)) and _nome_valido(m.group(2)) and \
            not re.search(r"\bdock\b|full ?screen", m.group(2)):
        return "move_item", {"elemento": _nome_oggetto(m.group(1)), "destinazione": m.group(2)}
    m = re.fullmatch(V_ELIMINA + r"\s+(.+?)(?:\s+(?:dalla|dal|dai|dalle|da|from)\s+(?:(?:the|my)\s+)?"
                     r"(?:cartella\s+)?(.+?)(?:\s+folder)?)?", t) or \
        re.fullmatch(r"(?:sposta|metti|butta)\s+(.+?)\s+nel cestino", t) or \
        re.fullmatch(r"(?:move|put|throw|send)\s+(.+?)\s+(?:in|into|to)(?: the)? (?:trash|recycle bin)(?: can)?", t)
    if m:
        dove = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        return "delete_item", {"elemento": _nome_oggetto(_togli_luogo(m.group(1))), "dove": dove or luogo}
    m = re.fullmatch(r"(?:dove si trova|dov'e|dove e|mostrami dove (?:si trova|e)|mostra la posizione di|"
                     r"apri la cartella (?:di|che contiene))\s+(.+)", t) or \
        re.fullmatch(r"(?:where is|where's|wheres|show (?:me )?the location of|"
                     r"open the (?:containing )?folder (?:of|containing|that contains|for)|"
                     r"which folder (?:is|contains))\s+(.+?)(?:\s+in)?", t) or \
        re.fullmatch(r"(?:show me|tell me) where\s+(.+?)\s+(?:is|are)", t)
    if m:
        return "show_location", {"elemento": _nome_oggetto(m.group(1))}
    m = re.fullmatch(V_CERCA + r"\s+(?:il |i |un |dei |tutti i |the |a |an |all |any |my )?"
                     r"(?:files|documents|folders|photos|pictures|images|file|documenti|cartelle|foto|immagini)?\s*"
                     r"(?:chiamat[oi] |di nome |con nome |che si chiama(?:no)? |called |named |with the name )?(.+)", t)
    if m and m.group(1) not in ("", "file", "files"):
        return "search_files", {"testo": _nome_oggetto(_togli_luogo(m.group(1))), "dove": luogo}
    m = re.fullmatch(r"(?:scarica|download)\s+(https?://\S+)(?:\s+.*)?", t)
    if m:
        return "download_file", {"url": m.group(1), "dove": luogo or "download"}
    return None


def _app_e_finestre(t):
    if re.fullmatch(r"(?:chiudi|chiudimi)(?: tutte le finestre| tutto| tutti i programmi| tutte le app)", t) or \
            re.fullmatch(r"close(?: all(?: the| my)? (?:windows|apps|applications|programs)| everything)", t):
        return "close_all_windows", {}
    if re.fullmatch(r"(?:chiudi|chiudimi)(?: questa| la)? finestra(?: attiva| corrente)?", t) or \
            re.fullmatch(r"close(?: this| the| the current| the active)? window", t):
        return "close_window", {}
    m = re.fullmatch(r"(?:forza la chiusura (?:di|del|della|dello)|chiudi (?:a forza|d'autorita|forzatamente)|"
                     r"uccidi|termina forzatamente)\s+(.+)", t) or \
        re.fullmatch(r"(?:force[ -]quit|force[ -]close|kill)\s+(.+)", t)
    if m:
        return "force_close_application", {"app": m.group(1)}
    m = re.fullmatch(r"(?:riduci(?: a icona)?|minimizza|nascondi)(?: la finestra(?: di)?)?(?: (.+))?", t) or \
        re.fullmatch(r"(?:minimi[sz]e|hide)(?: the window(?: of)?)?(?: (.+))?", t)
    if m:
        return "minimize_window", {"app": m.group(1) or ""}
    m = re.fullmatch(r"(?:ingrandisci|massimizza|allarga)(?: la finestra(?: di)?)?(?: (.+))?", t) or \
        re.fullmatch(r"(?:maximi[sz]e|enlarge)(?: the window(?: of)?)?(?: (.+))?", t)
    if m:
        return "maximize_window", {"app": m.group(1) or ""}
    m = re.fullmatch(r"(?:metti a )?schermo intero(?: (?:per|a) (.+))?|(?:metti|porta) (.+) a schermo intero", t) or \
        re.fullmatch(r"(?:go |make it |toggle )?full ?screen(?: (?:for|on) (.+))?|"
                     r"(?:make|put|set|switch) (.+?) (?:to |in |into )?full ?screen", t)
    if m:
        return "fullscreen_window", {"app": m.group(1) or m.group(2) or ""}
    ruoli = (r"(browser|posta|email|posta elettronica|gestore (?:dei )?file|file|terminale|editor(?: di testo)?|"
             r"lettore video|lettore multimediale|lettore pdf|pdf|visualizzatore (?:di )?immagini|immagini)")
    ruoli_en = (r"(web browser|browser|email client|mail client|email|mail|file manager|files|terminal|"
                r"text editor|editor|video player|media player|music player|pdf viewer|pdf reader|pdf|"
                r"image viewer|photo viewer|images)")
    m = re.fullmatch(r"(?:imposta|usa|metti|rendi|scegli)\s+(.+?)\s+come\s+(?:il |la |l'|lo )?" + ruoli +
                     r"(?: predefinit[oa]| di sistema)?", t) or \
        re.fullmatch(r"(?:set|use|make|choose)\s+(.+?)\s+(?:as\s+)?(?:the |my )?(?:default |system )" + ruoli_en, t) or \
        re.fullmatch(r"(?:set|use|make|choose)\s+(.+?)\s+as\s+(?:the |my )?" + ruoli_en +
                     r"(?: by default)?", t)
    if m:
        return "set_default_app", {"app": m.group(1), "ruolo": m.group(2)}
    m = re.fullmatch(r"(?:imposta|cambia|metti)\s+(?:il |la |l'|lo )?" + ruoli +
                     r"\s+predefinit[oa]\s+(?:in|con|a|su)\s+(.+)", t) or \
        re.fullmatch(r"(?:set|change|switch)\s+(?:the |my )?default\s+" + ruoli_en + r"\s+(?:to|as)\s+(.+)", t)
    if m:
        return "set_default_app", {"ruolo": m.group(1), "app": m.group(2)}
    if (re.search(r"\b(?:app|applicazioni|programmi) predefinit[ei]\b|\bqual e il (?:browser|terminale|gestore file)"
                  r" predefinito\b", t) or
            re.search(r"\bdefault (?:apps|applications|programs)\b|"
                      r"\bwhat(?:'s| is) (?:the |my )?default (?:browser|terminal|file manager|email|mail)\b|"
                      r"\bwhich (?:browser|terminal|file manager) is (?:the )?default\b", t)) and \
            not re.search(r"\b(?:impostazioni|settings)\b", t):
        return "list_default_apps", {}
    m = re.fullmatch(V_PASSA + r"\s+(.+)", t)
    if m and S.trova_app(m.group(1)):
        return "focus_application", {"app": m.group(1)}
    if re.search(r"\b(?:che|quali) (?:app|applicazioni|programmi|finestre) (?:sono |ho )?(?:aperte|aperti|in esecuzione)\b|"
                 r"\b(?:app|programmi|finestre) aperte?\b", t) or \
            re.search(r"\b(?:what|which) (?:apps|applications|programs|windows) (?:are |do i have |i have )?(?:open|running)\b|"
                      r"\b(?:apps|applications|programs|windows) (?:are )?(?:open|running)\b|"
                      r"\b(?:list|show)(?: me)?(?: the| all)? (?:open|running) (?:apps|applications|programs|windows)\b|"
                      r"^running (?:apps|applications|programs)$", t):
        return "list_running_applications", {}
    if re.search(r"\b(?:che|quali) (?:app|applicazioni|programmi) (?:sono |ho )?installat", t) or \
            re.search(r"\b(?:what|which) (?:apps|applications|programs) (?:are |do i have |i have )?installed\b|"
                      r"\b(?:list|show)(?: me)?(?: the| all)? installed (?:apps|applications|programs)\b|"
                      r"^installed (?:apps|applications|programs)$", t):
        return "list_installed_applications", {}
    m = re.fullmatch(r"(?:e installato|c'e|ho) (.+?)(?: installato)?\??", t)
    if m and re.search(r"installat", t):
        return "is_installed", {"app": m.group(1)}
    m = re.fullmatch(r"(?:is|do i have|have i got|have i) (.+?) installed\??", t)
    if m:
        return "is_installed", {"app": m.group(1)}
    m = re.fullmatch(r"(?:installa|installami)\s+(?:il |lo |la |l')?(?:programma |pacchetto |app )?(.+)", t) or \
        re.fullmatch(r"install\s+(?:the )?(?:program |package |app )?(.+)", t)
    if m:
        return "install_package", {"pacchetto": m.group(1)}
    m = re.fullmatch(r"(?:disinstalla|rimuovi il programma|rimuovi il pacchetto|uninstall|"
                     r"remove the program|remove the package|remove the app)\s+(.+)", t)
    if m:
        return "remove_package", {"pacchetto": m.group(1)}
    m = re.fullmatch(r"(?:aggiungi|metti)\s+(.+?)\s+(?:al|nel|sul) dock", t) or \
        re.fullmatch(r"(?:add|put|pin)\s+(.+?)\s+(?:to|on|in)(?: the)? dock", t)
    if m:
        return "dock_add", {"app": m.group(1)}
    m = re.fullmatch(r"(?:togli|rimuovi|leva)\s+(.+?)\s+dal dock", t) or \
        re.fullmatch(r"(?:remove|take|unpin)\s+(.+?)\s+(?:from|off)(?: the)? dock", t)
    if m:
        return "dock_remove", {"app": m.group(1)}
    # impostazioni (anche «impostazioni del wifi», «apri le impostazioni audio», «open sound settings»)
    m = re.fullmatch(r"(?:" + V_APRI + r"\s+)?(?:le )?(?:impostazioni|preferenze|settings)"
                     r"(?:\s+(?:di |del |della |dello |dei |delle |per |su |sul |sulla )?(.+))?", t) or \
        re.fullmatch(r"(?:" + V_APRI + r"\s+)?(?:the |my )?(?:system )?(?:settings|preferences)"
                     r"(?:\s+(?:for |of |on |about )?(?:the )?(.+))?", t) or \
        re.fullmatch(r"(?:" + V_APRI + r"\s+)?(?:the |my )?(.+?)\s+(?:settings|preferences)", t)
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
        cartella_en = re.match(r"(?:the |my )?(?:folder |directory )|(?:the |my )?.+ folder$", ogg)
        if cartella_en:               # «open the documents folder», «open the folder projects»
            pulito = re.sub(r"^(?:the |my )?(?:folder |directory )?(?:called |named )?|\s+folder$", "", ogg)
        elif re.match(r"(?:the |my )", ogg):
            pulito = re.sub(r"^(?:the |my )", "", ogg)
        if S.norm(pulito) in ("cestino", "trash", "recycle bin") or _luogo("in " + pulito) == pulito or \
                re.match(r"(?:la |le )?cartella", ogg) or cartella_en:
            return "open_folder", {"cartella": pulito}
        if re.search(r"\.[a-z0-9]{2,5}$", ogg) or re.match(r"(?:il |lo |la |l')?(?:file|documento|immagine|foto) ", ogg) or \
                re.match(r"(?:the |my |a )?(?:file|document|image|photo|picture) ", ogg):
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
# in inglese: «sixty», «sixty-five» (anche «sixty five», unito prima)
_UNITA_EN = {"zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
             "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_CIFRE_EN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_DECINE_EN = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
              "eighty": 80, "ninety": 90}


def _valore(parola):
    """«sessantacinque» -> 65, «ventotto» -> 28, «cento» -> 100; None se non e' un numero."""
    p = parola.lower()
    if p in ("cento", "hundred"):
        return 100
    if p in _UNITA_EN:
        return _UNITA_EN[p]
    if p in _DECINE_EN:
        return _DECINE_EN[p]
    d, _t, u = p.partition("-")
    if d in _DECINE_EN and u in _CIFRE_EN:
        return _DECINE_EN[d] + _CIFRE_EN[u]
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
    # «sixty five» -> «sixty-five»: una parola sola
    testo = re.sub(r"(?i)\b(%s)\s+(%s)\b" % ("|".join(_DECINE_EN), "|".join(_CIFRE_EN)), r"\1-\2", testo)
    testo = re.sub(r"(?i)\b(?:a|one) hundred\b", "hundred", testo)
    parole = re.split(r"(\s+)", testo)
    prima = {"al", "allo", "a", "del", "di", "su", "volume", "luminosita", "luminosità",
             "to", "at", "by", "of", "brightness"}
    for k in range(0, len(parole), 2):
        v = _valore(parole[k])
        if v is None:
            continue
        prec = parole[k - 2].lower() if k >= 2 else ""
        dopo = parole[k + 2].lower() if k + 2 < len(parole) else ""
        if prec in prima or dopo == "per" or dopo.startswith("percent"):
            parole[k] = str(v)
    return "".join(parole)


def _e_programma(nome):
    """An installed app or a command called so (and no file with that name
    in the usual folders is meant: files have extensions or several words)."""
    nome = _nome_oggetto(nome).strip()
    if not nome or "." in nome.rstrip(".") and not nome.endswith((".app",)):
        return False
    return bool(S.trova_app(nome) or shutil.which(nome) or shutil.which(nome.lower()))


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
                       r"alza|abbassa|crea|copia|sposta|elimina|cerca|blocca|riavvia|metti|passa|riduci|ingrandisci))|"
                       r"\band then\b|\bthen\b|\band after that\b|\bafter that\b|"
                       r"\band\b(?= (?:open|close|start|launch|turn|raise|lower|create|make|copy|move|delete|search|"
                       r"find|lock|restart|put|switch|minimi[sz]e|maximi[sz]e|set|show|mute|unmute)\b))\s*",
                       basso)
    if len(pezzi_b) < 2:
        return None
    azioni, pos = [], 0
    for p in pezzi_b:
        k = basso.find(p, pos)
        pos = k + len(p)
        # prima il pronome: «open it» sarebbe preso per un'app chiamata «it»
        r = _pronome(p, azioni) or _una(p, alto[k:k + len(p)])
        if not r:
            return None                  # un pezzo non capito: si prova la frase intera
        azioni.append(r)
    return azioni


def _pronome(pezzo, prima):
    """«...e poi aprila»: si apre proprio cio' che e' stato appena creato,
    copiato o spostato (con il percorso esatto, non cercandolo per nome)."""
    if not prima or not re.fullmatch(r"(?:e )?apri(?:la|lo|li|le|mela|melo)|aprimela|aprimelo|"
                                     r"(?:e )?mostra(?:mela|melo|la|lo)|"
                                     r"(?:and )?(?:open|show) (?:it|them)(?: to me| for me)?|(?:and )?show me", pezzo.strip()):
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
