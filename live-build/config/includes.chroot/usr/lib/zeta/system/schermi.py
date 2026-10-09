# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — schermi (monitor): lettura, applicazione sicura e memoria.

Solo logica, niente interfaccia (la pagina e' ui/pagina_schermi.py).

- Lo stato vero viene da Hyprland: «hyprctl -j monitors all» (anche gli schermi
  spenti), con risoluzioni e frequenze che lo schermo dichiara.
- Si applica con le regole di Hyprland (hl.monitor, «hyprctl eval»), mai con
  una shell: i valori arrivano solo da questo modulo e sono controllati.
- Dopo aver applicato si rilegge lo stato e si confronta con quello chiesto.
- La memoria e' per schermo, non per posizione nell'elenco: la chiave e'
  marca + modello + numero di serie (il selettore «desc:» di Hyprland), cosi'
  lo stesso monitor ritrova le sue impostazioni anche su un'altra presa.
  Gli schermi senza questi dati (macchine virtuali) usano il nome della presa.
- Salvato in ~/.config/zeta/schermi.json e tradotto in
  ~/.config/hypr/zeta_schermi.lua, letto da hyprland.lua all'avvio.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time

CFG = os.path.expanduser("~/.config/zeta")
MEMORIA = os.path.join(CFG, "schermi.json")
LUA = os.path.expanduser("~/.config/hypr/zeta_schermi.lua")

# Hyprland: 0 normale, 1 90°, 2 180°, 3 270° (4-7 sono le stesse ribaltate)
ROTAZIONI = (0, 1, 2, 3)
# scale proposte; si tengono solo quelle che dividono esattamente la
# risoluzione (le altre Hyprland le rifiuta e ne sceglie un'altra da solo)
SCALE = (1.0, 1.25, 1.5, 1.6, 1.75, 2.0, 2.5, 3.0)
INTERNI = ("eDP", "LVDS", "DSI")
_MODO = re.compile(r"^(\d+)x(\d+)@([\d.]+)Hz$")
_SICURO = re.compile(r"^[A-Za-z0-9 _.,:()/+-]*$")


# ------------------------------------------------------------------ lettura
def _hyprctl_json(*argomenti):
    try:
        r = subprocess.run(["hyprctl", "-j", *argomenti], capture_output=True,
                           text=True, timeout=5)
        return json.loads(r.stdout or "null")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _descrizione(m: dict) -> str:
    # come Hyprland compone la descrizione breve (m_shortDescription), che e'
    # anche quella letta in Lua all'avvio: devono coincidere alla lettera
    return ("%s %s %s" % (m.get("make", ""), m.get("model", ""), m.get("serial", ""))).strip()


def identita(m: dict) -> str:
    """Il nome stabile dello schermo: marca modello seriale, o la presa."""
    return _descrizione(m) or m.get("name", "")


def selettore(m: dict) -> str:
    desc = _descrizione(m)
    return ("desc:" + desc) if desc else m.get("name", "")


def leggi() -> list[dict]:
    """Gli schermi collegati, accesi e spenti, con i dati che servono."""
    dati = _hyprctl_json("monitors", "all") or []
    out = []
    for m in dati:
        modi = []
        for s in m.get("availableModes", []):
            g = _MODO.match(s)
            if g:
                modi.append((int(g.group(1)), int(g.group(2)), float(g.group(3))))
        specchio = m.get("mirrorOf") or "none"
        out.append({
            "nome": m.get("name", ""),
            "identita": identita(m),
            "selettore": selettore(m),
            "marca": m.get("make", ""), "modello": m.get("model", ""),
            "seriale": m.get("serial", ""), "descrizione": m.get("description", ""),
            "larghezza": int(m.get("width", 0)), "altezza": int(m.get("height", 0)),
            "frequenza": float(m.get("refreshRate", 0.0)),
            "x": int(m.get("x", 0)), "y": int(m.get("y", 0)),
            "scala": float(m.get("scale", 1.0)),
            "rotazione": int(m.get("transform", 0)),
            "acceso": not m.get("disabled", False),
            "specchio": None if specchio in ("none", "", None) else str(specchio),
            "modi": modi,
            "mm": (int(m.get("physicalWidth", 0)), int(m.get("physicalHeight", 0))),
            "fuoco": bool(m.get("focused")),
            "interno": m.get("name", "").startswith(INTERNI),
            "vrr": bool(m.get("vrr")),
            "id": int(m.get("id", -1)),
        })
    # Hyprland indica lo schermo copiato col suo numero: qui serve il nome
    per_id = {str(m["id"]): m["nome"] for m in out}
    for m in out:
        if m["specchio"] is not None:
            m["specchio"] = per_id.get(m["specchio"], m["specchio"])
    return out


# ------------------------------------------------------------------- calcoli
def esatta(w: int, h: int, s: float) -> bool:
    return abs(w / s - round(w / s)) < 1e-6 and abs(h / s - round(h / s)) < 1e-6


# sotto quest'area logica la barra e le finestre non ci stanno piu' (provato:
# 1280x800 al 160% = 800x500 e la barra esce dallo schermo)
AREA_MINIMA = (1024, 600)


def scale_valide(w: int, h: int, attuale: float | None = None) -> list[float]:
    """Le scale che Hyprland accetta per questa risoluzione e che lasciano un
    desktop usabile; il 100% e la scala attuale ci sono sempre."""
    v = [s for s in SCALE if esatta(w, h, s) and
         (s == 1.0 or (max(w, h) / s >= AREA_MINIMA[0] and min(w, h) / s >= AREA_MINIMA[1]))]
    if attuale and all(abs(attuale - s) > 1e-3 for s in v):
        v.append(round(attuale, 3))
    return sorted(v)


def risoluzioni(m: dict) -> list[tuple[int, int]]:
    """Risoluzioni diverse, dalla piu' grande; la prima dell'elenco di
    Hyprland e' quella che lo schermo preferisce (la nativa)."""
    viste, out = set(), []
    for w, h, _hz in m["modi"]:
        if (w, h) not in viste:
            viste.add((w, h))
            out.append((w, h))
    nativa = out[0] if out else None
    resto = sorted((r for r in out if r != nativa), key=lambda r: r[0] * r[1], reverse=True)
    return ([nativa] if nativa else []) + resto


def nativa(m: dict) -> tuple[int, int] | None:
    r = risoluzioni(m)
    return r[0] if r else None


def frequenze(m: dict, w: int, h: int) -> list[float]:
    return sorted({round(hz, 2) for mw, mh, hz in m["modi"] if (mw, mh) == (w, h)}, reverse=True)


def dimensione_logica(c: dict) -> tuple[int, int]:
    """Larghezza e altezza sullo schermo virtuale (scala e rotazione)."""
    w, h = c["larghezza"] / c["scala"], c["altezza"] / c["scala"]
    if c["rotazione"] % 2 == 1:
        w, h = h, w
    return round(w), round(h)


def pollici(m: dict) -> float | None:
    pw, ph = m["mm"]
    if pw <= 0 or ph <= 0:
        return None
    return round(((pw ** 2 + ph ** 2) ** 0.5) / 25.4, 1)


# -------------------------------------------------------- configurazione
def configurazione(schermi: list[dict]) -> dict:
    """{nome: impostazioni} dallo stato attuale (da modificare e applicare)."""
    out = {}
    for m in schermi:
        out[m["nome"]] = {
            "selettore": m["selettore"], "identita": m["identita"],
            "larghezza": m["larghezza"], "altezza": m["altezza"],
            "frequenza": round(m["frequenza"], 2), "x": m["x"], "y": m["y"],
            "scala": m["scala"], "rotazione": m["rotazione"],
            "acceso": m["acceso"], "specchio": m["specchio"],
        }
    return out


def controlla(conf: dict) -> str | None:
    """Errore leggibile, o None se la configurazione si puo' applicare."""
    nomi = set(conf)
    accesi = [n for n, c in conf.items() if c["acceso"] and not c["specchio"]]
    if not accesi:
        return "at-least-one"            # mai tutti spenti o tutti in specchio
    for n, c in conf.items():
        if c["specchio"]:
            if c["specchio"] == n or c["specchio"] not in nomi:
                return "mirror-invalid"
            if conf[c["specchio"]]["specchio"] or not conf[c["specchio"]]["acceso"]:
                return "mirror-invalid"
        if c["rotazione"] not in ROTAZIONI:
            return "invalid"
        if c["larghezza"] <= 0 or c["altezza"] <= 0 or c["scala"] <= 0:
            return "invalid"
        if not _SICURO.match(c["selettore"]):
            return "invalid"
    return None


def _riga_lua(c: dict, nome_specchio: str | None) -> str:
    sel = json.dumps(c["selettore"])
    if not c["acceso"]:
        return "hl.monitor({ output = %s, disabled = true })" % sel
    modo = "%dx%d@%.2f" % (c["larghezza"], c["altezza"], c["frequenza"])
    campi = ["output = %s" % sel, "disabled = false", "mode = %s" % json.dumps(modo),
             "position = %s" % json.dumps("%dx%d" % (c["x"], c["y"])),
             "scale = %s" % json.dumps("%g" % c["scala"]),
             "transform = %d" % c["rotazione"]]
    campi.append("mirror = %s" % json.dumps(nome_specchio or ""))
    return "hl.monitor({ %s })" % ", ".join(campi)


def righe_lua(conf: dict, principale: str | None = None, per_avvio: bool = False) -> list[str]:
    """Le regole di Hyprland per la configurazione. Per lo specchio Hyprland
    vuole il nome della presa dello schermo copiato."""
    righe = [_riga_lua(c, c["specchio"]) for c in conf.values()]
    if principale and principale in conf:
        sel = conf[principale]["selettore"]
        # lo schermo principale: quello del primo spazio di lavoro
        righe.append("hl.workspace_rule({ workspace = \"1\", monitor = %s, default = true })"
                     % json.dumps(sel))
    return righe


def _eval(codice: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(["hyprctl", "eval", codice], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    uscita = (r.stdout or "").strip()
    return (r.returncode == 0 and uscita.startswith("ok")), uscita


def applica(conf: dict, principale: str | None = None) -> tuple[bool, str]:
    """Applica subito (non salva). (ok, errore)"""
    errore = controlla(conf)
    if errore:
        return False, errore
    ok, msg = _eval("\n".join(righe_lua(conf, principale)))
    if not ok:
        return False, msg or "hyprctl"
    # dopo un cambio di schermi le finestre restano dentro l'area utile
    _eval("if zeta_recupera then zeta_recupera() end")
    return True, ""


def verifica(conf: dict, attesa: float = 4.0) -> tuple[bool, list[str]]:
    """Rilegge lo stato vero finche' coincide con quello chiesto (o finisce
    l'attesa). (ok, differenze)"""
    fine = time.monotonic() + attesa
    while True:
        diff = _differenze(conf, {m["nome"]: m for m in leggi()})
        if not diff or time.monotonic() > fine:
            if not diff:
                riallinea_livelli(conf)
            return not diff, diff
        time.sleep(0.25)


def riallinea_livelli(conf: dict) -> None:
    """Barra, scrivania e sfondo al posto giusto dopo uno spostamento.

    Hyprland (0.55) sistema i livelli (layer-shell) di uno schermo mentre
    applica le regole uno schermo alla volta: se poi la posizione cambia
    ancora, restano dove erano (provato: la barra spostata di 106 px e
    tagliata). Li ricalcola quando cambia solo l'area riservata di uno
    schermo, senza toccare la modalita' video: la si porta a 1 e di nuovo
    a 0, un fotogramma dopo l'altro."""
    accesi = [c["selettore"] for c in conf.values() if c["acceso"] and not c["specchio"]]
    for valore in (1, 0):
        _eval("\n".join("hl.monitor({ output = %s, reserved = %d })" % (json.dumps(sel), valore)
                         for sel in accesi))
        time.sleep(0.15)


def _differenze(conf: dict, vero: dict) -> list[str]:
    diff = []
    for n, c in conf.items():
        m = vero.get(n)
        if m is None:
            diff.append("%s: missing" % n)
            continue
        if c["acceso"] != m["acceso"]:
            diff.append("%s: enabled" % n)
            continue
        if not c["acceso"]:
            continue
        if (c["specchio"] or None) != (m["specchio"] or None):
            diff.append("%s: mirror" % n)
            continue
        if c["specchio"]:
            continue
        if (c["larghezza"], c["altezza"]) != (m["larghezza"], m["altezza"]):
            diff.append("%s: resolution" % n)
        if abs(c["frequenza"] - m["frequenza"]) > 0.6:
            diff.append("%s: refresh" % n)
        if abs(c["scala"] - m["scala"]) > 0.01:
            diff.append("%s: scale" % n)
        if c["rotazione"] != m["rotazione"]:
            diff.append("%s: rotation" % n)
        if (c["x"], c["y"]) != (m["x"], m["y"]):
            diff.append("%s: position" % n)
    return diff


# ------------------------------------------------------------------ memoria
def carica_memoria() -> dict:
    try:
        with open(MEMORIA) as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("schermi", {})
            return d
    except (OSError, ValueError):
        pass
    return {"schermi": {}, "principale": None}


def salva(conf: dict, principale: str | None = None) -> None:
    """Ricorda la configurazione di ogni schermo per identita' e scrive le
    regole lette da Hyprland all'avvio. Gli schermi che ora non ci sono
    restano ricordati."""
    mem = carica_memoria()
    for n, c in conf.items():
        voce = {k: c[k] for k in ("larghezza", "altezza", "frequenza", "x", "y", "scala",
                                  "rotazione", "acceso", "selettore")}
        # lo specchio si ricorda per identita' dello schermo copiato
        voce["specchio"] = conf[c["specchio"]]["identita"] if c["specchio"] in conf else None
        mem["schermi"][c["identita"]] = voce
    if principale in conf:
        mem["principale"] = conf[principale]["identita"]
    os.makedirs(CFG, exist_ok=True)
    tmp = MEMORIA + ".tmp"
    with open(tmp, "w") as f:
        json.dump(mem, f, indent=2)
    os.replace(tmp, MEMORIA)
    scrivi_lua(mem)


def scrivi_lua(mem: dict) -> None:
    """~/.config/hypr/zeta_schermi.lua: una funzione che hyprland.lua chiama
    dopo la regola generale. Lo specchio usa il nome della presa, che all'avvio
    si conosce solo per gli schermi presenti: si risolve in Lua."""
    righe = ["-- ZETA RAYS — generato da Impostazioni › Schermi (system/schermi.py).",
             "-- Una regola per schermo, riconosciuto da marca, modello e numero di serie.",
             "return function()",
             "    local prese = {}",
             "    for _, m in ipairs(hl.get_monitors()) do",
             "        local d = ((m.description or \"\") ~= \"\") and m.description or m.name",
             "        prese[d] = m.name",
             "    end"]
    for ident, c in sorted(mem.get("schermi", {}).items()):
        if not _SICURO.match(ident) or not _SICURO.match(c.get("selettore", "")):
            continue
        sel = json.dumps(c["selettore"])
        if not c.get("acceso", True):
            righe.append("    hl.monitor({ output = %s, disabled = true })" % sel)
            continue
        if c.get("specchio") and _SICURO.match(c["specchio"]):
            righe.append("    if prese[%s] then hl.monitor({ output = %s, disabled = false, mirror = prese[%s] }) end"
                         % (json.dumps(c["specchio"]), sel, json.dumps(c["specchio"])))
            continue
        modo = "%dx%d@%.2f" % (c["larghezza"], c["altezza"], c["frequenza"])
        righe.append("    hl.monitor({ output = %s, disabled = false, mode = %s, position = %s, "
                     "scale = %s, transform = %d })"
                     % (sel, json.dumps(modo), json.dumps("%dx%d" % (c["x"], c["y"])),
                        json.dumps("%g" % c["scala"]), int(c["rotazione"])))
    p = mem.get("principale")
    if p and p in mem.get("schermi", {}) and _SICURO.match(p):
        righe.append("    hl.workspace_rule({ workspace = \"1\", monitor = %s, default = true })"
                     % json.dumps(mem["schermi"][p]["selettore"]))
    righe.append("end")
    os.makedirs(os.path.dirname(LUA), exist_ok=True)
    tmp = LUA + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(righe) + "\n")
    os.replace(tmp, LUA)


def principale_salvato(schermi: list[dict]) -> str | None:
    p = carica_memoria().get("principale")
    for m in schermi:
        if m["identita"] == p:
            return m["nome"]
    return None
