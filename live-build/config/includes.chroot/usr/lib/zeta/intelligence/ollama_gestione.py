# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — gestione di Ollama (il modello AI locale).

Tutto passa dall'interfaccia locale di Ollama (http://127.0.0.1:11434): niente
comandi da terminale, niente permessi speciali, tranne avvio e arresto del
servizio, che chiedono la password (pkexec). Ogni funzione ha un tempo
massimo: se Ollama non risponde, l'interfaccia lo dice invece di bloccarsi.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not BASE.startswith("http"):
    BASE = "http://" + BASE


def _get(percorso: str, timeout: float = 3.0):
    with urllib.request.urlopen(BASE + percorso, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _richiesta(metodo: str, percorso: str, dati: dict, timeout: float = 30.0):
    req = urllib.request.Request(BASE + percorso, data=json.dumps(dati).encode(),
                                 headers={"Content-Type": "application/json"}, method=metodo)
    return urllib.request.urlopen(req, timeout=timeout)


def installato() -> bool:
    return bool(shutil.which("ollama"))


def servizio_attivo() -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", "ollama"],
                              timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def versione() -> str:
    try:
        return _get("/api/version").get("version", "")
    except (OSError, ValueError):
        return ""


def modelli() -> list[dict]:
    """Modelli installati: nome, dimensione (GB), famiglia, parametri."""
    try:
        dati = _get("/api/tags").get("models", [])
    except (OSError, ValueError):
        return []
    out = []
    for m in dati:
        d = m.get("details") or {}
        out.append({"nome": m.get("name", ""), "gb": (m.get("size") or 0) / 1e9,
                    "famiglia": d.get("family", ""), "parametri": d.get("parameter_size", ""),
                    "quantizzazione": d.get("quantization_level", "")})
    return sorted(out, key=lambda m: m["nome"])


def caricati() -> list[dict]:
    """Modelli in memoria adesso: nome, RAM/VRAM occupate (GB), scadenza."""
    try:
        dati = _get("/api/ps").get("models", [])
    except (OSError, ValueError):
        return []
    return [{"nome": m.get("name", ""), "gb": (m.get("size") or 0) / 1e9,
             "vram_gb": (m.get("size_vram") or 0) / 1e9, "fino_a": m.get("expires_at", "")}
            for m in dati]


def risorse_processo() -> dict:
    """Memoria e CPU dei processi di Ollama (server e motore del modello)."""
    tot_rss, cpu = 0, 0.0
    try:
        import psutil
        for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
            n = (p.info.get("name") or "").lower()
            if n.startswith("ollama") or n in ("llama-server", "ollama_llama_server"):
                tot_rss += getattr(p.info.get("memory_info"), "rss", 0) or 0
                cpu += p.info.get("cpu_percent") or 0.0
    except Exception:  # noqa: BLE001 - dato accessorio: se manca, zero
        pass
    return {"ram_gb": tot_rss / 1e9, "cpu": cpu}


def libera_memoria() -> int:
    """Scarica dalla memoria i modelli caricati (restano installati)."""
    n = 0
    for m in caricati():
        try:
            _richiesta("POST", "/api/generate", {"model": m["nome"], "keep_alive": 0}, 20).read()
            n += 1
        except (OSError, ValueError):
            pass
    return n


def rimuovi(nome: str) -> tuple[bool, str]:
    try:
        _richiesta("DELETE", "/api/delete", {"model": nome}, 60).read()
        return True, "Modello %s rimosso." % nome
    except urllib.error.HTTPError as e:
        return False, "Ollama ha rifiutato: %s" % e.read().decode("utf-8", "replace")[:200]
    except OSError as e:
        return False, "Ollama non risponde (%s)." % e


def scarica(nome: str, avanzamento=None, fermo=None) -> tuple[bool, str]:
    """Scarica un modello dalla libreria di Ollama (ollama.com/library).

    avanzamento(testo, frazione 0..1 o None) viene chiamato man mano;
    fermo() -> True interrompe il download (quello che manca si riprende
    la volta dopo: Ollama tiene i pezzi gia' scaricati).
    """
    nome = nome.strip()
    if not nome or any(c.isspace() for c in nome):
        return False, "Nome del modello non valido (esempio: llama3.2:3b)."
    try:
        resp = _richiesta("POST", "/api/pull", {"model": nome, "stream": True}, 3600)
    except urllib.error.HTTPError as e:
        return False, "Ollama ha rifiutato: %s" % e.read().decode("utf-8", "replace")[:200]
    except OSError as e:
        return False, "Ollama non risponde (%s)." % e
    try:
        for riga in resp:
            if fermo and fermo():
                resp.close()
                return False, "Download interrotto: riprendendolo riparte da dove era arrivato."
            try:
                d = json.loads(riga.decode("utf-8"))
            except ValueError:
                continue
            if d.get("error"):
                return False, "Errore: %s" % d["error"]
            tot, fatto = d.get("total"), d.get("completed")
            frazione = (fatto / tot) if tot and fatto is not None else None
            if avanzamento:
                testo = d.get("status", "")
                if frazione is not None:
                    testo = "%s  %.0f%% di %.1f GB" % (testo, frazione * 100, tot / 1e9)
                avanzamento(testo, frazione)
            if d.get("status") == "success":
                return True, "Modello %s scaricato." % nome
    except OSError as e:
        return False, "Download interrotto (%s)." % e
    finally:
        resp.close()
    return False, "Download non completato."


def servizio(azione: str) -> tuple[bool, str]:
    """Avvia, ferma o riavvia il servizio (chiede la password: pkexec)."""
    if azione not in ("start", "stop", "restart"):
        return False, "Azione sconosciuta."
    try:
        p = subprocess.run(["pkexec", "systemctl", azione, "ollama"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if p.returncode == 0:
        return True, {"start": "Ollama avviato.", "stop": "Ollama fermato.",
                      "restart": "Ollama riavviato."}[azione]
    if p.returncode in (126, 127):
        return False, "Operazione annullata."
    return False, (p.stderr or "Errore").strip()[:200]
