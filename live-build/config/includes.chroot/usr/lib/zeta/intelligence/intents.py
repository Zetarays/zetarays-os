# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Intelligence — riconoscimento locale dei comandi (senza modello AI).

Traduce frasi in linguaggio naturale (italiano, con qualche forma inglese) in
azioni del motore `actions.py`, senza contattare nessun servizio. È veloce,
funziona offline e in modo deterministico: adatto ai comandi di sistema
("apri i documenti", "quanta RAM sto usando", "chiudi questa finestra").

Se nessuna regola corrisponde, `parse()` restituisce None e ZETA può
passare la domanda al modello linguistico (se configurato).
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus as _url_quote
import unicodedata
from dataclasses import dataclass

from i18n import tr, language
from ui import accento as _accento


@dataclass
class Intent:
    action: str | None    # None: domanda con risposta certa, niente da eseguire
    args: dict
    reply: str            # cosa dice ZETA RAYS mentre esegue (o la risposta)


def _norm(text: str) -> str:
    text = text.lower().strip()
    text = "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")   # toglie gli accenti
    text = text.replace("’", "'")                   # apostrofo tipografico
    return re.sub(r"\s+", " ", text)


# cartelle riconosciute nel testo -> nome per l'azione open_folder
_FOLDERS = {
    r"documenti|documents": "documenti",
    r"download|scaricati|scaricat": "download",
    r"immagini|foto|pictures|photos?|images": "immagini",
    r"music|musica": "musica",
    r"video|filmati": "video",
    r"scrivania|desktop": "scrivania",
    r"home|personale|casa": "home",
    r"cestino|\btrash\b|recycle bin": "cestino",
}

# app riconosciute -> nome per open_application
_APPS = {
    r"firefox|browser|internet|navigatore|il web|sul web|the web": "firefox-esr",
    r"calcolatric|calcolatore|calculator": "gnome-calculator",
    r"editor|blocco note|testo|notepad": "gnome-text-editor",
    r"file|cartelle|gestore file|folders": "thunar",
}

# pagine impostazioni
_SETTINGS = {
    r"rete|wifi|wi fi|network": "rete",
    r"audio|suono|volume|sound": "audio",
    r"bluetooth": "bluetooth",
    r"aspetto|tema|colore|colori|appearance|theme|colou?rs?|wallpaper": "aspetto",
    r"\bai\b|intelligenza|assistente|assistant": "ai",
    r"sicurezza|firewall|security": "sicurezza",
    r"pacchett|applicazioni installate|packages|installed apps": "pacchetti",
    r"informazioni|info di sistema|sistema|\babout\b": "informazioni",
}


def _find(mapping: dict, text: str):
    for pattern, value in mapping.items():
        if re.search(pattern, text):
            return value
    return None


# verbi che indicano "apri/mostra/vai a"
_OPEN = (r"(?:apri|aprimi|avvia|lancia|mostra|mostrami|fammi vedere|vai a|portami|vedere|visualizza"
         r"|open|show|launch|go to|start|bring up|pull up|take me to)")


# «Come apro…», «dove trovo…»: domande su come si fa, non ordini.
# Il modello piccolo rispondeva a caso (mandava in Impostazioni per aprire il
# terminale, citava browser che non ci sono). Qui la risposta e un fatto del
# sistema, sempre giusta, e insegna il comando per farlo fare a ZETA.
# Le icone sono descritte per forma, non per posizione: il dock si riordina.
# I comandi suggeriti sono tutti instradati da questo stesso file.
# I toni sono quelli che il sistema propone in Impostazioni › Aspetto: chi
# dice «metti il rosso» si aspetta quel rosso, non uno qualunque.
_COLORI = {
    "giallo": "#FFB020", "arancione": "#FF8A34", "viola": "#A855F7", "rosa": "#FF6FA5",
    "turchese": "#2DD4BF", "grigio": "#8A8A8E",
    "yellow": "#FFB020", "orange": "#FF8A34", "purple": "#A855F7", "violet": "#A855F7",
    "pink": "#FF6FA5", "turquoise": "#2DD4BF", "teal": "#2DD4BF", "gray": "#8A8A8E", "grey": "#8A8A8E",
}
# i quattro colori del sistema vengono dalla sua tavolozza (ui/accento.py):
# «metti il rosso» da' esattamente il rosso di Impostazioni › Aspetto
for _it, _en, _chiave in (("blu", "blue", "blu"), ("azzurro", "light blue", "blu"),
                          ("rosso", "red", "rosso"), ("verde", "green", "verde"),
                          ("bianco", "white", "bianco")):
    _COLORI[_it] = _COLORI[_en] = _accento.colore_di(_chiave)

_DOMANDA = (r"^(?:ma |e |allora |scusa |so |and |but |hey )?"
            r"(?:come|dove|dov|in che modo|how|where)\b")   # «dov» per «dov'e»
_SAPERE = [
    (r"(recuper|ripristin)\w*|(file|documento|cartella)[^.?!]{0,25}(eliminat|cancellat|cestinat|pers)"
     r"|\b(restore|recover|undelete)\w*|\b(files?|documents?|folders?)\b[^.?!]{0,25}\b(deleted|removed|trashed|lost)",
     tr("Deleted files go to the Trash. To get one back: double-click the Trash icon on the desktop, "
        "then right-click the file and choose Restore. It goes back where it was.")),
    (r"svuot\w*[^.?!]{0,12}cestino|\bempty\w*[^.?!]{0,12}\b(trash|bin)\b",
     tr("Right-click the Trash icon on the desktop, then Empty Trash. "
        "Or tell me “empty the trash”: I'll ask you to confirm and empty it for you.")),
    (r"cestino|\btrash\b|recycle bin",
     tr("The Trash is on the desktop, at the top left: double-click to open it. "
        "Or tell me “open the trash”.")),
    (r"sfondo|wallpaper|desktop background|background (image|picture)",
     tr("Settings › Appearance › Wallpaper: click one of the ZETA RAYS wallpapers, or Choose… "
        "for your own image. Or tell me “set the red waves wallpaper”.")),
    (r"colore|colori|accento|\bcolou?rs?\b|\baccent\b",
     tr("Settings › Appearance › Accent Color: blue, red, white, green, or + to pick your own. "
        "It changes the whole interface at once. Or tell me “open appearance settings”.")),
    (r"\btema\b|chiaro|scuro|modalita notte|\btheme\b|dark mode|light mode|night mode",
     tr("Settings › Appearance › Theme: Dark or Light. Or tell me “open appearance settings”.")),
    (r"\bdock\b|barra|taskbar|\bbar\b",
     tr("The bar is at the bottom: on the left the ZETA RAYS symbol (the app list) and the "
        "workspaces 1 2 3, in the middle the dock with your apps, on the right search, network, "
        "volume, clock and power. Position and apps can be changed in Settings › Dock.")),
    (r"terminal|console|shell|riga di comando|command line",
     tr("The terminal is in the dock at the bottom: the icon with the >_ symbol. "
        "Or tell me “open the terminal” and I'll open it.")),
    (r"browser|firefox|internet|navigare|navigatore|browse",
     tr("The browser is Firefox: in the dock at the bottom, the globe icon. "
        "Or tell me “open the browser” and I'll open it.")),
    (r"gestore (dei )?file|file manager|esplora risorse|file explorer",
     tr("The file manager is in the dock at the bottom: the folder icon. You can also open it by "
        "double-clicking Home on the desktop. Or tell me “open the file manager”.")),
    (r"impostazion|settings|preferences",
     tr("Settings is in the dock at the bottom: the icon with the sliders. Or right-click the "
        "desktop › Customize, or tell me “open settings”.")),
    (r"editor|blocco note|scrivere (un )?testo|notepad|write (a )?text",
     tr("The text editor is in the dock at the bottom: the pencil icon. Or tell me “open the editor”.")),
    (r"calcolatric|calculator",
     tr("The Calculator is in the app list: click the ZETA RAYS symbol at the bottom left, "
        "then Calculator. Or tell me “open the calculator”.")),
    (r"monitor|processi|task manager|processes",
     tr("The system monitor is in the dock at the bottom: the speedometer icon. "
        "Or tell me “open the monitor”.")),
    (r"stamp|\bprint",
     tr("Settings › Printers: network printers are found automatically, USB printers as soon "
        "as you plug them in.")),
    (r"(apr|legg|vede|guarda|ascolt)\w*[^.?!]{0,20}\b(file|pdf|foto|immagine|video|documento|zip|rar|archivio|canzone|mp3)\b"
     r"|\b(open|read|view|see|watch|listen|play)\w*[^.?!]{0,20}\b(files?|pdfs?|photos?|pictures?|images?|videos?"
     r"|documents?|zip|rar|archives?|songs?|mp3)\b",
     tr("Double-click the file, in the file manager or on the desktop: it opens with the right app. "
        "PDFs and documents in the viewer, photos and images in the image viewer, video and music in "
        "the player, zip, rar and 7z in the archive manager. Or tell me “open the file” followed by "
        "its name and I'll find it and open it.")),
    (r"documenti|\bdocuments\b",
     tr("The Documents folder is inside Home: double-click Home on the desktop, then Documents. "
        "Or tell me “open documents”.")),
    (r"download|scaricat",
     tr("Downloaded files are in the Downloads folder, inside Home. Or tell me “open downloads”.")),
    (r"immagini|foto|\bpictures\b|\bphotos\b|\bimages\b",
     tr("The Pictures folder is inside Home. Or tell me “open pictures”.")),
    (r"musica|\bmusic\b",
     tr("The Music folder is inside Home. Or tell me “open music”.")),
    (r"\bvideos?\b",
     tr("The Videos folder is inside Home. Or tell me “open videos”.")),
    (r"\bhome\b|cartella personale|miei file|my files|home folder",
     tr("Home is your personal folder: you'll find it on the desktop, at the top left. Inside are "
        "Documents, Pictures, Music, Downloads and Videos. Or tell me “open home”.")),
]


def _sapere(t: str) -> Intent | None:
    if not re.search(_DOMANDA, t):
        return None
    for schema, risposta in _SAPERE:
        if re.search(schema, t):
            return Intent(None, {}, risposta)
    return None


_ESTENSIONI = (r"pdf|png|jpe?g|gif|webp|heic|svg|txt|md|docx?|odt|rtf|xlsx?|ods|csv|pptx?|odp|"
               r"mp3|wav|flac|ogg|m4a|mp4|mov|avi|mkv|webm|zip|rar|7z|tar|gz|iso")


# «le foto», «i video»...: un tipo di file, cioè più estensioni insieme
_TIPI = [
    (r"(le |the |my )?(foto|fotografie|immagini|photos|pictures|images)",
     "*.jpg,*.jpeg,*.png,*.heic,*.webp,*.gif", tr("Searching for photos.")),
    (r"(i |the |my )?(video|filmati|videos)",
     "*.mp4,*.mov,*.mkv,*.avi,*.webm", tr("Searching for videos.")),
    (r"(la |the |my )?(musica|canzoni|brani|music|songs)",
     "*.mp3,*.flac,*.wav,*.ogg,*.m4a", tr("Searching for music.")),
    (r"(i |the |my )?(documenti|pdf e documenti|documents)",
     "*.pdf,*.doc,*.docx,*.odt,*.txt,*.rtf,*.md", tr("Searching for documents.")),
]


def _ricerca(t: str) -> Intent | None:
    m = re.search(r"^(?:cerca|cercami|trova|trovami|dove (?:si trova|e|sta|trovo|ho messo)|dov'?e)\s+"
                  r"(?:tutti |tutte )?(?:i |il |lo |la |le |gli |l'|un |una |dei |delle |miei |mie )?"
                  r"(?:file |files )?(.+?)\s*\??$", t)
    if not m:
        m = re.search(r"^(?:search(?: for)?|find(?: me)?|look for|locate"
                      r"|where (?:is|are|did i (?:put|save))|where'?s)\s+"
                      r"(?:all )?(?:the |my |a |an |some )?"
                      r"(?:files? (?:called |named )?)?(.+?)\s*\??$", t)
    if not m:
        return None
    resto = m.group(1)
    # «cerca su internet…» e «cerca di…» non sono ricerche di file
    if re.search(r"\b(su internet|su google|sul web|online|in rete"
                 r"|on the internet|on google|on the web|on youtube|on wikipedia)\b", t) or \
            re.match(r"(cerca|cercami|trova|trovami) di ", t) or \
            re.match(r"(search|find) (out|a way)\b", t):
        return None
    args = {}
    if re.search(r"\b(di oggi|modificat\w* oggi|da oggi|oggi|today)\b", resto):
        args["oggi"] = True
    g = re.search(r"(?:degli |negli |ultimi |ultime )+(\d{1,3}) giorni"
                  r"|(?:in |from |of )?(?:the )?(?:last|past) (\d{1,3}) days", resto)
    if g:
        args["giorni"] = int(g.group(1) or g.group(2))
    elif re.search(r"(questa|ultima) settimana|della settimana|(this|last|past) week", resto):
        args["giorni"] = 7
    resto = re.sub(r"\b(modificat\w*|creat\w*|recenti|di oggi|da oggi|oggi|della settimana|questa settimana|"
                   r"ultima settimana|(degli |negli |ultimi |ultime )+\d{1,3} giorni"
                   r"|modified|created|changed|recent|from today|today|(from |of )?this week|last week|past week"
                   r"|(in |from |of )?(the )?(last|past) \d{1,3} days)\b", " ", resto)
    resto = re.sub(r"\s+", " ", resto).strip(" .?!")
    resto = re.sub(r"\s+(di|del|della|dei|delle|da|from|of|in|since)$", "", resto)   # «le foto di [questa settimana]»
    resto = re.sub(r"^(il |i |la |le |the |my )?(documento|documenti|file|document|documents|files) (?=\S)",
                   "", resto)   # «il documento fattura»
    if not resto:
        return None
    for schema, estensioni, risposta in _TIPI:
        if re.fullmatch(schema, resto):
            args["pattern"] = estensioni
            return Intent("find_files", args, risposta)
    if re.fullmatch(_ESTENSIONI, resto):
        args["pattern"] = "*." + resto
        detto = tr("Searching for {ext} files.").format(ext=resto.upper())
    else:
        args["pattern"] = "*%s*" % resto
        detto = tr("Searching for “{name}”.").format(name=resto)
    return Intent("find_files", args, detto)


def _nome_cartella(chiave: str) -> str:
    nomi = {"documenti": tr("Documents"), "download": tr("Downloads"), "immagini": tr("Pictures"),
            "musica": tr("Music"), "video": tr("Videos"), "scrivania": tr("Desktop"),
            "home": tr("Home")}
    return nomi.get(chiave, chiave)


def parse(text: str) -> Intent | None:
    t = _norm(text)
    if not t:
        return None

    # --- «come va la rete»: stato reale, non una spiegazione ---
    # Va prima di _sapere(), altrimenti «ho internet?» finisce nella risposta
    # sul browser e «come va la rete» arriva al modello, che non può guardare
    # le interfacce. Si escludono le frasi che chiedono il pannello o come
    # navigare: quelle non sono domande sullo stato.
    if not re.search(r"impostazion|settings|pannello|panel|^apri\b|^open\b|navig|browse", t) and \
       re.search(r"\b(come va|come sta|stato|funziona|non funziona|controlla|verifica|c ?e)\b"
                 r"[^.?!]{0,24}\b(rete|wifi|wi fi|connessione|internet)\b"
                 r"|\b(rete|wifi|connessione|internet)\b[^.?!]{0,16}(va|funziona|attiva|connessa|caduta)"
                 r"|sono (connesso|collegato|online)|network status|am i (online|connected)"
                 r"|\b(do i have|is there|check|test)\b[^.?!]{0,16}\b(internet|connection|network|wifi|wi fi)\b"
                 r"|\b(internet|wifi|wi fi|network|connection)\b[^.?!]{0,16}\b(working|down|connected|status)\b", t):
        return Intent("network_status", {}, tr("Checking the network."))

    domanda = _sapere(t)
    if domanda:
        return domanda

    # --- cancellare un file per nome --------------------------------------
    # «elimina la cartella X» era gia capito, «cancella il file X» no: due modi
    # di dire la stessa cosa non possono comportarsi in modo diverso.
    m = re.search(r"\b(?:cancella|elimina|butta|cestina|rimuovi)\b\s*(?:mi\s+)?"
                  r"(?:il |lo |la |i |gli |le |l )?"
                  # il sostantivo si consuma solo se e' una parola a se: senza
                  # lo spazio finale, «cestina foto.jpg» perdeva il «foto».
                  r"(?:(?:file|documento|cartella|foto|immagine)\s+)?"
                  r"[\"«]?([^\"»]{2,60}?)[\"»]?[.!]?$", t)
    inglese = False
    if not m and not re.search(_DOMANDA, t):
        # in inglese «trash» e anche un nome («open the trash»): come verbo
        # vale solo a inizio frase
        inglese = True
        m = re.search(r"(?:^(?:please )?trash|\b(?:delete|erase))\s+"
                      r"(?:the |my |this |that )?"
                      r"(?:(?:file|document|folder|photo|picture|image)\s+)?"
                      r"[\"«“]?([^\"»”]{2,60}?)[\"»”]?[.!]?$", t)
    if m and not re.search(r"\b(tutto|tutti|cestino|sistema|disco|programma|app)\b", m.group(1)) \
            and not (inglese and re.search(r"\b(everything|all|trash|bin|system|disk|program|history)\b",
                                           m.group(1))):
        nome = m.group(1).strip()
        return Intent("trash_file", {"name": nome},
                      tr("Moving “{name}” to the Trash.").format(name=nome))

    # --- finestre aperte ---------------------------------------------------
    if re.search(r"\b(che|quali|quanti)\b[^.?!]{0,24}\b(programmi|applicazioni|finestre|app)\b"
                 r"[^.?!]{0,16}\b(apert\w+|in esecuzione|attiv\w+)\b"
                 r"|\bfinestre aperte\b|\bcosa ho aperto\b"
                 r"|\b(what|which|how many)\b[^.?!]{0,24}\b(programs|apps|applications|windows)\b"
                 r"[^.?!]{0,16}\b(open|running|active)\b"
                 r"|\bwhat do i have open\b", t):
        return Intent("list_windows", {}, tr("Here are the open windows."))

    # --- colore d'accento a parole ---------------------------------------
    # L'azione vuole un #RRGGBB: nessuno lo dice a voce. Qui i colori che la
    # gente nomina davvero diventano i toni usati dal sistema.
    colori = "|".join(sorted(_COLORI, key=len, reverse=True))
    m = re.search(r"\b(?:cambia|metti|imposta|usa|voglio|change|set|use|make|switch)\b[^.?!]{0,24}"
                  r"\b(?:colore|accento|tinta|colou?r|accent)\b[^.?!]{0,12}\b(%s)\b" % colori, t)
    if not m:
        m = re.search(r"\b(?:accento|colore|accent|accent colou?r)\s+(?:to\s+)?(%s)\b" % colori, t)
    if not m:
        m = re.search(r"\b(%s)\s+accent\b" % colori, t)
    if m:
        nome = m.group(1)
        return Intent("set_accent", {"color": _COLORI[nome]},
                      tr("Setting the accent color to {color}.").format(color=nome))

    # --- spegnere lo schermo (non il computer) ----------------------------
    if re.search(r"\bspegni\b[^.?!]{0,10}\b(lo )?(schermo|monitor|display)\b"
                 r"|\bschermo\b[^.?!]{0,8}\bspegni\b"
                 r"|\b(turn|switch) off (the )?(screen|monitor|display)\b"
                 r"|\b(turn|switch) (the )?(screen|monitor|display) off\b|^screen off$", t):
        return Intent("screen_off", {}, tr("Turning off the screen."))

    # --- luminosita' ------------------------------------------------------
    m = re.search(r"\b(?:metti|imposta|porta)\b[^.?!]{0,20}luminosit\w*\s*(?:a|al)?\s*(\d{1,3})", t)
    if not m:
        m = re.search(r"\b(?:set|put|make|turn)\b[^.?!]{0,20}brightness\s*(?:to|at)?\s*(\d{1,3})", t)
    if m:
        return Intent("set_brightness", {"level": max(0, min(100, int(m.group(1))))},
                      tr("Setting the brightness."))
    if re.search(r"\b(alza|aumenta|su)\b[^.?!]{0,16}luminosit\w*|luminosit\w*[^.?!]{0,10}\b(alza|aumenta)\b"
                 r"|\b(raise|increase|turn up|brighten)\b[^.?!]{0,16}brightness|brightness[^.?!]{0,10}\bup\b", t):
        return Intent("set_brightness", {"level": 100}, tr("Turning up the brightness."))
    if re.search(r"\b(abbassa|riduci|diminuisci)\b[^.?!]{0,16}luminosit\w*"
                 r"|luminosit\w*[^.?!]{0,10}\b(abbassa|riduci)\b"
                 r"|\b(lower|decrease|reduce|dim|turn down)\b[^.?!]{0,16}brightness|brightness[^.?!]{0,10}\bdown\b", t):
        return Intent("set_brightness", {"level": 30}, tr("Turning down the brightness."))

    # --- cercare sul web -------------------------------------------------
    # Prima queste frasi venivano escluse dalla ricerca dei file e finivano al
    # modello: significava aspettare il caricamento del modello per aprire una
    # pagina. Ora si apre e basta. Il motore predefinito e' DuckDuckGo, che non
    # traccia chi cerca; se l'utente nomina un motore, si usa quello.
    _MOTORI = r"(google|internet|web|duckduckgo|youtube|wikipedia)"
    cosa = motore = None
    m = re.search(r"\b(?:cerca|cercami|trova|trovami|guarda|cerchi)\b\s*(?:mi\s+)?(.{2,80}?)"
                  r"\s+(?:su|sul|in|nel)\s+" + _MOTORI + r"\b[.?!]?$", t) or \
        re.search(r"\b(?:search(?: for)?|look up|look for|find)\b\s+(.{2,80}?)"
                  r"\s+(?:on|in)\s+(?:the\s+)?" + _MOTORI + r"\b[.?!]?$", t)
    if m:
        cosa, motore = m.group(1), m.group(2)
    else:
        m2 = re.search(r"\b(?:cerca|cercami|trova|trovami)\b\s+(?:su|sul|in|nel)\s+"
                       + _MOTORI + r"\b\s+(.{2,80})$", t) or \
            re.search(r"\b(?:search|look up)\b\s+(?:on\s+)?(?:the\s+)?" + _MOTORI
                      + r"\b\s+(?:for\s+)?(.{2,80})$", t)
        if m2:
            motore, cosa = m2.group(1), m2.group(2)
    if cosa:
        cosa = cosa.strip(" .?!")
        q = _url_quote(cosa)
        motori = {
            "google": "https://www.google.com/search?q=%s",
            "youtube": "https://www.youtube.com/results?search_query=%s",
            # Wikipedia nella lingua del sistema
            "wikipedia": "https://" + language() + ".wikipedia.org/w/index.php?search=%s",
        }
        url = motori.get(motore, "https://duckduckgo.com/?q=%s") % q
        return Intent("open_url", {"url": url},
                      tr("Searching the web for “{query}”.").format(query=cosa))

    # --- chiudere la finestra ---
    if re.search(r"chiudi (questa |la )?finestra|close (this |the )?(current |active )?window"
                 r"|chiudi l'app|close (this|the current) app\b", t):
        return Intent("close_active_window", {}, tr("Closing the active window."))

    # --- chiudere un programma per nome: «chiudi firefox» ---
    # Va dopo la finestra attiva, altrimenti «chiudi la finestra» verrebbe
    # letto come «chiudi il programma chiamato la finestra».
    # «spegni» resta fuori di proposito: «spegni il wifi» e «spegni lo schermo»
    # non chiudono un programma, e con quel verbo qui dentro finivano qui.
    m = re.search(r"\b(chiudi|termina|esci da)\s+(?:il |lo |la |l )?(?:programma |app |applicazione )?([a-z0-9 .+-]{2,30})$", t) or \
        re.search(r"\b(close|quit|exit)\s+(?:the )?(?:program |app |application )?([a-z0-9 .+-]{2,30})$", t)
    if m and not re.search(r"\b(computer|sistema|schermo|finestra|tutto|sessione"
                           r"|wifi|wi fi|bluetooth|rete|volume|audio|musica|luce"
                           r"|luminosita|schermata|sessione"
                           r"|system|screen|windows?|everything|all|session|network|music|light"
                           r"|brightness|screenshot|full ?screen)\b", m.group(2)):
        nome = m.group(2).strip()
        return Intent("close_application", {"app": nome}, tr("Closing {name}.").format(name=nome))

    # --- schermata ---
    if re.search(r"(fai|scatta|cattura|prendi|salva)[^.?!]{0,14}(schermata|screenshot|foto dello schermo)"
                 r"|^screenshot$|^schermata$"
                 r"|\b(take|grab|capture|save)\b[^.?!]{0,14}(screenshot|screen ?shot|screen capture)"
                 r"|\bcapture (the )?screen\b", t):
        return Intent("screenshot", {}, tr("Saving a screenshot."))

    # --- cercare DENTRO i file, non nei nomi ---
    # Le parole di servizio («nei file», «la parola») vanno consumate dallo
    # schema una per una: contandole a caratteri, «cerca dentro i file la
    # parola fattura» cercava «ola fattura».
    m = re.search(r"(?:cerca|trova|cercami)\b[^.?!]{0,20}?\b(?:dentro|nel contenuto|nei contenuti|nel testo)\b"
                  r"(?:\s+(?:a|ai|dei|delle|di|nei|nelle|d|i|gli|le|la|il|lo)(?!\s+(?:parola|frase|testo|termine)\b))?"
                  r"(?:\s+(?:file|documenti|documento|pdf))?"
                  r"(?:\s+(?:la|il|lo)\s+(?:parola|frase|testo|termine))?"
                  r"\s+[\"«]?([^\"»]{2,60})[\"»]?$", t)
    if not m:
        m = re.search(r"(?:quale|che) (?:file|documento)[^.?!]{0,20}(?:parla di|contiene|dice)\s+(.{2,60})$", t)
    if not m:
        m = re.search(r"(?:search|find|look)\b[^.?!]{0,20}?\b(?:inside|within|in the contents? of|in the text of)\b"
                      r"(?:\s+(?:the|my|all))?"
                      r"(?:\s+(?:files|documents|document|pdfs?))?"
                      r"(?:\s+for)?"
                      r"(?:\s+the\s+(?:word|phrase|text|term))?"
                      r"\s+[\"«“]?([^\"»”]{2,60})[\"»”]?$", t)
    if not m:
        m = re.search(r"(?:which|what) (?:files?|documents?)[^.?!]{0,20}"
                      r"(?:talks? about|contains?|mentions?|says?)\s+(.{2,60})$", t)
    if m:
        testo = m.group(1).strip(" .")
        return Intent("search_content", {"text": testo},
                      tr("Searching inside files for “{text}”.").format(text=testo))

    # --- rinominare ---
    m = re.search(r"rinomina\s+[\"«]?([^\"»]{1,60}?)[\"»]?\s+(?:in|come)\s+[\"«]?([^\"»]{1,60})[\"»]?$", t) or \
        re.search(r"\brename\s+[\"«“]?([^\"»”]{1,60}?)[\"»”]?\s+(?:to|as|into)\s+[\"«“]?([^\"»”]{1,60})[\"»”]?$", t)
    if m:
        vecchio, nuovo = m.group(1).strip(), m.group(2).strip(" .")
        return Intent("rename_file", {"name": vecchio, "new_name": nuovo},
                      tr("Renaming “{old}” to “{new}”.").format(old=vecchio, new=nuovo))

    # --- spostare ---
    m = re.search(r"sposta\s+[\"«]?([^\"»]{1,60}?)[\"»]?\s+(?:in|dentro|nella|nel)\s+[\"«]?([^\"»]{1,40})[\"»]?$", t) or \
        re.search(r"\bmove\s+[\"«“]?([^\"»”]{1,60}?)[\"»”]?\s+(?:to|into|in)\s+(?:the\s+)?"
                  r"[\"«“]?([^\"»”]{1,40})[\"»”]?$", t)
    if m and not re.search(r"cestino|\btrash\b|\bbin\b|recycle", m.group(2)) \
            and not re.search(r"\b(window|workspace)\b", m.group(1)):
        che, dove = m.group(1).strip(), m.group(2).strip(" .")
        return Intent("move_file", {"name": che, "folder": dove},
                      tr("Moving “{name}” to {folder}.").format(name=che, folder=dove))

    # --- gestione delle finestre ---
    if re.search(r"\b(minimizza|minimize|minimise)\b|(riduci|nascondi|hide).*(finestra|window)", t):
        return Intent("minimize_window", {}, tr("Minimizing the active window."))
    if re.search(r"\b(massimizza|maximize|maximise)\b|(ingrandisci|schermo intero|full ?screen).*(finestra|window)", t):
        return Intent("maximize_window", {}, tr("Maximizing the active window."))
    # «quante finestre ho aperte», «dimmi le finestre», «che finestre ci sono»:
    # chi parla non usa il verbo che ci aspettavamo, e la frase finiva al
    # modello, che risponde di non poter sapere quali finestre sono aperte.
    if re.search(r"(quante|quali|che|mostra|mostrami|elenca|dimmi|vedere"
                 r"|how many|which|what|show|list|tell me)"
                 r"[^.?!]{0,24}\b(finestre|window)|"
                 r"\bfinestre\b[^.?!]{0,12}(aperte|ridotte|attive)"
                 r"|\bwindows\b[^.?!]{0,12}\b(open|minimized|active)\b", t):
        return Intent("list_windows", {}, tr("Here are the windows."))

    # --- aprire un sito ---
    if re.search(r"\b(apri|vai su|portami su|mostrami|open|go to|take me to|show me|visit)\b[^.?!]{0,20}"
                 r"(https?://|www\.|\b[a-z0-9-]+\.(it|com|org|net|eu|io|dev)\b)", t):
        m = re.search(r"(https?://\S+|www\.\S+|\b[a-z0-9-]+\.(?:it|com|org|net|eu|io|dev)\b\S*)", t)
        if m:
            return Intent("open_url", {"url": m.group(1)}, tr("Opening the website."))

    # --- aprire un file per nome ---
    if re.search(r"\b(apri|open)\b[^.?!]{0,30}\b(il |la |lo |l |the |my )?"
                 r"(file|documento|immagine|foto|video|pdf|document|image|photo|picture)\b", t):
        m = re.search(r"\b(?:file|documento|immagine|foto|video|pdf|document|image|photo|picture)\s+"
                      r"(?:chiamat[oa]\s+|called\s+|named\s+)?([\w .-]+)", t)
        if m and m.group(1).strip() and m.group(1).strip() not in ("folder", "folders"):
            return Intent("open_file", {"name": m.group(1).strip()},
                          tr("Finding and opening the file."))

    # --- sfondo della scrivania ---
    if re.search(r"(cambia|cambiami|metti|imposta|change|set|put|use)[^.?!]{0,20}\b(sfondo|wallpaper|background)\b", t):
        if re.search(r"(predefinit|originale|di zeta|default|original)", t):
            return Intent("set_wallpaper", {"name": "predefinito"},
                          tr("Restoring the ZETA RAYS wallpaper."))
        # uno degli sfondi di ZETA RAYS per nome («metti lo sfondo onde rosse»)
        m = re.search(r"\b(?:sfondo|wallpaper|background)\b\s+(?:con |in |a |to )?([\w -]+?)\s*[.?!]*$", t)
        if m:
            from system import sfondi
            if sfondi.cerca(m.group(1)):
                return Intent("set_wallpaper", {"name": m.group(1).strip()}, tr("Changing the wallpaper."))
        m = re.search(r"\b(?:sfondo|wallpaper|background)\b[^.?!]{0,10}?\b(?:con|in|a|to|with)\s+([\w ./-]+)", t)
        if m and m.group(1).strip():
            return Intent("set_wallpaper", {"name": m.group(1).strip()}, tr("Changing the wallpaper."))
        return Intent("open_settings", {"page": "aspetto"},
                      tr("Opening Settings so you can pick a wallpaper."))

    # --- tema chiaro / scuro ---
    if re.search(r"tema (chiaro|light)|modalita chiara|passa al chiaro"
                 r"|light (theme|mode)|switch to light|(theme|mode) to light", t):
        return Intent("set_theme", {"tema": "chiaro"}, tr("Switching to the light theme."))
    if re.search(r"tema (scuro|dark)|modalita scura|passa allo scuro"
                 r"|dark (theme|mode)|switch to dark|(theme|mode) to dark", t):
        return Intent("set_theme", {"tema": "scuro"}, tr("Switching to the dark theme."))

    # --- domande banali: risposte immediate, senza scomodare il modello ---
    if re.search(r"che ore sono|che ora e|dimmi l ?ora|^ora$|what time|tell me the time|^time$", t):
        return Intent("current_time", {}, tr("It's…"))
    if re.search(r"che giorno e|che data e|^data$|dimmi la data|what day|what.*date|today'?s date|^date$", t):
        return Intent("current_date", {}, tr("Today is…"))
    if re.search(r"(quanta|stato).*batteria|^batteria$|battery", t):
        return Intent("battery_status", {}, tr("Checking the battery."))
    if re.search(r"(che |quale |quanto )?(volume|audio)[^.?!]{0,16}\b(e|adesso|ora)\b"
                 r"|^volume$|a che volume"
                 r"|what'?s the volume|what is the volume|current volume|how loud", t):
        return Intent("volume_status", {}, tr("Checking the volume."))
    if re.search(r"a che rete|come mi chiamo in rete|nome del computer|^hostname$"
                 r"|computer name|what'?s my computer called", t):
        return Intent("system_info", {}, tr("Here's the system information."))

    # --- stato del sistema ---
    if re.search(r"(uso|quanto)[^.?!]*\b(cpu|processore)\b|\bcpu\b[^.?!]*(uso|carico|percentuale)"
                 r"|what.*\bcpu\b|\b(cpu|processor) (usage|load)\b", t):
        return Intent("cpu_usage", {}, tr("Checking CPU usage."))
    if re.search(r"(quanta|uso|quanto)[^.?!]*\b(ram|memoria)\b|\bmemoria\b[^.?!]*(uso|libera|disponibile)"
                 r"|how much (ram|memory)|\b(ram|memory) usage\b|\bfree (ram|memory)\b", t):
        return Intent("memory_usage", {}, tr("Checking memory."))
    if re.search(r"spazio.*(disco|libero)|(uso|quanto).*disco|disk (usage|space)"
                 r"|free space|storage space|how much space", t):
        return Intent("disk_usage", {}, tr("Checking disk space."))
    # «ip» senza confini di parola stava dentro «zip», «equipaggio», «principio»:
    # chiedere come si apre un file zip faceva rispondere con l'indirizzo IP.
    if re.search(r"\b(mio |il mio )ip\b|\bindirizzo ip\b|\bip\b.{0,12}\b(pubblico|locale|privato)\b"
                 r"|^ip$|what.*\bmy ip\b|\bip address", t):
        return Intent("ip_address", {}, tr("Here are your IP addresses."))
    if re.search(r"da quanto.*acceso|\buptime\b|tempo di attivita"
                 r"|how long (has|have|is|was) [^.?!]{0,25}\b(on|running|up)\b", t):
        return Intent("uptime", {}, tr("How long the system has been on."))
    if re.search(r"informazioni.*(sistema|zeta)|system info|che sistema|what system|about this (computer|system)", t):
        return Intent("system_info", {}, tr("Here's the system information."))
    if re.search(r"process(i|es).*(attivi|in esecuzione|cpu)|cosa (sta |)consuma|what.*using.*cpu|running process", t):
        return Intent("open_system_monitor", {"section": "processes"}, tr("Opening processes in the Monitor."))

    # --- monitor di sistema / sicurezza ---
    if re.search(_OPEN + r".*(monitor|monitoraggio)", t):
        return Intent("open_system_monitor", {}, tr("Opening the System Monitor."))
    if re.search(_OPEN + r".*(sicurezza|security|firewall|strumenti di sicurezza)", t):
        return Intent("open_security", {}, tr("Opening ZETA RAYS Security."))

    # --- terminale ---
    if re.search(_OPEN + r".*(terminale|terminal|console|shell)", t) or t in ("terminale", "terminal"):
        return Intent("open_terminal", {}, tr("Opening the terminal."))

    # --- impostazioni (con eventuale pagina) ---
    if re.search(_OPEN + r".*(impostazion|settings|preferenze|preferences|configurazione)", t):
        page = _find(_SETTINGS, t)
        if page:
            from .actions import nome_pagina
            return Intent("open_settings", {"page": page},
                          tr("Opening Settings › {page}.").format(page=nome_pagina(page)))
        return Intent("open_settings", {}, tr("Opening Settings."))
    if re.search(r"(impostazion|settings).*(rete|wifi|audio|bluetooth|sicurezza|ai|network|sound|security)"
                 r"|(network|wifi|sound|audio|bluetooth|security|appearance) settings", t):
        page = _find(_SETTINGS, t)
        return Intent("open_settings", {"page": page} if page else {}, tr("Opening Settings."))

    # --- Wi-Fi (prima dell'energia: «spegni il wifi» non deve spegnere tutto) ---
    if re.search(r"(attiva|accendi|enable|turn on|switch on)[^.?!]{0,8}(wi.?fi|wireless)"
                 r"|\b(turn|switch) (the )?(wi.?fi|wireless) on\b", t):
        return Intent("wifi_toggle", {"on": True}, tr("Turning Wi-Fi on."))
    if re.search(r"(disattiva|spegni|disable|turn off|switch off)[^.?!]{0,8}(wi.?fi|wireless)"
                 r"|\b(turn|switch) (the )?(wi.?fi|wireless) off\b", t):
        return Intent("wifi_toggle", {"on": False}, tr("Turning Wi-Fi off."))

    # --- energia ---
    # «spegni» da solo, o riferito al computer. NON «spegni lo schermo», «spegni
    # il wifi», «spegni il bluetooth»: prima bastava la parola «spegni» in
    # qualunque posto, e chiedere di spegnere lo schermo proponeva di spegnere
    # il computer. La conferma evitava il disastro, ma la domanda era sbagliata.
    if re.search(r"^(ora |adesso |now |please )?(spegni(ti)?|spegnere|shutdown|shut down|power off|turn off)"
                 r"( (il|questo|the|this|my) (computer|pc|sistema|tutto|system|laptop))?[.!]?$"
                 r"|\bspegni(re)? (il |questo )?(computer|pc|sistema)\b"
                 r"|\bchiudi (il |questo )?(computer|pc|sistema)\b"
                 r"|\b(shut ?down|power off|turn off|switch off) (the |this |my )?(computer|pc|system|laptop)\b", t):
        return Intent("power_off", {}, tr("Shutting down the computer."))
    if re.search(r"\briavvia(re)?\b|\breboot\b|riavviare il (computer|sistema)"
                 r"|^(please )?restart( (the|this|my) (computer|pc|system|laptop))?[.!]?$"
                 r"|\brestart (the |this |my )?(computer|pc|system|laptop)\b", t):
        return Intent("reboot", {}, tr("Restarting the computer."))
    if re.search(r"\bsospendi\b|\bsospensione\b|\bsuspend\b|metti in pausa il computer"
                 r"|put (the |this |my )?(computer|pc|laptop) to sleep|^sleep$", t):
        return Intent("suspend", {}, tr("Suspending the computer."))
    if re.search(r"blocca( lo)? schermo|\block screen\b|blocca il computer"
                 r"|\block (the |my )?(screen|computer|pc)\b", t):
        return Intent("lock_screen", {}, tr("Locking the screen."))
    if re.search(r"\besci\b|disconnett|log ?out|chiudi (la )?sessione|sign out|log me out|end (the )?session", t):
        return Intent("log_out", {}, tr("Logging out."))

    # --- volume ---
    m = re.search(r"(?:volume|audio|sound)[^.?!]{0,12}?\b(\d{1,3})\s*%?", t)
    if m and re.search(r"metti|imposta|porta|volume a|al |\bset\b|\bto\b|\bat\b", t):
        return Intent("set_volume", {"level": int(m.group(1))}, tr("Setting the volume."))
    # relativo al volume attuale: prima «alza» portava sempre all'80%
    # (da 95 lo abbassava) e «abbassa» sempre al 30%
    if re.search(r"(alza|aumenta|raise|increase|turn up)[^.?!]{0,10}(volume|audio|sound)"
                 r"|\b(volume|sound) up\b|\blouder\b", t):
        return Intent("set_volume", {"step": "su", "amount": 10}, tr("Turning up the volume."))
    if re.search(r"(abbassa|riduci|lower|decrease|reduce|turn down)[^.?!]{0,10}(volume|audio|sound)"
                 r"|\b(volume|sound) down\b|\b(quieter|softer)\b", t):
        return Intent("set_volume", {"step": "giu", "amount": 10}, tr("Turning down the volume."))
    if re.search(r"\b(silenzia|muto|mute|zittisci|silence)\b", t):
        return Intent("set_volume", {"mute": True}, tr("Muting the audio."))

    # --- luminosità ---
    m = re.search(r"luminosit[aà][^.?!]{0,12}?\b(\d{1,3})\s*%?|brightness[^.?!]{0,12}?\b(\d{1,3})\s*%?", t)
    if m:
        return Intent("set_brightness", {"level": int(m.group(1) or m.group(2))},
                      tr("Adjusting the brightness."))

    # --- programmi ---
    m = re.search(r"\binstalla(?:re)?\b\s+(?:il |lo |la |l )?([a-z0-9.+-]{2,40})", t) or \
        re.search(r"^(?:please |can you |could you )?install\s+(?:the )?(?:program |app |package )?"
                  r"([a-z0-9.+-]{2,40})[.!?]?$", t)
    if m:
        nome = m.group(1).strip()
        return Intent("install_package", {"name": nome}, tr("Installing {name}.").format(name=nome))
    m = re.search(r"\b(?:disinstalla(?:re)?|rimuovi)\b\s+(?:il |lo |la |l )?([a-z0-9.+-]{2,40})", t) or \
        re.search(r"^(?:please |can you |could you )?(?:uninstall|remove)\s+(?:the )?(?:program |app |package )?"
                  r"([a-z0-9.+-]{2,40})[.!?]?$", t)
    if m:
        nome = m.group(1).strip()
        return Intent("remove_package", {"name": nome}, tr("Removing {name}.").format(name=nome))

    # --- nuova cartella ---
    m = re.search(r"(?:crea|nuova)[^.?!]{0,12}cartella\s+(?:chiamata\s+)?([\w .-]{1,40})", t) or \
        re.search(r"(?:create|make|new)[^.?!]{0,12}folder\s+(?:called\s+|named\s+)?([\w .-]{1,40})", t)
    if m and m.group(1).strip():
        return Intent("create_folder", {"name": m.group(1).strip()}, tr("Creating the folder."))

    # --- cestinare ---
    m = re.search(r"(?:cestina|butta|sposta nel cestino|elimina)\s+(?:il |lo |la |l )?(?:file\s+)?([\w .-]{1,40})", t) or \
        re.search(r"\bmove\s+(?:the |my )?(?:file\s+)?([\w .-]{1,40}?)\s+to (?:the )?(?:trash|bin|recycle bin)$", t)
    if m and m.group(1).strip() not in ("", "cestino", "trash"):
        return Intent("trash_file", {"name": m.group(1).strip()}, tr("Moving it to the Trash."))
    if re.search(r"svuota( il)? cestino|\bempty (the )?(trash|bin|recycle bin)\b", t):
        return Intent("empty_trash", {}, tr("Emptying the Trash."))

    # --- cercare file: «cerca fattura», «trova i file pdf di oggi»,
    #     «dove si trova il file prova.txt» ---
    ricerca = _ricerca(t)
    if ricerca:
        return ricerca

    # --- cartelle ---
    folder = _find(_FOLDERS, t)
    if folder and re.search(_OPEN + r"|cartella|folder", t):
        if folder == "cestino":
            return Intent("open_folder", {"name": folder}, tr("Opening the Trash."))
        return Intent("open_folder", {"name": folder},
                      tr("Opening the {name} folder.").format(name=_nome_cartella(folder)))

    # --- app specifiche ---
    app = _find(_APPS, t)
    if app and re.search(_OPEN, t):
        return Intent("open_application", {"app": app}, tr("Opening {name}.").format(name=app))

    # --- "apri <qualcosa>" generico: passa il nome a open_application ---
    m = re.search(_OPEN + r"\s+(?:l'|lo |la |il |le |gli |i |the |my )?([a-z0-9 .-]{2,30})$", t)
    if m:
        target = m.group(1).strip()
        # evita di intercettare frasi già gestite sopra
        if target and target not in ("finestra", "window"):
            return Intent("open_application", {"app": target},
                          tr("Trying to open {name}.").format(name=target))

    return None
