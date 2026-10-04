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


@dataclass
class Intent:
    action: str | None    # None: domanda con risposta certa, niente da eseguire
    args: dict
    reply: str            # cosa dice ZETA RAYS mentre esegue (o la risposta)


def _norm(text: str) -> str:
    text = text.lower().strip()
    text = "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")   # toglie gli accenti
    return re.sub(r"\s+", " ", text)


# cartelle riconosciute nel testo -> nome per l'azione open_folder
_FOLDERS = {
    r"documenti|documents": "documenti",
    r"download|scaricati|scaricat": "download",
    r"immagini|foto|pictures": "immagini",
    r"music|musica": "musica",
    r"video|filmati": "video",
    r"scrivania|desktop": "scrivania",
    r"home|personale|casa": "home",
    r"cestino": "cestino",
}

# app riconosciute -> nome per open_application
_APPS = {
    r"firefox|browser|internet|navigatore|il web|sul web": "firefox-esr",
    r"calcolatric|calcolatore": "gnome-calculator",
    r"editor|blocco note|testo": "gnome-text-editor",
    r"file|cartelle|gestore file": "thunar",
}

# pagine impostazioni
_SETTINGS = {
    r"rete|wifi|wi fi|network": "rete",
    r"audio|suono|volume": "audio",
    r"bluetooth": "bluetooth",
    r"aspetto|tema|colore|colori": "aspetto",
    r"\bai\b|intelligenza|assistente": "ai",
    r"sicurezza|firewall|security": "sicurezza",
    r"pacchett|applicazioni installate": "pacchetti",
    r"informazioni|info di sistema|sistema": "informazioni",
}


def _find(mapping: dict, text: str):
    for pattern, value in mapping.items():
        if re.search(pattern, text):
            return value
    return None


# verbi che indicano "apri/mostra/vai a"
_OPEN = r"(?:apri|aprimi|avvia|lancia|mostra|mostrami|fammi vedere|vai a|portami|vedere|visualizza|open|show|launch|go to)"


# «Come apro…», «dove trovo…»: domande su come si fa, non ordini.
# Il modello piccolo rispondeva a caso (mandava in Impostazioni per aprire il
# terminale, citava browser che non ci sono). Qui la risposta e un fatto del
# sistema, sempre giusta, e insegna il comando per farlo fare a ZETA.
# Le icone sono descritte per forma, non per posizione: il dock si riordina.
# I comandi suggeriti sono tutti instradati da questo stesso file.
# I toni sono quelli che il sistema propone in Impostazioni › Aspetto: chi
# dice «metti il rosso» si aspetta quel rosso, non uno qualunque.
_COLORI = {
    "blu": "#3A8DFF", "azzurro": "#3A8DFF", "rosso": "#E5484D",
    "verde": "#34C759", "bianco": "#FFFFFF", "giallo": "#FFB020",
    "arancione": "#FF8A34", "viola": "#A855F7", "rosa": "#FF6FA5",
    "turchese": "#2DD4BF", "grigio": "#8A8A8E",
}

_DOMANDA = r"^(?:ma |e |allora |scusa )?(?:come|dove|dov|in che modo)\b"   # «dov» per «dov'e»
_SAPERE = [
    (r"(recuper|ripristin)\w*|(file|documento|cartella)[^.?!]{0,25}(eliminat|cancellat|cestinat|pers)",
     "I file eliminati finiscono nel Cestino. Per recuperarne uno: doppio clic sull'icona "
     "Cestino della scrivania, poi clic destro sul file e Ripristina. Torna dov'era."),
    (r"svuot\w*[^.?!]{0,12}cestino",
     "Clic destro sull'icona Cestino della scrivania, poi Svuota il cestino. "
     "Oppure dimmi «svuota il cestino»: ti chiedo conferma e lo svuoto io."),
    (r"cestino",
     "Il Cestino è sulla scrivania, in alto a sinistra: doppio clic per aprirlo. "
     "Oppure dimmi «apri il cestino»."),
    (r"sfondo",
     "Impostazioni › Aspetto › Sfondo: un clic su uno degli sfondi di ZETA RAYS, oppure Scegli… "
     "per un'immagine tua. Oppure dimmi «metti lo sfondo onde rosse»."),
    (r"colore|colori|accento",
     "Impostazioni › Aspetto › Colore d'accento: blu, rosso, bianco, verde, oppure + per sceglierne uno. "
     "Cambia tutta l'interfaccia insieme. Oppure dimmi «apri le impostazioni aspetto»."),
    (r"\btema\b|chiaro|scuro|modalita notte",
     "Impostazioni › Aspetto › Tema: Scuro oppure Chiaro. Oppure dimmi «apri le impostazioni aspetto»."),
    (r"\bdock\b|barra",
     "La barra è in basso: a sinistra il simbolo ZETA RAYS (elenco delle applicazioni) e gli spazi di "
     "lavoro 1 2 3, al centro il dock con le applicazioni, a destra ricerca, rete, volume, ora e spegnimento. "
     "Posizione e applicazioni si cambiano in Impostazioni › Dock."),
    (r"terminal|console|shell|riga di comando",
     "Il terminale è nel dock, in basso: l'icona con il simbolo >_. Oppure dimmi «apri il terminale» e lo apro io."),
    (r"browser|firefox|internet|navigare|navigatore",
     "Il browser è Firefox: nel dock, in basso, l'icona del globo. Oppure dimmi «apri il browser» e lo apro io."),
    (r"gestore (dei )?file|file manager|esplora risorse",
     "Il gestore file è nel dock, in basso: l'icona della cartella. Si apre anche con un doppio clic su Home, "
     "sulla scrivania. Oppure dimmi «apri il gestore file»."),
    (r"impostazion",
     "Le Impostazioni sono nel dock, in basso: l'icona con i cursori. Oppure clic destro sulla scrivania › "
     "Personalizza, o dimmi «apri le impostazioni»."),
    (r"editor|blocco note|scrivere (un )?testo",
     "L'editor di testo è nel dock, in basso: l'icona della matita. Oppure dimmi «apri l'editor»."),
    (r"calcolatric",
     "La Calcolatrice è nell'elenco delle applicazioni: clic sul simbolo ZETA RAYS in basso a sinistra, "
     "poi Calcolatrice. Oppure dimmi «apri la calcolatrice»."),
    (r"monitor|processi|task manager",
     "Il monitor di sistema è nel dock, in basso: l'icona del tachimetro. Oppure dimmi «apri il monitor»."),
    (r"stamp",
     "Impostazioni › Stampanti: le stampanti di rete vengono trovate da sole, quelle USB appena le colleghi."),
    (r"(apr|legg|vede|guarda|ascolt)\w*[^.?!]{0,20}\b(file|pdf|foto|immagine|video|documento|zip|rar|archivio|canzone|mp3)\b",
     "Doppio clic sul file, nel gestore file o sulla scrivania: si apre con il programma giusto. PDF e documenti "
     "nel visore, foto e immagini nel visualizzatore, video e musica nel lettore, zip, rar e 7z nel gestore "
     "archivi. Oppure dimmi «apri il file» seguito dal nome e lo cerco e lo apro io."),
    (r"documenti", "La cartella Documenti è dentro Home: doppio clic su Home sulla scrivania, poi Documenti. "
                   "Oppure dimmi «apri i documenti»."),
    (r"download|scaricat", "I file scaricati sono nella cartella Scaricati, dentro Home. "
                           "Oppure dimmi «apri i download»."),
    (r"immagini|foto", "La cartella Immagini è dentro Home. Oppure dimmi «apri le immagini»."),
    (r"musica", "La cartella Musica è dentro Home. Oppure dimmi «apri la musica»."),
    (r"\bvideo\b", "La cartella Video è dentro Home. Oppure dimmi «apri i video»."),
    (r"\bhome\b|cartella personale|miei file",
     "Home è la tua cartella personale: la trovi sulla scrivania, in alto a sinistra. Dentro ci sono "
     "Documenti, Immagini, Musica, Scaricati e Video. Oppure dimmi «apri la home»."),
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
_TIPI = {
    r"(le )?(foto|fotografie|immagini)": ("*.jpg,*.jpeg,*.png,*.heic,*.webp,*.gif", "le foto"),
    r"(i )?(video|filmati)": ("*.mp4,*.mov,*.mkv,*.avi,*.webm", "i video"),
    r"(la )?(musica|canzoni|brani)": ("*.mp3,*.flac,*.wav,*.ogg,*.m4a", "la musica"),
    r"(i )?(documenti|pdf e documenti)": ("*.pdf,*.doc,*.docx,*.odt,*.txt,*.rtf,*.md", "i documenti"),
}


def _ricerca(t: str) -> Intent | None:
    m = re.search(r"^(?:cerca|cercami|trova|trovami|dove (?:si trova|e|sta|trovo|ho messo)|dov'?e)\s+"
                  r"(?:tutti |tutte )?(?:i |il |lo |la |le |gli |l'|un |una |dei |delle |miei |mie )?"
                  r"(?:file |files )?(.+?)\s*\??$", t)
    if not m:
        return None
    resto = m.group(1)
    # «cerca su internet…» e «cerca di…» non sono ricerche di file
    if re.search(r"\b(su internet|su google|sul web|online|in rete)\b", t) or \
            re.match(r"(cerca|cercami|trova|trovami) di ", t):
        return None
    args = {}
    if re.search(r"\b(di oggi|modificat\w* oggi|da oggi|oggi)\b", resto):
        args["oggi"] = True
    g = re.search(r"(?:degli |negli |ultimi |ultime )+(\d{1,3}) giorni", resto)
    if g:
        args["giorni"] = int(g.group(1))
    elif re.search(r"(questa|ultima) settimana|della settimana", resto):
        args["giorni"] = 7
    resto = re.sub(r"\b(modificat\w*|creat\w*|recenti|di oggi|da oggi|oggi|della settimana|questa settimana|"
                   r"ultima settimana|(degli |negli |ultimi |ultime )+\d{1,3} giorni)\b", " ", resto)
    resto = re.sub(r"\s+", " ", resto).strip(" .?!")
    resto = re.sub(r"\s+(di|del|della|dei|delle|da)$", "", resto)     # «le foto di [questa settimana]»
    resto = re.sub(r"^(il |i |la |le )?(documento|documenti|file) (?=\S)", "", resto)   # «il documento fattura»
    if not resto:
        return None
    for schema, (estensioni, nome) in _TIPI.items():
        if re.fullmatch(schema, resto):
            args["pattern"] = estensioni
            return Intent("find_files", args, "Cerco %s." % nome)
    if re.fullmatch(_ESTENSIONI, resto):
        args["pattern"] = "*." + resto
        detto = "i file %s" % resto.upper()
    else:
        args["pattern"] = "*%s*" % resto
        detto = "«%s»" % resto
    return Intent("find_files", args, "Cerco %s." % detto)


def parse(text: str) -> Intent | None:
    t = _norm(text)
    if not t:
        return None

    # --- «come va la rete»: stato reale, non una spiegazione ---
    # Va prima di _sapere(), altrimenti «ho internet?» finisce nella risposta
    # sul browser e «come va la rete» arriva al modello, che non può guardare
    # le interfacce. Si escludono le frasi che chiedono il pannello o come
    # navigare: quelle non sono domande sullo stato.
    if not re.search(r"impostazion|settings|pannello|^apri\b|navig", t) and \
       re.search(r"\b(come va|come sta|stato|funziona|non funziona|controlla|verifica|c ?e)\b"
                 r"[^.?!]{0,24}\b(rete|wifi|wi fi|connessione|internet)\b"
                 r"|\b(rete|wifi|connessione|internet)\b[^.?!]{0,16}(va|funziona|attiva|connessa|caduta)"
                 r"|sono (connesso|collegato|online)|network status|am i (online|connected)", t):
        return Intent("network_status", {}, "Controllo la rete.")

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
    if m and not re.search(r"\b(tutto|tutti|cestino|sistema|disco|programma|app)\b", m.group(1)):
        nome = m.group(1).strip()
        return Intent("trash_file", {"name": nome},
                      "Sposto «%s» nel cestino." % nome)

    # --- finestre aperte ---------------------------------------------------
    if re.search(r"\b(che|quali|quanti)\b[^.?!]{0,24}\b(programmi|applicazioni|finestre|app)\b"
                 r"[^.?!]{0,16}\b(apert\w+|in esecuzione|attiv\w+)\b"
                 r"|\bfinestre aperte\b|\bcosa ho aperto\b", t):
        return Intent("list_windows", {}, "Ecco le finestre aperte.")

    # --- colore d'accento a parole ---------------------------------------
    # L'azione vuole un #RRGGBB: nessuno lo dice a voce. Qui i colori che la
    # gente nomina davvero diventano i toni usati dal sistema.
    m = re.search(r"\b(?:cambia|metti|imposta|usa|voglio)\b[^.?!]{0,24}"
                  r"\b(?:colore|accento|tinta)\b[^.?!]{0,12}\b(%s)\b" % "|".join(_COLORI), t)
    if not m:
        m = re.search(r"\b(?:accento|colore)\s+(%s)\b" % "|".join(_COLORI), t)
    if m:
        nome = m.group(1)
        return Intent("set_accent", {"color": _COLORI[nome]},
                      "Metto l'accento %s." % nome)

    # --- spegnere lo schermo (non il computer) ----------------------------
    if re.search(r"\bspegni\b[^.?!]{0,10}\b(lo )?(schermo|monitor|display)\b"
                 r"|\bschermo\b[^.?!]{0,8}\bspegni\b", t):
        return Intent("screen_off", {}, "Spengo lo schermo.")

    # --- luminosita' ------------------------------------------------------
    m = re.search(r"\b(?:metti|imposta|porta)\b[^.?!]{0,20}luminosit\w*\s*(?:a|al)?\s*(\d{1,3})", t)
    if m:
        return Intent("set_brightness", {"level": max(0, min(100, int(m.group(1))))},
                      "Imposto la luminosità.")
    if re.search(r"\b(alza|aumenta|su)\b[^.?!]{0,16}luminosit\w*|luminosit\w*[^.?!]{0,10}\b(alza|aumenta)\b", t):
        return Intent("set_brightness", {"level": 100}, "Alzo la luminosità.")
    if re.search(r"\b(abbassa|riduci|diminuisci)\b[^.?!]{0,16}luminosit\w*"
                 r"|luminosit\w*[^.?!]{0,10}\b(abbassa|riduci)\b", t):
        return Intent("set_brightness", {"level": 30}, "Abbasso la luminosità.")

    # --- cercare sul web -------------------------------------------------
    # Prima queste frasi venivano escluse dalla ricerca dei file e finivano al
    # modello: significava aspettare il caricamento del modello per aprire una
    # pagina. Ora si apre e basta. Il motore predefinito e' DuckDuckGo, che non
    # traccia chi cerca; se l'utente nomina un motore, si usa quello.
    m = re.search(r"\b(?:cerca|cercami|trova|trovami|guarda|cerchi)\b\s*(?:mi\s+)?(.{2,80}?)"
                  r"\s+(?:su|sul|in|nel)\s+(google|internet|web|duckduckgo|youtube|wikipedia)\b[.?!]?$", t)
    if not m:
        m2 = re.search(r"\b(?:cerca|cercami|trova|trovami)\b\s+(?:su|sul|in|nel)\s+"
                       r"(google|internet|web|duckduckgo|youtube|wikipedia)\b\s+(.{2,80})$", t)
        if m2:
            m = None
            motore, cosa = m2.group(1), m2.group(2)
        else:
            motore = cosa = None
    else:
        cosa, motore = m.group(1), m.group(2)
    if cosa:
        cosa = cosa.strip(" .?!")
        q = _url_quote(cosa)
        motori = {
            "google": "https://www.google.com/search?q=%s",
            "youtube": "https://www.youtube.com/results?search_query=%s",
            "wikipedia": "https://it.wikipedia.org/w/index.php?search=%s",
        }
        url = motori.get(motore, "https://duckduckgo.com/?q=%s") % q
        return Intent("open_url", {"url": url}, "Cerco «%s» sul web." % cosa)

    # --- chiudere la finestra ---
    if re.search(r"chiudi (questa |la )?finestra|close (this )?window|chiudi l'app", t):
        return Intent("close_active_window", {}, "Chiudo la finestra attiva.")

    # --- chiudere un programma per nome: «chiudi firefox» ---
    # Va dopo la finestra attiva, altrimenti «chiudi la finestra» verrebbe
    # letto come «chiudi il programma chiamato la finestra».
    # «spegni» resta fuori di proposito: «spegni il wifi» e «spegni lo schermo»
    # non chiudono un programma, e con quel verbo qui dentro finivano qui.
    m = re.search(r"\b(chiudi|termina|esci da)\s+(?:il |lo |la |l )?(?:programma |app |applicazione )?([a-z0-9 .+-]{2,30})$", t)
    if m and not re.search(r"\b(computer|sistema|schermo|finestra|tutto|sessione"
                           r"|wifi|wi fi|bluetooth|rete|volume|audio|musica|luce"
                           r"|luminosita|schermata|sessione)\b", m.group(2)):
        nome = m.group(2).strip()
        return Intent("close_application", {"app": nome}, "Chiudo %s." % nome)

    # --- schermata ---
    if re.search(r"(fai|scatta|cattura|prendi|salva)[^.?!]{0,14}(schermata|screenshot|foto dello schermo)"
                 r"|^screenshot$|^schermata$", t):
        return Intent("screenshot", {}, "Salvo una schermata.")

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
    if m:
        testo = m.group(1).strip(" .")
        return Intent("search_content", {"text": testo}, "Cerco «%s» dentro i file." % testo)

    # --- rinominare ---
    m = re.search(r"rinomina\s+[\"«]?([^\"»]{1,60}?)[\"»]?\s+(?:in|come)\s+[\"«]?([^\"»]{1,60})[\"»]?$", t)
    if m:
        vecchio, nuovo = m.group(1).strip(), m.group(2).strip(" .")
        return Intent("rename_file", {"name": vecchio, "new_name": nuovo},
                      "Rinomino «%s» in «%s»." % (vecchio, nuovo))

    # --- spostare ---
    m = re.search(r"sposta\s+[\"«]?([^\"»]{1,60}?)[\"»]?\s+(?:in|dentro|nella|nel)\s+[\"«]?([^\"»]{1,40})[\"»]?$", t)
    if m and not re.search(r"cestino", m.group(2)):
        che, dove = m.group(1).strip(), m.group(2).strip(" .")
        return Intent("move_file", {"name": che, "folder": dove},
                      "Sposto «%s» in %s." % (che, dove))

    # --- gestione delle finestre ---
    if re.search(r"\b(minimizza|minimize)\b|(riduci|nascondi).*(finestra|window)", t):
        return Intent("minimize_window", {}, "Riduco a icona la finestra attiva.")
    if re.search(r"\b(massimizza|maximize)\b|(ingrandisci|schermo intero).*(finestra|window)", t):
        return Intent("maximize_window", {}, "Ingrandisco la finestra attiva.")
    # «quante finestre ho aperte», «dimmi le finestre», «che finestre ci sono»:
    # chi parla non usa il verbo che ci aspettavamo, e la frase finiva al
    # modello, che risponde di non poter sapere quali finestre sono aperte.
    if re.search(r"(quante|quali|che|mostra|mostrami|elenca|dimmi|vedere)"
                 r"[^.?!]{0,24}\b(finestre|window)|"
                 r"\bfinestre\b[^.?!]{0,12}(aperte|ridotte|attive)", t):
        return Intent("list_windows", {}, "Ecco le finestre.")

    # --- aprire un sito ---
    if re.search(r"\b(apri|vai su|portami su|mostrami)\b[^.?!]{0,20}"
                 r"(https?://|www\.|\b[a-z0-9-]+\.(it|com|org|net|eu|io|dev)\b)", t):
        m = re.search(r"(https?://\S+|www\.\S+|\b[a-z0-9-]+\.(?:it|com|org|net|eu|io|dev)\b\S*)", t)
        if m:
            return Intent("open_url", {"url": m.group(1)}, "Apro il sito.")

    # --- aprire un file per nome ---
    if re.search(r"\bapri\b[^.?!]{0,30}\b(il |la |lo |l )?(file|documento|immagine|foto|video|pdf)\b", t):
        m = re.search(r"\b(?:file|documento|immagine|foto|video|pdf)\s+(?:chiamat[oa]\s+)?([\w .-]+)", t)
        if m and m.group(1).strip():
            return Intent("open_file", {"name": m.group(1).strip()},
                          "Cerco e apro il file.")

    # --- sfondo della scrivania ---
    if re.search(r"(cambia|cambiami|metti|imposta)[^.?!]{0,20}\b(sfondo|wallpaper)\b", t):
        if re.search(r"(predefinit|originale|di zeta|default)", t):
            return Intent("set_wallpaper", {"name": "predefinito"},
                          "Rimetto lo sfondo di ZETA RAYS.")
        # uno degli sfondi di ZETA RAYS per nome («metti lo sfondo onde rosse»)
        m = re.search(r"\b(?:sfondo|wallpaper)\b\s+(?:con |in |a )?([\w -]+?)\s*[.?!]*$", t)
        if m:
            from system import sfondi
            if sfondi.cerca(m.group(1)):
                return Intent("set_wallpaper", {"name": m.group(1).strip()}, "Cambio lo sfondo.")
        m = re.search(r"\b(?:sfondo|wallpaper)\b[^.?!]{0,10}?\b(?:con|in|a)\s+([\w ./-]+)", t)
        if m and m.group(1).strip():
            return Intent("set_wallpaper", {"name": m.group(1).strip()}, "Cambio lo sfondo.")
        return Intent("open_settings", {"page": "aspetto"},
                      "Apro le Impostazioni per scegliere lo sfondo.")

    # --- tema chiaro / scuro ---
    if re.search(r"tema (chiaro|light)|modalita chiara|passa al chiaro", t):
        return Intent("set_theme", {"tema": "chiaro"}, "Passo al tema chiaro.")
    if re.search(r"tema (scuro|dark)|modalita scura|passa allo scuro", t):
        return Intent("set_theme", {"tema": "scuro"}, "Passo al tema scuro.")

    # --- domande banali: risposte immediate, senza scomodare il modello ---
    if re.search(r"che ore sono|che ora e|dimmi l ?ora|^ora$|what time", t):
        return Intent("current_time", {}, "Sono le…")
    if re.search(r"che giorno e|che data e|^data$|dimmi la data|what day|what.*date", t):
        return Intent("current_date", {}, "Oggi è…")
    if re.search(r"(quanta|stato).*batteria|^batteria$|battery", t):
        return Intent("battery_status", {}, "Controllo la batteria.")
    if re.search(r"(che |quale |quanto )?(volume|audio)[^.?!]{0,16}\b(e|adesso|ora)\b"
                 r"|^volume$|a che volume", t):
        return Intent("volume_status", {}, "Controllo il volume.")
    if re.search(r"a che rete|come mi chiamo in rete|nome del computer|^hostname$", t):
        return Intent("system_info", {}, "Ecco le informazioni di sistema.")

    # --- stato del sistema ---
    if re.search(r"(uso|quanto)[^.?!]*\b(cpu|processore)\b|\bcpu\b[^.?!]*(uso|carico|percentuale)"
                 r"|what.*\bcpu\b", t):
        return Intent("cpu_usage", {}, "Controllo l'uso della CPU.")
    if re.search(r"(quanta|uso|quanto)[^.?!]*\b(ram|memoria)\b|\bmemoria\b[^.?!]*(uso|libera|disponibile)"
                 r"|how much (ram|memory)", t):
        return Intent("memory_usage", {}, "Controllo la memoria.")
    if re.search(r"spazio.*(disco|libero)|(uso|quanto).*disco|disk (usage|space)", t):
        return Intent("disk_usage", {}, "Controllo lo spazio sui dischi.")
    # «ip» senza confini di parola stava dentro «zip», «equipaggio», «principio»:
    # chiedere come si apre un file zip faceva rispondere con l'indirizzo IP.
    if re.search(r"\b(mio |il mio )ip\b|\bindirizzo ip\b|\bip\b.{0,12}\b(pubblico|locale|privato)\b"
                 r"|^ip$|what.*\bmy ip\b", t):
        return Intent("ip_address", {}, "Ecco i tuoi indirizzi IP.")
    if re.search(r"da quanto.*acceso|\buptime\b|tempo di attivita", t):
        return Intent("uptime", {}, "Da quanto è acceso il sistema.")
    if re.search(r"informazioni.*(sistema|zeta)|system info|che sistema", t):
        return Intent("system_info", {}, "Ecco le informazioni di sistema.")
    if re.search(r"process(i|es).*(attivi|in esecuzione|cpu)|cosa (sta |)consuma|what.*using.*cpu|running process", t):
        return Intent("open_system_monitor", {"section": "processes"}, "Apro i processi nel Monitor.")

    # --- monitor di sistema / sicurezza ---
    if re.search(_OPEN + r".*(monitor|monitoraggio)", t):
        return Intent("open_system_monitor", {}, "Apro il Monitor di sistema.")
    if re.search(_OPEN + r".*(sicurezza|security|firewall|strumenti di sicurezza)", t):
        return Intent("open_security", {}, "Apro ZETA RAYS Security.")

    # --- terminale ---
    if re.search(_OPEN + r".*(terminale|terminal|console|shell)", t) or t in ("terminale", "terminal"):
        return Intent("open_terminal", {}, "Apro il terminale.")

    # --- impostazioni (con eventuale pagina) ---
    if re.search(_OPEN + r".*(impostazion|settings|preferenze|configurazione)", t):
        page = _find(_SETTINGS, t)
        return Intent("open_settings", {"page": page} if page else {},
                      "Apro le Impostazioni%s." % (" › " + page if page else ""))
    if re.search(r"(impostazion|settings).*(rete|wifi|audio|bluetooth|sicurezza|ai)", t):
        page = _find(_SETTINGS, t)
        return Intent("open_settings", {"page": page} if page else {}, "Apro le Impostazioni.")

    # --- Wi-Fi (prima dell'energia: «spegni il wifi» non deve spegnere tutto) ---
    if re.search(r"(attiva|accendi)[^.?!]{0,8}(wi.?fi|wireless)", t):
        return Intent("wifi_toggle", {"on": True}, "Accendo il Wi-Fi.")
    if re.search(r"(disattiva|spegni)[^.?!]{0,8}(wi.?fi|wireless)", t):
        return Intent("wifi_toggle", {"on": False}, "Spengo il Wi-Fi.")

    # --- energia ---
    # «spegni» da solo, o riferito al computer. NON «spegni lo schermo», «spegni
    # il wifi», «spegni il bluetooth»: prima bastava la parola «spegni» in
    # qualunque posto, e chiedere di spegnere lo schermo proponeva di spegnere
    # il computer. La conferma evitava il disastro, ma la domanda era sbagliata.
    if re.search(r"^(ora |adesso )?(spegni(ti)?|spegnere|shutdown|power off)( (il|questo) (computer|pc|sistema|tutto))?[.!]?$"
                 r"|\bspegni(re)? (il |questo )?(computer|pc|sistema)\b"
                 r"|\bchiudi (il |questo )?(computer|pc|sistema)\b", t):
        return Intent("power_off", {}, "Spengo il computer.")
    if re.search(r"\briavvia(re)?\b|\breboot\b|riavviare il (computer|sistema)", t):
        return Intent("reboot", {}, "Riavvio il computer.")
    if re.search(r"\bsospendi\b|\bsospensione\b|\bsuspend\b|metti in pausa il computer", t):
        return Intent("suspend", {}, "Sospendo il computer.")
    if re.search(r"blocca( lo)? schermo|\block screen\b|blocca il computer", t):
        return Intent("lock_screen", {}, "Blocco lo schermo.")
    if re.search(r"\besci\b|disconnett|log ?out|chiudi (la )?sessione", t):
        return Intent("log_out", {}, "Chiudo la sessione.")

    # --- volume ---
    m = re.search(r"(?:volume|audio)[^.?!]{0,12}?\b(\d{1,3})\s*%?", t)
    if m and re.search(r"metti|imposta|porta|volume a|al ", t):
        return Intent("set_volume", {"level": int(m.group(1))}, "Imposto il volume.")
    # relativo al volume attuale: prima «alza» portava sempre all'80%
    # (da 95 lo abbassava) e «abbassa» sempre al 30%
    if re.search(r"(alza|aumenta)[^.?!]{0,10}(volume|audio)", t):
        return Intent("set_volume", {"step": "su", "amount": 10}, "Alzo il volume.")
    if re.search(r"(abbassa|riduci)[^.?!]{0,10}(volume|audio)", t):
        return Intent("set_volume", {"step": "giu", "amount": 10}, "Abbasso il volume.")
    if re.search(r"\b(silenzia|muto|mute|zittisci)\b", t):
        return Intent("set_volume", {"mute": True}, "Silenzio l'audio.")

    # --- luminosità ---
    m = re.search(r"luminosit[aà][^.?!]{0,12}?\b(\d{1,3})\s*%?", t)
    if m:
        return Intent("set_brightness", {"level": int(m.group(1))}, "Regolo la luminosità.")

    # --- programmi ---
    m = re.search(r"\binstalla(re)?\b\s+(?:il |lo |la |l )?([a-z0-9.+-]{2,40})", t)
    if m:
        return Intent("install_package", {"name": m.group(2).strip()}, "Installo %s." % m.group(2).strip())
    m = re.search(r"\b(disinstalla(re)?|rimuovi)\b\s+(?:il |lo |la |l )?([a-z0-9.+-]{2,40})", t)
    if m:
        return Intent("remove_package", {"name": m.group(3).strip()}, "Rimuovo %s." % m.group(3).strip())

    # --- nuova cartella ---
    m = re.search(r"(?:crea|nuova)[^.?!]{0,12}cartella\s+(?:chiamata\s+)?([\w .-]{1,40})", t)
    if m and m.group(1).strip():
        return Intent("create_folder", {"name": m.group(1).strip()}, "Creo la cartella.")

    # --- cestinare ---
    m = re.search(r"(?:cestina|butta|sposta nel cestino|elimina)\s+(?:il |lo |la |l )?(?:file\s+)?([\w .-]{1,40})", t)
    if m and m.group(1).strip() not in ("", "cestino"):
        return Intent("trash_file", {"name": m.group(1).strip()}, "Sposto nel cestino.")
    if re.search(r"svuota( il)? cestino", t):
        return Intent("empty_trash", {}, "Svuoto il cestino.")

    # --- cercare file: «cerca fattura», «trova i file pdf di oggi»,
    #     «dove si trova il file prova.txt» ---
    ricerca = _ricerca(t)
    if ricerca:
        return ricerca

    # --- cartelle ---
    folder = _find(_FOLDERS, t)
    if folder and re.search(_OPEN + r"|cartella|folder", t):
        detto = "il cestino" if folder == "cestino" else "la cartella %s" % folder
        return Intent("open_folder", {"name": folder}, "Apro %s." % detto)

    # --- app specifiche ---
    app = _find(_APPS, t)
    if app and re.search(_OPEN, t):
        return Intent("open_application", {"app": app}, "Apro %s." % app)

    # --- "apri <qualcosa>" generico: passa il nome a open_application ---
    m = re.search(_OPEN + r"\s+(?:l'|lo |la |il |le |gli |i |the )?([a-z0-9 .-]{2,30})$", t)
    if m:
        target = m.group(1).strip()
        # evita di intercettare frasi già gestite sopra
        if target and target not in ("finestra", "window"):
            return Intent("open_application", {"app": target}, "Provo ad aprire %s." % target)

    return None
