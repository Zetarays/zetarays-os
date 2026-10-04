# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — cosa apt puo' installare davvero, chiesto ad apt.

Un pulsante «Installa» ha senso solo se apt conosce il pacchetto. Qui si
chiede ad apt, in una sola chiamata e senza rete (legge gli indici gia'
scaricati), per ogni pacchetto: la versione installata e quella installabile.
Se un pacchetto non ha candidato si spiega perche', invece di lasciare che
sia Synaptic a dire «non esiste».
"""
import glob
import os
import subprocess
import time

LISTE = "/var/lib/apt/lists"
VECCHIO = 7 * 24 * 3600          # indici piu' vecchi di una settimana: da aggiornare

# Pacchetti noti che Debian 13 non ha. Non si aggiungono i repository di Kali
# per averli: Kali e Debian mescolati si rompono a vicenda al primo
# aggiornamento (lo dice Kali stessa), e il sistema smette di aggiornarsi.
MOTIVI = {
    "radare2": ("Non incluso in Debian 13: i suoi autori pubblicano versioni nuove così spesso "
                "che Debian non riusciva a garantirne le correzioni di sicurezza nella versione stabile."),
    "theharvester": "Esiste solo nei repository di Kali Linux, non in Debian. Mescolare i due "
                    "rompe gli aggiornamenti del sistema, quindi ZETA RAYS non lo fa.",
}


def disponibilita(pacchetti, timeout=20):
    """{pacchetto: {"installato": versione|None, "candidato": versione|None}}.

    Una chiamata sola ad apt-cache per tutti. In caso di errore ogni pacchetto
    risulta sconosciuto (None, None): meglio nessun pulsante che uno falso.
    """
    ris = {p: {"installato": None, "candidato": None} for p in pacchetti}
    if not pacchetti:
        return ris
    try:
        r = subprocess.run(["apt-cache", "policy", "--"] + list(pacchetti),
                           capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C.UTF-8", LANG="C.UTF-8"))
    except (OSError, subprocess.SubprocessError):
        return ris
    corrente = None
    for riga in r.stdout.splitlines():
        if riga and not riga[0].isspace() and riga.endswith(":"):
            corrente = riga[:-1]
            if corrente not in ris:           # es. «pkg:arm64»
                corrente = corrente.split(":")[0]
            continue
        if corrente not in ris:
            continue
        s = riga.strip()
        if s.startswith("Installed:"):
            v = s.split(":", 1)[1].strip()
            ris[corrente]["installato"] = None if v == "(none)" else v
        elif s.startswith("Candidate:"):
            v = s.split(":", 1)[1].strip()
            ris[corrente]["candidato"] = None if v == "(none)" else v
    return ris


def eta_indici():
    """Secondi dall'ultimo «apt update» riuscito, None se non ci sono indici."""
    file = glob.glob(os.path.join(LISTE, "*_InRelease")) + glob.glob(os.path.join(LISTE, "*_Release"))
    if not file:
        return None
    try:
        return max(0, time.time() - max(os.path.getmtime(f) for f in file))
    except OSError:
        return None


def descrivi_eta(sec):
    if sec is None:
        return "mai scaricato"
    giorni = int(sec // 86400)
    if giorni == 0:
        ore = int(sec // 3600)
        return "aggiornato da %d or%s" % (ore, "a" if ore == 1 else "e") if ore else "appena aggiornato"
    return "vecchio di %d giorn%s" % (giorni, "o" if giorni == 1 else "i")


def indici_vecchi():
    e = eta_indici()
    return e is None or e > VECCHIO


def perche_manca(pacchetto):
    """Spiegazione per un pacchetto senza candidato."""
    if pacchetto in MOTIVI:
        return MOTIVI[pacchetto]
    if indici_vecchi():
        return ("Non trovato nell'elenco dei pacchetti, che è %s: aggiornalo e riprova."
                % descrivi_eta(eta_indici()))
    return "Non presente nei repository configurati (Debian 13 e backports)."


def repository():
    """Le righe «deb» attive, da sources.list, .list e .sources (formato deb822)."""
    righe = []
    for f in ["/etc/apt/sources.list"] + sorted(glob.glob("/etc/apt/sources.list.d/*.list")):
        try:
            for r in open(f, encoding="utf-8", errors="replace"):
                r = r.strip()
                if r.startswith("deb ") or r.startswith("deb-src "):
                    righe.append((os.path.basename(f), r))
        except OSError:
            pass
    for f in sorted(glob.glob("/etc/apt/sources.list.d/*.sources")):
        try:
            blocchi = open(f, encoding="utf-8", errors="replace").read().split("\n\n")
        except OSError:
            continue
        for b in blocchi:
            campi = {}
            for r in b.splitlines():
                if ":" in r and not r.startswith((" ", "#")):
                    k, v = r.split(":", 1)
                    campi[k.strip().lower()] = v.strip()
            if campi.get("enabled", "yes").lower() == "no" or "uris" not in campi:
                continue
            righe.append((os.path.basename(f), "%s %s %s %s" % (
                campi.get("types", "deb"), campi["uris"], campi.get("suites", ""),
                campi.get("components", ""))))
    return righe
