# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — dock personalizzabile.

Il dock non è fisso: l'utente sceglie quali applicazioni mostrare (da
Impostazioni › Dock). La scelta è salvata in ~/.config/zeta/dock.json e da qui
si rigenera la configurazione di Waybar (~/.config/waybar/config.jsonc), che
viene ricaricata a caldo. Se qualcosa va storto, la barra esistente resta
intatta: non si genera mai un file rotto.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
CFG = HOME / ".config" / "zeta"
DOCK_FILE = CFG / "dock.json"
WAYBAR = HOME / ".config" / "waybar" / "config.jsonc"

SEGNALE_DOCK = 12        # SIGRTMIN+12: finestre aperte/chiuse (lo manda zeta-spazi)

ICON_DIRS = [
    "/usr/share/icons/zeta/scalable/apps",
    "/usr/share/icons/hicolor/scalable/apps",
    "/usr/share/pixmaps",
]

# Dock predefinito: accesso immediato alle funzioni principali del sistema.
DEFAULT = [
    {"cmd": "thunar",             "name": "File",          "icon": "org.xfce.thunar"},
    {"cmd": "foot",               "name": "Terminale",     "icon": "foot"},
    {"cmd": "firefox-esr",        "name": "Firefox",       "icon": "firefox-esr"},
    # Posta (Thunderbird): suggerimento, puntino quando e' aperta, «Nuovo
    # messaggio» nel menu. Lo stato lo chiede il dock solo quando si apre o si chiude
    # una finestra (segnale di zeta-spazi): nessun controllo periodico.
    {"cmd": "zeta-posta",         "name": "Posta",         "icon": "zeta-posta",
     "stato": "zeta-posta stato", "voci": [["Nuovo messaggio", "zeta-posta nuovo"]]},
    {"cmd": "gnome-text-editor",  "name": "Editor",        "icon": "org.gnome.TextEditor"},
    {"cmd": "zeta-monitor",       "name": "Monitor",       "icon": "zeta-monitor"},
    {"cmd": "zeta-sicurezza",     "name": "Sicurezza",     "icon": "zeta-sicurezza"},
    {"cmd": "synaptic-pkexec",    "name": "Pacchetti",     "icon": "synaptic"},
    {"cmd": "zeta-impostazioni",  "name": "Impostazioni",  "icon": "zeta-impostazioni"},
]


def resolve_icon(name: str) -> str:
    """Nome icona -> percorso di un file, cercando prima nel tema di ZETA RAYS."""
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for d in ICON_DIRS:
        for ext in (".svg", ".png"):
            p = os.path.join(d, name + ext)
            if os.path.exists(p):
                return p
    # ripiego: icona generica
    fallback = "/usr/share/icons/zeta/scalable/apps/zeta-app.svg"
    return fallback if os.path.exists(fallback) else name


def _read_desktop(path: Path) -> dict | None:
    try:
        txt = path.read_text(errors="replace")
    except OSError:
        return None
    d = {}
    in_entry = False
    for line in txt.splitlines():
        if line.strip() == "[Desktop Entry]":
            in_entry = True
            continue
        if in_entry and line.startswith("["):
            break
        if in_entry and "=" in line:
            k, _, v = line.partition("=")
            d.setdefault(k.strip(), v.strip())
    if d.get("Type") != "Application" or d.get("NoDisplay") == "true":
        return None
    exec_ = re.sub(r"%[a-zA-Z]", "", d.get("Exec", "")).strip()
    if not exec_:
        return None
    return {"id": path.stem, "name": d.get("Name", path.stem),
            "icon": d.get("Icon", ""), "exec": exec_}


def installed_apps() -> list[dict]:
    """Applicazioni grafiche installate, per la scelta del dock."""
    apps, seen = [], set()
    for d in ("/usr/share/applications", str(HOME / ".local/share/applications")):
        if not os.path.isdir(d):
            continue
        for path in sorted(Path(d).glob("*.desktop")):
            info = _read_desktop(path)
            if info and info["name"].lower() not in seen:
                seen.add(info["name"].lower())
                apps.append(info)
    apps.sort(key=lambda a: a["name"].lower())
    return apps


def load_dock() -> list[dict]:
    try:
        with open(DOCK_FILE) as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            voci = [e for e in data if isinstance(e, dict) and e.get("cmd")]
            for e in voci:
                # dock salvati dalla 1.7 precedente: il menu proprio della
                # Posta e' diventato una voce del menu comune
                if e.pop("menu", None) == "zeta-posta menu":
                    e.setdefault("voci", [["Nuovo messaggio", "zeta-posta nuovo"]])
            return voci
    except (OSError, ValueError):
        pass
    return list(DEFAULT)


def save_dock(entries: list[dict]) -> None:
    CFG.mkdir(parents=True, exist_ok=True)
    tmp = DOCK_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    tmp.replace(DOCK_FILE)


def entry_from_desktop(app: dict) -> dict:
    """Converte una app installata in una voce del dock."""
    return {"cmd": app["exec"], "name": app["name"], "icon": app.get("icon", "")}


def posizione() -> str:
    """Barra in basso o in alto (Impostazioni › Dock)."""
    try:
        v = (CFG / "dock-posizione").read_text().strip()
    except OSError:
        return "bottom"
    return v if v in ("bottom", "top") else "bottom"


def bar_icon(name: str, fallback: str) -> str:
    """Icona della barra ricolorata per il tema (generata da zeta-accent)."""
    p = CFG / "barra" / name
    return str(p) if p.exists() else fallback


def icon_size() -> int:
    """Dimensione delle icone del dock scelta in Impostazioni > Aspetto."""
    try:
        v = int((CFG / "icon-size").read_text().strip())
    except (OSError, ValueError):
        return 42
    return v if 28 <= v <= 64 else 42


def render_config(dock: list[dict]) -> dict:
    """Configurazione Waybar completa con il dock richiesto."""
    dock_modules = []
    images = {}
    size = icon_size()
    for i, e in enumerate(dock):
        key = "image#dock%d" % i
        dock_modules.append(key)
        images[key] = {
            "path": resolve_icon(e.get("icon", "")),
            "size": size, "tooltip": False,
            "on-click": e["cmd"],
        }
        if e.get("stato"):
            # icona e suggerimento dati da un comando breve, rieseguito al
            # segnale SIGRTMIN+12 (finestre aperte o chiuse); l'intervallo
            # lungo e' solo una rete di sicurezza
            del images[key]["path"]
            images[key].update({"exec": e["stato"], "signal": SEGNALE_DOCK,
                                "interval": 300, "tooltip": True})
        # tasto destro: lo stesso menu per tutte le icone (Apri, Chiudi se
        # aperta, Rimuovi dal Dock, Opzioni, Impostazioni dell'app)
        images[key]["on-click-right"] = "zeta-dock menu %d" % i

    cfg = {
        "layer": "top", "position": posizione(), "height": max(60, size + 18),
        "margin-left": 12, "margin-right": 12, "spacing": 0,
        ("margin-bottom" if posizione() == "bottom" else "margin-top"): 12,
        "modules-left": ["image#launcher", "group/spazi"],
        "modules-center": ["group/dock", "group/ridotte"],
        "modules-right": ["image#search", "image#net", "image#vol",
                          "image#bat", "clock", "image#power"],
        "image#launcher": {
            "exec": "echo $HOME/.config/zeta/launcher.svg",
            # Il marchio e l'elemento d'identita della barra. E un disegno a
            # linee sottili: a 20 spariva, e anche a 34 le linee scendevano a
            # circa un pixel e l'antialiasing le spegneva. A 42 e alto quanto
            # le tessere del dock e le linee restano nitide.
            "size": 42, "signal": 8, "tooltip": False, "on-click": "zeta-pannello launcher",
        },
        # Finestre ridotte a icona: una miniatura per finestra accanto al dock,
        # come su macOS (zeta-riduci ne fa la foto prima di nasconderla). Un
        # posto senza finestra non ha immagine e Waybar non lo mostra.
        # Aggiornate subito da zeta-riduci e zeta-spazi (SIGRTMIN+9).
        "group/ridotte": {"orientation": "horizontal",
                          "modules": ["image#ridotta%d" % n for n in range(8)]},
        **{"image#ridotta%d" % n: {
            "exec": "zeta-finestre anteprima %d" % n, "signal": 9, "interval": 300,
            "size": int(size * 1.6), "tooltip": True,
            "on-click": "zeta-riduci ripristina-n %d" % n,
            "on-click-right": "zeta-riduci menu %d" % n,
            "on-click-middle": "zeta-finestre chiudi-n %d" % n,
        } for n in range(8)},
        "image#search": {
            "path": bar_icon("cerca.svg", "/usr/share/zeta/status/cerca.svg"),
            "size": 18, "tooltip": False, "on-click": "zeta-pannello cerca",
        },
        # Spazi di lavoro: non si usa "hyprland/workspaces" perché per
        # attivarne uno manda a Hyprland la sintassi storica, che la
        # configurazione in Lua di Hyprland 0.55 rifiuta — cliccare un numero
        # nella barra non faceva nulla. zeta-spazi ascolta gli eventi di
        # Hyprland (nessun sondaggio continuo) e usa la sintassi corretta.
        "group/spazi": {
            "orientation": "horizontal",
            "modules": ["custom/spazio%d" % n for n in (1, 2, 3)],
        },
        # Comandi brevi che finiscono da soli, aggiornati dal segnale che manda
        # «zeta-spazi segnala». Un modulo che resta aperto verrebbe lasciato
        # indietro come processo zombie a ogni ricarica della barra.
        **{"custom/spazio%d" % n: {
            "exec": "zeta-spazi stato %d" % n, "return-type": "json",
            "interval": 120, "signal": 10,
            "on-click": "zeta-spazi vai %d" % n, "tooltip": False,
        } for n in (1, 2, 3)},
        "group/dock": {"orientation": "horizontal", "modules": dock_modules},
        # la rete: aggiornata da NetworkManager quando cambia (SIGRTMIN+13,
        # /etc/NetworkManager/dispatcher.d/90-zeta-barra); l'intervallo lungo
        # e' solo una rete di sicurezza
        "image#net": {"exec": "zeta-status net", "interval": 60, "signal": 13, "size": 18,
                      "tooltip": False, "on-click": "zeta-pannello controllo"},
        # Il volume si aggiorna con un segnale (zeta-volume lo manda appena
        # cambia), non rileggendo lo stato ogni 2 secondi: la lettura
        # periodica resta solo come rete di sicurezza.
        "image#vol": {"exec": "zeta-status vol", "interval": 60, "signal": 11,
                      "size": 18,
                      "tooltip": False, "on-click": "zeta-pannello controllo",
                      "on-scroll-up": "zeta-volume su",
                      "on-scroll-down": "zeta-volume giu"},
        "image#bat": {"exec": "zeta-status bat", "interval": 60, "size": 20,
                      "tooltip": False, "on-click": "zeta-pannello controllo"},
        "image#power": {"path": bar_icon("power.svg", "/usr/share/zeta/status/power.svg"),
                        "size": 18,
                        "tooltip": False, "on-click": "zeta-pannello energia"},
        "clock": {
            "format": "<span weight='500'>{0:%H:%M}</span>\n<span size='8.5pt' foreground='#8A8A8E'>{0:L%a %d %b}</span>",
            "locale": "it_IT.UTF-8", "justify": "right",
            "tooltip-format": "<span size='11pt'>{0:L%A %d %B %Y}</span>\n\n<tt>{calendar}</tt>",
            "calendar": {"mode": "month", "weeks-pos": "",
                         "format": {"months": "<span color='#EDEDEA'><b>{}</b></span>",
                                    "weekdays": "<span color='#8A8A8E'>{}</span>",
                                    "today": "<span color='#3A8DFF'><b>{}</b></span>"}},
            "on-click": "zeta-pannello controllo",
        },
    }
    cfg.update(images)
    return cfg


def reload_waybar() -> None:
    """Ricarica Waybar a caldo, tramite zeta-barra: una ricarica alla volta e
    poi il controllo che la barra sia rimasta una sola (le ricariche con
    SIGUSR2 ravvicinate a volte la duplicavano). Non aspetta: torna subito."""
    try:
        subprocess.Popen(["zeta-barra", "ricarica"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        try:   # zeta-barra assente (sistema vecchio): ricarica diretta
            out = subprocess.run(["pgrep", "-x", "waybar"], capture_output=True, text=True)
            for pid in out.stdout.split()[:1]:
                os.kill(int(pid), signal.SIGUSR2)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass


def apply(dock: list[dict] | None = None, reload: bool = True) -> bool:
    """Genera config.jsonc dal dock (o da dock.json) e ricarica Waybar.

    Con reload=False la barra non viene toccata: serve a chi ricarica una volta
    sola alla fine (due ricariche ravvicinate fanno cadere Waybar)."""
    if dock is None:
        dock = load_dock()
    cfg = render_config(dock)
    WAYBAR.parent.mkdir(parents=True, exist_ok=True)
    tmp = WAYBAR.with_suffix(".tmp")
    header = ("// ZETA RAYS — barra in basso con dock (generato da zeta-dock;\n"
              "// personalizza da Impostazioni › Dock, non modificare a mano)\n")
    try:
        with open(tmp, "w") as f:
            f.write(header)
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(WAYBAR)
    except OSError:
        return False
    if reload:
        reload_waybar()
    return True
