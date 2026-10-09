# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — stampanti (CUPS).

Si usano gli strumenti standard di CUPS (lpstat, lpinfo, lpadmin, lp).
L'utente e' nel gruppo lpadmin, quindi aggiunge e toglie stampanti senza
password, come in qualsiasi sistema desktop.

Il computer non distingue una stampante in Wi-Fi da una via cavo: sono
entrambe «in rete» e si trovano allo stesso modo (DNS-SD/mDNS, cioe' il
Bonjour delle stampanti, e SNMP per le stampanti di rete piu' vecchie).
Prima si prova sempre la stampa senza driver (IPP Everywhere, la fanno
tutte le stampanti dal 2013 in poi, anche USB grazie a ipp-usb); solo se
la stampante non la supporta si cerca il driver adatto.
"""
import os
import re
import socket
import subprocess

from i18n import tr

LPADMIN = "/usr/sbin/lpadmin"
LPINFO = "/usr/sbin/lpinfo"
PAGINA_DI_PROVA = "/usr/share/cups/data/default-testpage.pdf"
_ENV = dict(os.environ, LANG="C", LC_ALL="C", LANGUAGE="C")


def _cmd(argv, timeout=20):
    """(codice, stdout, stderr) senza mai sollevare eccezioni."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=_ENV, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", tr("the printer did not respond in time")
    except OSError as e:
        return 127, "", e.strerror or str(e)


def gestibili():
    """Vero se questo utente puo' aggiungere stampanti (gruppo lpadmin)."""
    try:
        import grp
        gid = grp.getgrnam("lpadmin").gr_gid
    except (KeyError, ImportError):
        return False
    return os.geteuid() == 0 or gid in os.getgroups()


def servizio_attivo():
    rc, out, _ = _cmd(["lpstat", "-r"], 5)
    return rc == 0 and "not running" not in out


# ------------------------------------------------------------- elenco
def elenco():
    """Stampanti configurate: [{nome, descrizione, uri, stato, predefinita,
    lavori, collegamento}]."""
    _rc, out_v, _ = _cmd(["lpstat", "-v"], 8)
    uri = {}
    for r in out_v.splitlines():
        m = re.match(r"device for (\S+): (.+)$", r.strip())
        if m:
            uri[m.group(1)] = m.group(2).strip()
    if not uri:
        return []
    _rc, out_d, _ = _cmd(["lpstat", "-d"], 5)
    m = re.search(r"system default destination: (\S+)", out_d)
    predef = m.group(1) if m else None
    _rc, out_p, _ = _cmd(["lpstat", "-l", "-p"], 8)
    stato, descr = {}, {}
    attuale = None
    for r in out_p.splitlines():
        m = re.match(r"printer (\S+) (.*)", r)
        if m:
            attuale = m.group(1)
            t = m.group(2)
            if "disabled" in t:
                stato[attuale] = "ferma"
            elif "now printing" in t:
                stato[attuale] = "stampa"
            else:
                stato[attuale] = "pronta"
            continue
        m = re.match(r"\s+Description: (.*)", r)
        if m and attuale:
            descr[attuale] = m.group(1).strip()
    _rc, out_o, _ = _cmd(["lpstat", "-o"], 8)
    lavori = {}
    for r in out_o.splitlines():
        m = re.match(r"(\S+)-\d+\s", r)
        if m:
            lavori[m.group(1)] = lavori.get(m.group(1), 0) + 1
    res = []
    for nome, u in uri.items():
        res.append({
            "nome": nome,
            "descrizione": (descr.get(nome) or nome).replace("_", " ").strip(),
            "uri": u,
            "stato": stato.get(nome, "pronta"),
            "predefinita": nome == predef,
            "lavori": lavori.get(nome, 0),
            "collegamento": collegamento(u),
        })
    res.sort(key=lambda s: (not s["predefinita"], s["descrizione"].lower()))
    return res


def collegamento(uri):
    u = uri.lower()
    # ipp-usb pubblica le stampanti USB come stampanti di rete del computer
    # stesso, sulle porte da 60000 in su
    if u.startswith("usb:") or "localhost" in u or "127.0.0.1" in u or \
            "ipp-usb" in u or re.search(r":6\d{4}/", u):
        return "USB"
    if u.startswith(("cups-pdf:", "file:")):
        return tr("On this computer")
    return tr("Network (Wi-Fi or cable)")


# ------------------------------------------------------------- ricerca
def cerca(secondi=8):
    """Stampanti collegate o in rete non ancora aggiunte.

    [{uri, nome, modello, device_id, collegamento}]. Una stampante di rete
    si annuncia piu' volte (IPP, IPPS, porta 9100...): ne resta una sola,
    preferendo l'annuncio che permette la stampa senza driver."""
    rc, out, _ = _cmd([LPINFO, "-l", "-v", "--timeout", str(secondi),
                       "--include-schemes", "dnssd,usb,snmp"], secondi + 15)
    trovate, voce = [], None
    for r in out.splitlines():
        m = re.match(r"Device: uri = (.+)$", r.strip())
        if m:
            voce = {"uri": m.group(1).strip()}
            trovate.append(voce)
            continue
        m = re.match(r"\s*(class|info|make-and-model|device-id|location) = (.*)$", r)
        if m and voce is not None:
            voce[m.group(1)] = m.group(2).strip()
    # cups-browsed crea da solo una coda per ogni stampante IPP in rete
    # (indirizzo implicitclass://): quella e' gia' pronta, non va riproposta
    configurate = elenco()
    gia = {s["uri"] for s in configurate}
    gia_nomi = {_chiave(s["descrizione"]) for s in configurate} | \
        {_chiave(s["nome"]) for s in configurate}
    scelte = {}
    for v in trovate:
        u = v["uri"]
        # usb:// senza stampante (solo lo schema), backend senza risultati
        if u in ("usb", "dnssd", "snmp") or "://" not in u:
            continue
        nome = (v.get("info") or v.get("make-and-model") or u).strip()
        if not nome or nome.lower() in ("unknown", "unknown unknown"):
            nome = u
        nome = _nome_pulito(nome)
        modello = v.get("make-and-model", "")
        if modello.lower() in ("unknown", ""):
            modello = ""
        modello = _nome_pulito(modello) if modello else ""
        chiave = re.sub(r"[^a-z0-9]", "", (modello or nome).lower())[:40] or u
        punti = 3 if u.startswith("dnssd:") else (2 if u.startswith("usb:") else 1)
        if u in gia or _chiave(nome) in gia_nomi or (modello and _chiave(modello) in gia_nomi):
            continue
        att = scelte.get(chiave)
        if att is None or punti > att["_punti"]:
            scelte[chiave] = {"uri": u, "nome": nome, "modello": modello,
                              "device_id": v.get("device-id", ""),
                              "collegamento": collegamento(u),
                              "_punti": punti}
    res = []
    for s in scelte.values():
        s.pop("_punti", None)
        res.append(s)
    res.sort(key=lambda s: s["nome"].lower())
    return res


def _chiave(testo):
    return re.sub(r"[^a-z0-9]", "", (testo or "").lower())


def assicura_predefinita():
    """Se ci sono stampanti ma nessuna e' la predefinita, lo diventa la
    prima: i programmi stampano subito senza chiedere dove."""
    if not gestibili():
        return
    lista = elenco()
    if lista and not any(s["predefinita"] for s in lista):
        _cmd([LPADMIN, "-d", lista[0]["nome"]], 10)


def _nome_pulito(nome):
    """«Canon Canon PIXMA (driverless)» -> «Canon PIXMA»."""
    nome = re.sub(r"\s*\((driverless|IPP Everywhere|IPP-USB)\)\s*$", "", nome, flags=re.I)
    parole = nome.split()
    if len(parole) > 1 and parole[0].lower() == parole[1].lower():
        parole = parole[1:]
    return " ".join(parole) or nome


# ------------------------------------------------------------- aggiunta
def _nome_coda(testo):
    """Nome valido per CUPS (lettere, cifre, _), unico tra le stampanti."""
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", testo).strip("_")[:60] or "Stampante"
    esistenti = {s["nome"] for s in elenco()}
    nome, n = base, 2
    while nome in esistenti:
        nome, n = "%s_%d" % (base, n), n + 1
    return nome


def _marca(device_id, modello):
    m = re.search(r"(?:MFG|MANUFACTURER):([^;]+)", device_id or "")
    marca = (m.group(1) if m else (modello or "").split(" ")[0]).strip().lower()
    return {"hewlett-packard": "hp"}.get(marca, marca)


def _driver_per(device_id, modello):
    """Il driver che CUPS ritiene migliore per questa stampante, o None.
    Si accetta solo un driver della stessa marca: lpinfo, se non trova il
    modello, propone comunque il primo driver dell'elenco."""
    marca = _marca(device_id, modello)
    if not marca:
        return None
    for opz, val in (("--device-id", device_id), ("--make-and-model", modello)):
        if not val:
            continue
        _rc, out, _ = _cmd([LPINFO, "-m", opz, val], 30)
        for r in out.splitlines():
            ppd, _sp, descr = r.partition(" ")
            if not ppd or ppd in ("everywhere", "raw") or "pwgrast" in ppd:
                continue
            d = descr.lower().replace("hewlett-packard", "hp")
            if d.startswith(marca) or (" " + marca + " ") in (" " + d):
                return ppd, descr or ppd
    return None


def _prima_stampante():
    _rc, out, _ = _cmd(["lpstat", "-d"], 5)
    return "system default destination:" not in out


def aggiungi(uri, nome_visibile, device_id="", modello=""):
    """Aggiunge la stampante. (ok, messaggio)."""
    if not gestibili():
        return False, tr("This user cannot add printers: membership in the lpadmin group is required.")
    coda = _nome_coda(nome_visibile)
    descr = nome_visibile[:120]
    era_prima = _prima_stampante()
    rc, _o, err = _cmd([LPADMIN, "-p", coda, "-E", "-v", uri, "-m", "everywhere",
                        "-D", descr], 60)
    modo = tr("driverless")
    if rc != 0:
        _cmd([LPADMIN, "-x", coda], 10)     # lpadmin lascia la coda a meta'
        driver = _driver_per(device_id, modello)
        if driver is None:
            return False, tr("The printer does not support driverless printing and no suitable driver "
                             "is installed ({error}).").format(error=err or tr("no details"))
        rc, _o, err = _cmd([LPADMIN, "-p", coda, "-E", "-v", uri, "-m", driver[0],
                            "-D", descr], 60)
        modo = tr("driver {name}").format(name=driver[1])
        if rc != 0:
            _cmd([LPADMIN, "-x", coda], 10)
            return False, tr("Could not add the printer: {error}").format(error=err or rc)
    if era_prima:
        _cmd([LPADMIN, "-d", coda], 10)
    _cmd([LPADMIN, "-p", coda, "-o", "printer-error-policy=retry-job"], 10)
    return True, tr("“{name}” added ({method}).").format(name=descr, method=modo)


_HOST_VALIDO = re.compile(r"^[A-Za-z0-9.\-]+(:\d{2,5})?$|^\[?[0-9A-Fa-f:]+\]?$")


def aggiungi_indirizzo(host):
    """Aggiunge una stampante di rete dal suo indirizzo IP o nome.

    Serve quando la ricerca automatica non la vede (rete dell'ufficio con
    l'annuncio mDNS bloccato, stampante su un'altra sottorete)."""
    host = (host or "").strip()
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0]
    if not host or not _HOST_VALIDO.match(host):
        return False, tr("Enter the printer's address, for example 192.168.1.50.")
    porta = None
    m = re.match(r"^([A-Za-z0-9.\-]+):(\d{2,5})$", host)   # 192.168.1.50:8631
    if m:
        host, porta = m.group(1), int(m.group(2))
    elif ":" in host and not host.startswith("["):
        host = "[%s]" % host        # IPv6 negli URI va tra parentesi
    nudo = host.strip("[]")
    if porta:
        if not _porta_aperta(nudo, porta):
            return False, tr("No printer responds at {address}:{port}.").format(address=nudo, port=porta)
        for uri in ("ipp://%s:%d/ipp/print" % (host, porta), "ipp://%s:%d/" % (host, porta)):
            ok, msg = _prova_everywhere(uri, nudo)
            if ok:
                return ok, msg
        return False, tr("Something is listening on port {port}, but it is not an IPP printer.").format(port=porta)
    porte = {p: _porta_aperta(nudo, p) for p in (631, 443, 9100)}
    if not any(porte.values()):
        return False, tr("No printer responds at {address}. Check that it is turned on and on the "
                         "same network (Wi-Fi or cable).").format(address=nudo)
    if porte[631] or porte[443]:
        for uri in ("ipp://%s/ipp/print" % host, "ipps://%s/ipp/print" % host,
                    "ipp://%s/ipp" % host, "ipp://%s/" % host):
            ok, msg = _prova_everywhere(uri, nudo)
            if ok:
                return ok, msg
    era_prima = _prima_stampante()
    if porte[9100]:
        # Stampante di rete senza IPP: porta 9100 e driver generico PCL,
        # che quasi tutte le laser capiscono.
        coda = _nome_coda("Stampante_" + nudo)
        rc, _o, err = _cmd([LPADMIN, "-p", coda, "-E", "-v", "socket://%s:9100" % host,
                            "-m", "drv:///sample.drv/generpcl.ppd",
                            "-D", tr("Printer {address}").format(address=nudo)], 30)
        if rc != 0:
            rc, _o, err = _cmd([LPADMIN, "-p", coda, "-E", "-v", "socket://%s:9100" % host,
                                "-m", "gutenprint.5.3://pcl-g_5e/expert",
                                "-D", tr("Printer {address}").format(address=nudo)], 30)
        if rc == 0:
            if era_prima:
                _cmd([LPADMIN, "-d", coda], 10)
            return True, tr("Printer {address} added with the generic PCL driver.").format(address=nudo)
        _cmd([LPADMIN, "-x", coda], 10)
        return False, tr("Could not add the printer: {error}").format(error=err)
    return False, tr("Printer {address} responds but does not accept network printing.").format(address=nudo)


def _prova_everywhere(uri, nudo):
    era_prima = _prima_stampante()
    coda = _nome_coda("Stampante_" + nudo)
    rc, _o, _err = _cmd([LPADMIN, "-p", coda, "-E", "-v", uri, "-m", "everywhere"], 45)
    if rc != 0:
        _cmd([LPADMIN, "-x", coda], 10)
        return False, ""
    # il nome vero della stampante, letto da lei
    _rc, out, _ = _cmd(["lpoptions", "-p", coda], 8)
    m = re.search(r"printer-make-and-model='([^']+)'", out) or \
        re.search(r"printer-make-and-model=(\S+)", out)
    descr = re.sub(r"\s*-\s*IPP Everywhere.*$", "", m.group(1)) if m else ""
    if descr.lower() in ("", "printer", "unknown"):
        descr = tr("Printer {address}").format(address=nudo)
    _cmd([LPADMIN, "-p", coda, "-D", descr, "-o", "printer-error-policy=retry-job"], 10)
    if era_prima:
        _cmd([LPADMIN, "-d", coda], 10)
    return True, tr("“{name}” added (driverless).").format(name=descr)


def _porta_aperta(host, porta, attesa=2.5):
    try:
        with socket.create_connection((host, porta), timeout=attesa):
            return True
    except OSError:
        return False


# ------------------------------------------------------------- azioni
def rimuovi(nome):
    rc, _o, err = _cmd([LPADMIN, "-x", nome], 15)
    return rc == 0, err


def imposta_predefinita(nome):
    rc, _o, err = _cmd([LPADMIN, "-d", nome], 10)
    return rc == 0, err


def pagina_di_prova(nome):
    prova = PAGINA_DI_PROVA if os.path.exists(PAGINA_DI_PROVA) else "/usr/share/cups/data/testprint"
    rc, _o, err = _cmd(["lp", "-d", nome, "-t", tr("ZETA RAYS test page"), prova], 20)
    return rc == 0, err


def riprendi(nome):
    """Rimette in funzione una stampante fermata da un errore."""
    rc1, _o, e1 = _cmd(["cupsenable", nome], 10)
    rc2, _o, e2 = _cmd(["cupsaccept", nome], 10)
    return rc1 == 0 and rc2 == 0, e1 or e2


def annulla_lavori(nome):
    rc, _o, err = _cmd(["cancel", "-a", nome], 10)
    return rc == 0, err
