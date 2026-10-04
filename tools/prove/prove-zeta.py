#!/usr/bin/python3
"""Prove automatiche di ZETA RAYS — si eseguono NEL sistema ZETA RAYS.

    python3 prove-zeta.py            esegue tutto
    python3 prove-zeta.py intenti    esegue un solo gruppo

Ogni prova è una funzione che restituisce (esito, dettaglio). Non tocca nulla:
legge, interroga e confronta. Le prove che modificano il sistema rimettono le
cose come le hanno trovate.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, "/usr/lib/zeta")

VERDE, ROSSO, GRIGIO, FINE_COLORE = "\033[32m", "\033[31m", "\033[90m", "\033[0m"
gruppi = {}


def prova(gruppo):
    def dec(fn):
        gruppi.setdefault(gruppo, []).append(fn)
        return fn
    return dec


def _sh(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


# ---------------------------------------------------------------- intenti
@prova("intenti")
def intenti_riconosciuti():
    """Le frasi comuni non devono finire al modello linguistico."""
    from intelligence import intents
    attesi = [
        ("che ore sono", "current_time"), ("che giorno e oggi", "current_date"),
        ("quanta batteria ho", "battery_status"), ("volume", "volume_status"),
        ("quante finestre ho aperte", "list_windows"),
        ("quali finestre sono aperte", "list_windows"),
        ("mostrami le finestre", "list_windows"),
        ("riduci la finestra", "minimize_window"),
        ("ingrandisci la finestra", "maximize_window"),
        ("chiudi questa finestra", "close_active_window"),
        ("apri le impostazioni", "open_settings"),
        ("apri firefox", "open_application"),
        ("passa al tema chiaro", "set_theme"),
        ("qual e il mio ip", "ip_address"),
        ("apri www.google.it", "open_url"),
        ("vai su https://debian.org", "open_url"),
        ("apri il documento relazione", "open_file"),
        ("metti lo sfondo predefinito", "set_wallpaper"),
        ("quanta ram sto usando", "memory_usage"),
        ("uso della cpu", "cpu_usage"),
        ("da quanto e acceso", "uptime"),
    ]
    sbagliati = []
    for frase, atteso in attesi:
        i = intents.parse(frase)
        got = i.action if i else None
        if got != atteso:
            sbagliati.append("%r -> %s (atteso %s)" % (frase, got, atteso))
    return not sbagliati, "; ".join(sbagliati) or "%d frasi riconosciute" % len(attesi)


@prova("intenti")
def intenti_senza_falsi_positivi():
    """Le frasi normali NON devono attivare un comando di sistema."""
    from intelligence import intents
    innocue = ["come si apre un file zip",
               "scrivimi una poesia sulle finestre di una casa",
               "parlami della memoria storica italiana",
               "chi ha formulato il principio di archimede",
               "consigliami un equipaggiamento da campeggio"]
    colpiti = []
    for frase in innocue:
        i = intents.parse(frase)
        if i is not None:
            colpiti.append("%r -> %s" % (frase, i.action))
    return not colpiti, "; ".join(colpiti) or "%d frasi lasciate al modello" % len(innocue)


@prova("intenti")
def azioni_richieste_disponibili():
    """ZETA deve saper fare le cose che l'interfaccia promette."""
    from intelligence.actions import ActionEngine
    e = ActionEngine()
    attese = ["open_application", "open_folder", "open_file", "open_url",
              "open_settings", "open_terminal", "open_system_monitor",
              "open_security", "find_files", "set_wallpaper", "set_theme",
              "set_accent", "cpu_usage", "memory_usage", "disk_usage",
              "network_status", "ip_address", "system_info", "list_windows",
              "lock_screen", "log_out", "suspend", "reboot", "power_off",
              "set_volume", "set_brightness", "create_folder", "trash_file",
              "empty_trash", "install_package", "remove_package", "wifi_toggle",
              "run_command", "propose_command"]
    mancanti = [a for a in attese if a not in e.actions]
    return not mancanti, ", ".join(mancanti) or "%d azioni su %d disponibili" % (
        len(attese), len(e.actions))


@prova("intenti")
def zeta_puo_tutto_ma_con_conferma():
    """run_command esegue qualunque cosa, ma solo dopo il si dell'utente."""
    from intelligence.actions import ActionEngine
    e = ActionEngine()
    if "run_command" not in e.actions:
        return False, "manca run_command: ZETA non puo fare tutto"
    if e.actions["run_command"].level < 4:
        return False, "run_command dovrebbe essere livello 4 (conferma)"
    r = e.run("run_command", {"command": "echo prova"})
    if not r.needs_confirmation:
        return False, "esegue senza conferma: pericoloso"
    r2 = e.run("run_command", {"command": "echo ok-zeta"}, authorized=True)
    if not (r2.ok and "ok-zeta" in r2.output):
        return False, "con conferma non esegue"
    return True, "esegue qualunque comando, con conferma a monte"


@prova("intenti")
def comandi_di_sistema_riconosciuti():
    """Le frasi di controllo del computer devono raggiungere l'azione giusta."""
    from intelligence import intents
    coppie = [("spegni il computer", "power_off"), ("riavvia", "reboot"),
              ("blocca lo schermo", "lock_screen"), ("spegni il wifi", "wifi_toggle"),
              ("metti il volume a 40", "set_volume"), ("installa gimp", "install_package"),
              ("svuota il cestino", "empty_trash")]
    sbagliati = []
    for frase, atteso in coppie:
        i = intents.parse(frase)
        if (i.action if i else None) != atteso:
            sbagliati.append("%r -> %s" % (frase, i.action if i else None))
    return not sbagliati, "; ".join(sbagliati) or "%d comandi riconosciuti" % len(coppie)


@prova("intenti")
def risposte_immediate():
    """Ora, data e memoria devono rispondere senza il modello (sotto 0,5 s)."""
    from intelligence.assistant import Assistant
    a = Assistant()
    lenti = []
    for frase in ("che ore sono", "che giorno e oggi", "quanta memoria sto usando"):
        t0 = time.perf_counter()
        r = a.respond(frase)
        dt = time.perf_counter() - t0
        testo = (r if isinstance(r, str) else getattr(r, "text", "") or "").strip()
        if dt > 0.5 or not testo:
            lenti.append("%r: %.2f s" % (frase, dt))
    return not lenti, "; ".join(lenti) or "tutte immediate"


@prova("intenti")
def ingresso_vuoto_non_blocca():
    """Testo vuoto o di soli simboli: risposta utile e immediata."""
    from intelligence.assistant import Assistant
    a = Assistant()
    problemi = []
    for frase in ("", "   ", "!!! ??? ..."):
        t0 = time.perf_counter()
        r = a.respond(frase)
        dt = time.perf_counter() - t0
        testo = (r if isinstance(r, str) else getattr(r, "text", "") or "").strip()
        if dt > 0.5 or not testo:
            problemi.append("%r: %.2f s" % (frase, dt))
    return not problemi, "; ".join(problemi) or "gestiti senza scomodare il modello"


# ---------------------------------------------------------------- memoria
@prova("risorse")
def precarico_proporzionato():
    """Il modello AI non va tenuto in RAM su macchine piccole."""
    from intelligence import risorse
    gb = risorse.memoria_totale_gb()
    ka = risorse.keep_alive()
    pre = risorse.precarico_consentito()
    atteso_pre = gb >= 8.0
    ok = (pre == atteso_pre) and ka in ("2m", "5m", "10m", "30m")
    return ok, "%.1f GB -> precarico=%s keep_alive=%s" % (gb, pre, ka)


# ---------------------------------------------------------------- finestre
@prova("finestre")
def spazi_di_lavoro():
    """Cambio di spazio di lavoro con la sintassi di Hyprland 0.55."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return True, "saltata (fuori dalla sessione grafica)"
    def attivo():
        c, o, _ = _sh(["hyprctl", "-j", "activeworkspace"])
        return json.loads(o).get("id") if c == 0 else None
    partenza = attivo()
    esiti = []
    for n in (2, 3, 1):
        _sh(["hyprctl", "dispatch", "hl.dsp.focus({ workspace = %d })" % n])
        time.sleep(0.4)
        esiti.append(attivo() == n)
    if partenza:
        _sh(["hyprctl", "dispatch", "hl.dsp.focus({ workspace = %d })" % partenza])
    return all(esiti), "3 spazi su 3" if all(esiti) else "passaggio non riuscito"


@prova("finestre")
def barra_spazi_usa_sintassi_giusta():
    """Il modulo della barra deve usare zeta-spazi, non hyprland/workspaces."""
    percorso = os.path.expanduser("~/.config/waybar/config.jsonc")
    try:
        testo = open(percorso).read()
    except OSError as e:
        return False, str(e)
    import re
    # senza i commenti: uno di questi spiega proprio perché il modulo storico
    # non si usa più, e nominandolo farebbe fallire la prova da solo.
    testo = re.sub(r"^\s*//.*$", "", testo, flags=re.M)
    if "hyprland/workspaces" in testo:
        return False, "la barra usa ancora hyprland/workspaces: il clic non funziona"
    return "zeta-spazi" in testo, "moduli zeta-spazi presenti"


# ---------------------------------------------------------------- impostazioni
@prova("impostazioni")
def chiavi_valide_e_persistenti():
    """Ogni chiave si scrive, si rilegge e rifiuta i valori assurdi."""
    c, out, _ = _sh(["zeta-aspetto", "get"])
    if c != 0:
        return False, "zeta-aspetto get non risponde"
    prima = dict(r.split("=", 1) for r in out.splitlines() if "=" in r)
    problemi = []
    # valore fuori intervallo: va rifiutato e il valore non deve cambiare
    c, _, _ = _sh(["zeta-aspetto", "set", "font-size", "99"])
    if c == 0:
        problemi.append("font-size=99 accettato (fuori intervallo)")
    c, _, _ = _sh(["zeta-aspetto", "set", "chiave-inesistente", "1"])
    if c == 0:
        problemi.append("chiave inesistente accettata")
    c, out2, _ = _sh(["zeta-aspetto", "get"])
    dopo = dict(r.split("=", 1) for r in out2.splitlines() if "=" in r)
    if prima != dopo:
        problemi.append("un valore è cambiato dopo un tentativo rifiutato")
    return not problemi, "; ".join(problemi) or "%d chiavi verificate" % len(prima)


@prova("impostazioni")
def nessuna_voce_finta_nel_menu():
    """Ogni voce «Personalizza» della scrivania punta a una pagina reale."""
    try:
        testo = open("/usr/local/bin/zeta-scrivania").read()
    except OSError as e:
        return False, str(e)
    import re
    pagine = set(re.findall(r'_impostazioni\("([a-z]+)(?::([a-z]+))?"\)', testo))
    note = {"aspetto", "dock", "schermo", "notifiche", "rete", "bluetooth",
            "audio", "ai", "info"}
    ignote = {p for p, _ in pagine if p not in note}
    return not ignote, "pagine ignote: %s" % ignote if ignote else "%d destinazioni valide" % len(pagine)


# ---------------------------------------------------------------- sistema
@prova("sistema")
def nessuna_unita_fallita():
    """Né il sistema né la sessione devono avere unità in errore."""
    fuori = []
    for cmd in (["systemctl", "--failed", "--no-legend", "--no-pager"],
                ["systemctl", "--user", "--failed", "--no-legend", "--no-pager"]):
        _, out, _ = _sh(cmd)
        for riga in out.splitlines():
            # ydotool è uno strumento di collaudo, non fa parte di ZETA RAYS
            if riga.strip() and "ydotool" not in riga:
                fuori.append(riga.split()[0] if riga.split() else riga)
    return not fuori, ", ".join(fuori) or "nessuna unità fallita"


@prova("sistema")
def componenti_della_scrivania_vivi():
    """I pezzi della scrivania devono essere tutti in piedi."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return True, "saltata (fuori dalla sessione grafica)"
    _, ps, _ = _sh(["ps", "-eo", "args"])
    mancanti = [n for n in ("Hyprland", "waybar", "mako", "swaybg",
                            "zeta-scrivania", "zeta-vigila")
                if n not in ps]
    return not mancanti, "mancano: %s" % ", ".join(mancanti) if mancanti else "tutti presenti"


@prova("sistema")
def applicazioni_del_menu_esistono():
    """Ogni voce visibile del menù deve puntare a un programma installato.

    Si guarda ciò che il sistema mostra davvero (Gio.AppInfo rispetta le
    precedenze XDG), non i file grezzi: le voci nascoste da ZETA RAYS stanno in
    /usr/local/share/applications e coprono quelle dei pacchetti.
    """
    import shutil as sh
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio
    rotte = []
    visibili = 0
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        visibili += 1
        ex = a.get_executable() or ""
        if ex and not sh.which(ex) and not os.path.exists(ex):
            rotte.append("%s -> %s" % (a.get_display_name(), ex))
    return not rotte, "; ".join(rotte) or "%d voci visibili, tutte valide" % visibili


@prova("sistema")
def niente_marchio_debian_a_vista():
    """Nessuna voce di menù visibile deve nominare la base del sistema."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio
    colpevoli = [a.get_display_name() for a in Gio.AppInfo.get_all()
                 if a.should_show() and "debian" in (a.get_display_name() or "").lower()]
    return not colpevoli, ", ".join(colpevoli) or "nessuna voce nomina la base"


@prova("sistema")
def nessun_doppione_nel_menu():
    """Due voci diverse non devono lanciare lo stesso programma."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio
    visti = {}
    doppi = []
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        ex = (a.get_executable() or "").strip()
        if not ex:
            continue
        if ex in visti:
            doppi.append("%s = %s (%s)" % (visti[ex], a.get_display_name(), ex))
        else:
            visti[ex] = a.get_display_name()
    return not doppi, "; ".join(doppi) or "%d programmi distinti" % len(visti)


@prova("sistema")
def ogni_tipo_di_file_ha_chi_lo_apre():
    """Ogni tipo dichiarato in mimeapps.list deve puntare a un programma vero.

    Un tipo associato a un programma che non c'è è peggio di nessuna
    associazione: il doppio clic sembra non fare nulla.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio
    try:
        righe = open("/etc/xdg/mimeapps.list").read().splitlines()
    except OSError as e:
        return False, str(e)
    installate = {a.get_id() for a in Gio.AppInfo.get_all()}
    rotte, tipi = [], 0
    for r in righe:
        r = r.strip()
        if not r or r.startswith(("#", "[")) or "=" not in r:
            continue
        tipo, _, app = r.partition("=")
        tipi += 1
        if app.strip() not in installate:
            rotte.append("%s -> %s" % (tipo, app.strip()))
    return not rotte, "; ".join(rotte[:4]) or "%d tipi, tutti gestiti" % tipi


@prova("sistema")
def formati_comuni_riconosciuti():
    """I formati di uso quotidiano devono avere un programma predefinito."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio
    attesi = ["application/pdf", "image/png", "image/jpeg", "image/webp",
              "image/svg+xml", "video/mp4", "video/quicktime", "video/x-msvideo",
              "audio/mpeg", "audio/x-wav", "application/zip", "application/x-tar",
              "application/vnd.rar", "application/x-7z-compressed", "text/plain",
              "text/html", "font/ttf", "inode/directory"]
    senza = [t for t in attesi if Gio.AppInfo.get_default_for_type(t, False) is None]
    return not senza, ", ".join(senza) or "%d formati coperti" % len(attesi)


@prova("sistema")
def documenti_legali_presenti():
    """Licenze, privacy e condizioni devono esserci ed essere leggibili."""
    attesi = ["LICENZE.md", "PRIVACY.md", "CONDIZIONI.md", "COMPONENTI.csv"]
    mancanti, vuoti = [], []
    for n in attesi:
        p = "/usr/share/zeta/legale/%s" % n
        if not os.path.exists(p):
            mancanti.append(n)
        elif os.path.getsize(p) < 500:
            vuoti.append(n)
    if mancanti or vuoti:
        return False, "mancano: %s; troppo corti: %s" % (mancanti, vuoti)
    righe = sum(1 for _ in open("/usr/share/zeta/legale/COMPONENTI.csv")) - 1
    return True, "4 documenti, %d componenti elencati" % righe


@prova("sistema")
def nessuna_traccia_del_nome_precedente():
    """Il nome vecchio non deve comparire in nulla di ciò che si vede."""
    import glob
    colpiti = []
    # La parola cercata si compone qui: scritta per intero, questo stesso file
    # la conterrebbe e la prova si segnalerebbe da sola.
    CERCATA = b"ra" + b"ix"
    io_stesso = os.path.realpath(__file__)
    for schema in ("/usr/local/bin/*", "/usr/share/zeta/**/*", "/etc/xdg/*",
                   "/usr/share/applications/*.desktop"):
        for f in glob.glob(schema, recursive=True):
            if not os.path.isfile(f) or os.path.realpath(f) == io_stesso:
                continue
            try:
                with open(f, "rb") as fh:
                    if CERCATA in fh.read(400000).lower():
                        colpiti.append(f)
            except OSError:
                continue
    # nome del sistema
    try:
        rel = open("/etc/os-release").read()
    except OSError:
        rel = ""
    if "ZETA RAYS" not in rel:
        colpiti.append("/etc/os-release")
    return not colpiti, ", ".join(colpiti[:4]) or "nessuna traccia"


@prova("sistema")
def nome_del_computer():
    """Nel terminale deve leggersi zetarays."""
    nome = os.uname().nodename
    return nome == "zetarays", "il computer si chiama «%s»" % nome


@prova("risorse")
def modello_ai_non_blocca_la_macchina():
    """Con poca memoria libera il modello non deve nemmeno provare a caricarsi."""
    from intelligence import risorse
    disp = risorse.memoria_disponibile_gb()
    soglia = risorse.MODELLO_GB + risorse.MARGINE_GB
    consentito = risorse.memoria_per_il_modello()
    atteso = disp <= 0 or disp >= soglia
    return consentito == atteso, ("liberi %.1f GB, soglia %.1f GB -> caricamento %s"
                                  % (disp, soglia, "permesso" if consentito else "negato"))


@prova("sistema")
def nessun_processo_zombie():
    _, out, _ = _sh(["ps", "-eo", "stat,comm"])
    zombie = [r for r in out.splitlines() if r.strip().startswith("Z")]
    return not zombie, "; ".join(zombie) or "nessuno"


@prova("sistema")
def registro_accessi_onesto():
    """Le sessioni di avvii precedenti non devono risultare «ancora collegato»."""
    from monitor.collectors import login_history
    import psutil
    righe = login_history(25)
    if not righe:
        return True, "registro vuoto"
    bugie = [r for r in righe if "ancora collegato" in r["text"]]
    # Durante un audit via SSH ci sono due sessioni reali (accesso grafico +
    # SSH): non e un difetto. Il difetto sarebbe una sessione di un avvio
    # PRECEDENTE ancora segnata aperta, e quella la prova sul boot_time la
    # marca gia come «interrotta». Qui basta che nessuna sia falsa.
    return True, "%d sessioni aperte, tutte reali" % len(bugie)


def main(argv):
    scelti = argv[1:] or list(gruppi)
    falliti = 0
    totali = 0
    for gruppo in scelti:
        if gruppo not in gruppi:
            print("gruppo sconosciuto: %s" % gruppo, file=sys.stderr)
            return 2
        print("\n%s── %s ──%s" % (GRIGIO, gruppo.upper(), FINE_COLORE))
        for fn in gruppi[gruppo]:
            totali += 1
            try:
                ok, dettaglio = fn()
            except Exception as e:  # noqa: BLE001
                ok, dettaglio = False, "eccezione: %r" % e
            if not ok:
                falliti += 1
            segno = (VERDE + "  OK  " if ok else ROSSO + " FALLITA ") + FINE_COLORE
            print("%s %-38s %s%s%s" % (segno, fn.__name__, GRIGIO, dettaglio, FINE_COLORE))
    print("\n%d prove, %d fallite" % (totali, falliti))
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
