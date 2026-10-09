# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — rete (NetworkManager via nmcli): stato, Wi-Fi, VPN, proxy."""
import os
import re

from i18n import tr

from . import run

VPN_TYPES = ("vpn", "wireguard")

# nmcli traduce stati e messaggi nella lingua del sistema («connesso»,
# «abilitato»): quando se ne legge l'uscita si usa sempre l'inglese. C.UTF-8
# e non C, cosi' i nomi delle reti con lettere accentate restano intatti.
NMCLI = ["env", "LC_ALL=C.UTF-8", "LANGUAGE=C", "nmcli"]


def _split(line):
    """Divide una riga di `nmcli -t` rispettando i ':' preceduti da '\\'."""
    parts, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _rows(args, timeout=8):
    out = run(NMCLI + ["-t"] + args, timeout=timeout)
    return [_split(l) for l in (out or "").splitlines() if l.strip()]


def nice_name(conn, typ):
    """Nome da mostrare: i nomi automatici di NetworkManager diventano leggibili."""
    m = re.match(r"^(Wired connection|Connessione via cavo)\s*(\d+)$", conn or "")
    if m:
        if m.group(2) == "1":
            return tr("Wired connection")
        return tr("Wired connection {n}").format(n=m.group(2))
    return conn


def status():
    """Connessione principale: {kind, name, label, device, ip, connected}."""
    info = {"kind": "none", "name": "", "label": "", "device": "", "ip": "", "connected": False}
    for dev, typ, state, conn in _rows(["-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]):
        if state == "connected" and typ in ("ethernet", "wifi"):
            info.update(kind=typ, name=conn, device=dev, connected=True,
                        label=nice_name(conn, typ))
            break
    if info["device"]:
        for row in _rows(["-f", "IP4.ADDRESS", "device", "show", info["device"]]):
            if len(row) > 1 and row[1]:
                info["ip"] = row[1].split("/")[0]
                break
    return info


def connectivity():
    """Stato di Internet secondo NetworkManager: full, limited, portal, none, unknown.

    Senza --check: legge l'ultimo controllo di NetworkManager, non aspetta la rete.
    """
    stato = (run(NMCLI + ["-t", "networking", "connectivity"]) or "").strip()
    return stato if stato in ("full", "limited", "portal", "none") else "unknown"


def wifi_enabled():
    return (run(NMCLI + ["-t", "radio", "wifi"]) or "").strip() == "enabled"


def has_wifi():
    return any(typ == "wifi" for _d, typ, *_ in _rows(["-f", "DEVICE,TYPE", "device"]))


def set_wifi(on):
    run(NMCLI + ["radio", "wifi", "on" if on else "off"])


def wifi_networks(rescan=False):
    """Reti Wi-Fi visibili, la più forte per nome: [{ssid, signal, secure, active}]."""
    args = ["-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
            "--rescan", "yes" if rescan else "auto"]
    best = {}
    for row in _rows(args, timeout=15):
        if len(row) < 4 or not row[1]:
            continue
        inuse, ssid, signal, sec = row[0], row[1], row[2], row[3]
        try:
            signal = int(signal)
        except ValueError:
            signal = 0
        net = {"ssid": ssid, "signal": signal, "secure": bool(sec and sec != "--"),
               "active": inuse.strip() == "*"}
        if ssid not in best or net["active"] or signal > best[ssid]["signal"]:
            best[ssid] = net
    return sorted(best.values(), key=lambda n: (not n["active"], -n["signal"]))


def known_connection(ssid):
    for name, typ in _rows(["-f", "NAME,TYPE", "connection", "show"]):
        if typ == "802-11-wireless" and name == ssid:
            return True
    return False


def _nmcli(args, input_=None, timeout=45):
    """nmcli in inglese (i messaggi si riconoscono, vedi _motivo) e con un
    limite di attesa: senza --wait una rete che non risponde teneva
    l'interfaccia su «Connessione…» per un minuto e mezzo."""
    import os
    import subprocess
    attesa = ["--wait", str(max(5, timeout - 10))]
    try:
        r = subprocess.run(["nmcli"] + attesa + args, input=input_, capture_output=True, text=True,
                           timeout=timeout, env=dict(os.environ, LC_ALL="C.UTF-8", LANGUAGE="C"))
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def known_wifi():
    """I nomi delle reti Wi-Fi salvate (una chiamata sola)."""
    return {name for name, typ in _rows(["-f", "NAME,TYPE", "connection", "show"])
            if typ == "802-11-wireless"}


def _motivo(testo):
    t = testo.lower()
    if ("secrets were required" in t or "psk: property is invalid" in t or "no secrets" in t
            or "802-1x" in t or "wrong password" in t or "(7)" in t):
        return "password"
    if "no network with ssid" in t or "not found" in t and "ssid" in t:
        return "non trovata"
    if "timeout" in t or "timed out" in t:
        return "tempo"
    return "altro"


def _wifi_dev():
    for dev, typ in _rows(["-f", "DEVICE,TYPE", "device"]):
        if typ == "wifi":
            return dev
    return None


# Che cosa scrive nmcli --ask (provato con NetworkManager 1.52 e punti di
# accesso simulati, 1 ottobre):
#  - la riga «Password (802-11-wireless-security.psk):» compare due volte
#    ANCHE quando va tutto bene: nmcli la ristampa dopo «successfully
#    activated» e quando scade il tempo. Contarla faceva dire «password
#    sbagliata» a una connessione riuscita, e il profilo appena collegato
#    veniva cancellato: con la password giusta non ci si collegava mai.
#  - il rifiuto vero e' NetworkManager che CHIEDE DI NUOVO la password:
#    l'intestazione qui sotto ricompare (ogni ~4 s finche' non si rinuncia).
_RICHIESTA = "passwords or encryption keys are required"
_RIUSCITA = "successfully activated"


def _leggi_uscita(testo):
    """«riuscita», «rifiutata» (NetworkManager ha richiesto la password) o None."""
    t = (testo or "").lower()
    if _RIUSCITA in t:
        return "riuscita"
    if t.count(_RICHIESTA) >= 2:
        return "rifiutata"
    return None


def _attiva(args, password, limite=40):
    """Esegue nmcli leggendo cio' che scrive mentre lavora. Con --ask nmcli
    chiede la password una volta (e la riceve dall'ingresso: non compare
    nell'elenco dei processi). Se NetworkManager la richiede una seconda
    volta l'ha rifiutata: ci si ferma subito invece di aspettare il limite
    di tempo (prima l'errore arrivava dopo 40 s, o diventava «non risponde»)."""
    import os
    import subprocess
    import threading
    import time
    cmd = ["nmcli", "--wait", str(limite)] + args
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, env=dict(os.environ, LC_ALL="C.UTF-8", LANGUAGE="C"))
    except OSError as e:
        return 1, str(e), None
    try:
        p.stdin.write((password or "") + "\n")
        p.stdin.close()
    except OSError:
        pass
    righe = []

    def leggi():
        # nmcli scrive la domanda senza andare a capo: si legge a pezzi
        while True:
            pezzo = p.stdout.read(1) if p.stdout else ""
            if not pezzo:
                break
            righe.append(pezzo)
    t = threading.Thread(target=leggi, daemon=True)
    t.start()
    fine = time.monotonic() + limite + 5
    rifiutata = False
    while p.poll() is None and time.monotonic() < fine:
        time.sleep(0.2)
        stato = _leggi_uscita("".join(righe))
        if stato == "riuscita":
            break                                    # nmcli sta finendo da solo
        if stato == "rifiutata":
            rifiutata = True
            break
    try:
        p.wait(timeout=3)                            # se ha finito da solo, il suo esito vale
    except subprocess.SubprocessError:
        pass
    ucciso = p.poll() is None
    if ucciso:
        p.kill()
        try:
            p.wait(timeout=5)
        except subprocess.SubprocessError:
            pass
    t.join(timeout=2)
    out = "".join(righe).strip()
    if _leggi_uscita(out) == "riuscita":
        return 0, out, None
    if rifiutata or _leggi_uscita(out) == "rifiutata":
        return 1, out, "password"
    if ucciso:
        return 1, out, "tempo"
    return p.returncode, out, None


def _attendi_rete(ssid, entro=15):
    """La rete si vede? Subito dopo aver acceso il Wi-Fi (o ricaricato la
    scheda) l'elenco e' vuoto per qualche secondo, e NetworkManager accetta
    una nuova scansione solo ogni tanto: si riguarda per un massimo di 15 s
    invece di rispondere «non la vedo» al terzo tentativo (provato: 6 s non
    bastavano dopo aver ricaricato la scheda)."""
    import time
    fine = time.monotonic() + entro
    primo = True
    while True:
        _rc, out = _nmcli(["-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "auto" if primo else "yes"],
                          timeout=20)
        if ssid in {riga.replace("\\:", ":") for riga in out.splitlines()}:
            return True
        primo = False
        if time.monotonic() >= fine:
            return False
        time.sleep(2)


def _chiave_rifiutata(dal):
    """True se wpa_supplicant ha scritto che la chiave e' sbagliata (WRONG_KEY)
    dal momento indicato; False se non l'ha scritto; None se il registro non
    si puo' leggere (utente fuori dal gruppo adm, per esempio dal vivo).

    Serve perche' NetworkManager, al primo collegamento, richiede la password
    per QUALUNQUE accesso non riuscito: password sbagliata, ma anche segnale
    debole o router che non risponde (provato: punto di accesso spento, stessa
    richiesta). Solo WRONG_KEY dice davvero che la password e' sbagliata."""
    import subprocess
    try:
        r = subprocess.run(["journalctl", "-q", "--no-pager", "-o", "cat", "-u", "wpa_supplicant",
                            "--since", "@%d" % int(dal)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return "reason=WRONG_KEY" in r.stdout


def connect_wifi_esito(ssid, password=None, nascosta=False):
    """(ok, messaggio, motivo) — motivo: None, «password», «non trovata», «tempo», «altro».

    Il problema che risolve: dopo una password sbagliata NetworkManager teneva
    la rete salvata CON la password sbagliata; da li' in poi l'interfaccia la
    considerava «conosciuta», non chiedeva piu' la password e riprovava sempre
    quella sbagliata. Ora:
      - una password nuova sostituisce sempre quella salvata;
      - se l'accesso fallisce, il profilo si toglie, cosi' il tentativo dopo
        chiede di nuovo la password (motivo «password»: l'interfaccia la
        richiede subito, senza far ripartire da capo);
      - «password sbagliata» si dice solo se wpa_supplicant lo conferma;
      - la password arriva a nmcli dall'ingresso (--ask), non dalla riga di
        comando: non compare nell'elenco dei processi;
      - le reti nascoste si collegano per nome, con un profilo «hidden».
    """
    import time
    conosciuta = known_connection(ssid)
    dev = _wifi_dev()
    if not dev:
        return False, tr("This computer has no Wi-Fi adapter."), "altro"
    if not nascosta and not _attendi_rete(ssid):
        return False, tr("The network “{name}” is not in range").format(name=ssid), "non trovata"
    inizio = time.time()
    if nascosta:
        # non compare nelle scansioni, quindi «device wifi connect» non la
        # trova nemmeno con «hidden yes» (provato): si crea il profilo e lo si
        # attiva; NetworkManager la cerca per nome. Con «wpa-psk» wpa_supplicant
        # accetta anche WPA3 (gli passa WPA-PSK e SAE insieme).
        if conosciuta:
            _nmcli(["connection", "delete", "id", ssid], timeout=15)
        sic = ["wifi-sec.key-mgmt", "wpa-psk"] if password else []
        rc, out = _nmcli(["connection", "add", "type", "wifi", "ifname", dev, "con-name", ssid,
                          "ssid", ssid, "802-11-wireless.hidden", "yes"] + sic, timeout=15)
        if rc != 0:
            return False, tr("Could not create the profile for “{name}”: {error}").format(
                name=ssid, error=out[-120:]), "altro"
        conosciuta = False
        rc, out, motivo = _attiva(["--ask", "connection", "up", "id", ssid], password)
    elif password:
        if conosciuta:
            _nmcli(["connection", "delete", "id", ssid], timeout=15)
        rc, out, motivo = _attiva(["--ask", "device", "wifi", "connect", ssid, "ifname", dev], password)
    elif conosciuta:
        rc, out, motivo = _attiva(["connection", "up", "id", ssid], None)
    else:
        # rete aperta, oppure protetta senza password: con --ask nmcli la
        # chiede, e la risposta vuota la fa fallire subito
        rc, out, motivo = _attiva(["--ask", "device", "wifi", "connect", ssid, "ifname", dev], None)
    if rc == 0 and "error" not in out.lower():
        return True, tr("Connected to {name}").format(name=ssid), None
    motivo = motivo or _motivo(out)
    if motivo == "altro" and "802-11-wireless-security" in out:
        motivo = "password"                  # protetta e senza password
    if nascosta and motivo == "non trovata":
        motivo = "tempo"                     # nascosta: «non trovata» vuol dire che non ha risposto
    if motivo == "password" and known_connection(ssid):
        _nmcli(["connection", "delete", "id", ssid], timeout=15)
    elif not conosciuta and motivo != "tempo" and known_connection(ssid):
        _nmcli(["connection", "delete", "id", ssid], timeout=15)    # niente profili a meta'
    if motivo == "password" and ("property is invalid" in out.lower() or (password and len(password) < 8)):
        return False, tr("Invalid password for “{name}”: WPA networks need at least 8 characters.").format(
            name=ssid), motivo
    if motivo == "password" and not password:
        if conosciuta:
            return False, tr("The saved password for “{name}” no longer works: enter the current one.").format(
                name=ssid), motivo
        return False, tr("“{name}” is secured: a password is required.").format(name=ssid), motivo
    if motivo == "password" and _chiave_rifiutata(inizio) is False:
        # NetworkManager ha richiesto la password, ma la chiave non e' stata
        # rifiutata: l'accesso non e' riuscito per un altro motivo
        return False, tr("Could not join “{name}”. Check the password; if it is correct, the signal "
                         "is weak or the router did not respond: move closer and try again.").format(
                             name=ssid), motivo
    ultima = out.splitlines()[-1][:120] if out else tr("unknown error")
    if motivo == "password":
        msg = tr("Wrong password for “{name}”. Try again.").format(name=ssid)
    elif motivo == "non trovata":
        msg = tr("The network “{name}” is not in range").format(name=ssid)
    elif motivo == "tempo":
        msg = tr("“{name}” did not respond in time: move closer to the router and try again").format(name=ssid)
    else:
        msg = tr("Connection failed: {error}").format(error=ultima)
    return False, msg, motivo


def connect_wifi(ssid, password=None):
    """(ok, messaggio) — vedi connect_wifi_esito."""
    ok, msg, _m = connect_wifi_esito(ssid, password)
    return ok, msg


def forget_wifi(ssid):
    """Dimentica una rete salvata (con la sua password)."""
    rc, _out = _nmcli(["connection", "delete", "id", ssid], timeout=15)
    return rc == 0


def disconnect(device):
    run(NMCLI + ["device", "disconnect", device], timeout=15)


def vpns():
    """Connessioni VPN configurate: [{name, uuid, type, active}]."""
    active = {row[0] for row in _rows(["-f", "UUID", "connection", "show", "--active"])}
    rows = []
    for name, uuid, typ in _rows(["-f", "NAME,UUID,TYPE", "connection", "show"]):
        if typ in VPN_TYPES:
            rows.append({"name": name, "uuid": uuid,
                         "type": "WireGuard" if typ == "wireguard" else "VPN",
                         "active": uuid in active})
    return rows


def set_vpn(uuid, on):
    out = run(["nmcli", "connection", "up" if on else "down", "uuid", uuid], timeout=40, check=True)
    return out is not None


def import_vpn(path):
    """Importa un file .conf (WireGuard) o .ovpn (OpenVPN). (ok, messaggio)."""
    kind = "wireguard" if path.lower().endswith(".conf") else "openvpn"
    out = run(["nmcli", "connection", "import", "type", kind, "file", path], timeout=20, check=True)
    if out is None:
        return False, tr("Import failed (invalid file?)")
    return True, tr("VPN imported")


def remove_connection(uuid):
    return run(["nmcli", "connection", "delete", "uuid", uuid], timeout=15, check=True) is not None


# ---------------- proxy ----------------
# Il proxy di sistema è quello del desktop (org.gnome.system.proxy), letto da
# Firefox e dalle app GTK; lo stesso valore va nelle variabili d'ambiente
# (~/.config/environment.d/zeta-proxy.conf) per i programmi da terminale.
ENV_FILE = os.path.expanduser("~/.config/environment.d/zeta-proxy.conf")


def _gs(*args):
    return (run(["gsettings"] + list(args)) or "").strip().strip("'")


def proxy():
    mode = _gs("get", "org.gnome.system.proxy", "mode") or "none"
    host = _gs("get", "org.gnome.system.proxy.http", "host")
    port = _gs("get", "org.gnome.system.proxy.http", "port")
    url = _gs("get", "org.gnome.system.proxy", "autoconfig-url")
    return {"mode": mode, "host": host, "port": int(port) if port.isdigit() else 0, "url": url}


def set_proxy(mode, host="", port=0, url=""):
    run(["gsettings", "set", "org.gnome.system.proxy", "mode", mode])
    if mode == "manual":
        for scheme in ("http", "https"):
            run(["gsettings", "set", "org.gnome.system.proxy." + scheme, "host", host])
            run(["gsettings", "set", "org.gnome.system.proxy." + scheme, "port", str(int(port or 0))])
    if mode == "auto":
        run(["gsettings", "set", "org.gnome.system.proxy", "autoconfig-url", url])
    os.makedirs(os.path.dirname(ENV_FILE), exist_ok=True)
    if mode == "manual" and host:
        p = "http://%s:%d/" % (host, int(port or 0))
        with open(ENV_FILE, "w") as f:
            f.write("# Scritto da ZETA RAYS Impostazioni\n")
            for v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
                f.write("%s=%s\n" % (v, p))
            f.write("no_proxy=localhost,127.0.0.1,::1\n")
    elif os.path.exists(ENV_FILE):
        os.remove(ENV_FILE)


def proxy_env():
    """Proxy visto dai programmi (variabili d'ambiente)."""
    return {k: v for k, v in os.environ.items() if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}


def public_ip_local():
    """IP locali per interfaccia (senza richieste esterne)."""
    out = run(["ip", "-o", "-4", "addr", "show", "scope", "global"])
    return re.findall(r"^\d+:\s+(\S+)\s+inet\s+([\d.]+)", out or "", re.M)
