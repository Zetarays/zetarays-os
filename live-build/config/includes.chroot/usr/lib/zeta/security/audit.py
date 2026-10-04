# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS Security — raccolta dello stato di sicurezza del sistema.

Legge lo stato reale (firewall, aggiornamenti, cifratura, avvio sicuro...) e
lo classifica in modo onesto. Non dichiara mai "sicuro" a priori:

  ATTIVO           la protezione è attiva
  CONFIGURATO      presente e configurato
  NON CONFIGURATO  disponibile ma non attivo
  ATTENZIONE       richiede intervento

Nessuna dipendenza esterna: solo comandi di sistema e file di /proc, /sys.
"""
from __future__ import annotations

import os
import shutil
import json
import subprocess
from dataclasses import dataclass

ACTIVE = "ATTIVO"
CONFIGURED = "CONFIGURATO"
NOT_CONFIGURED = "NON CONFIGURATO"
WARNING = "ATTENZIONE"


@dataclass
class Check:
    key: str
    label: str
    state: str
    detail: str = ""


def _run(cmd: list[str], timeout: float = 6.0) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "").strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _service_active(name: str) -> bool:
    return _run(["systemctl", "is-active", name]) == "active"


def check_firewall() -> Check:
    if _service_active("nftables"):
        # Le regole si leggono solo con privilegi: si usa l'aiutante del Monitor
        # (lettura senza password per gli amministratori).
        raw = _run(["sudo", "-n", "/usr/libexec/zeta-monitor-helper", "firewall"], timeout=8)
        try:
            items = json.loads(raw).get("ruleset", {}).get("nftables", [])
        except (ValueError, AttributeError):
            return Check("firewall", "Firewall", ACTIVE, "nftables attivo")
        rules = sum(1 for i in items if "rule" in i)
        blocks = any(i["chain"].get("hook") == "input" and i["chain"].get("policy") == "drop"
                     for i in items if "chain" in i)
        detail = "nftables attivo · %d regole" % rules
        if blocks:
            detail += " · entrata non richiesta bloccata"
        return Check("firewall", "Firewall", ACTIVE, detail)
    if shutil.which("nft"):
        return Check("firewall", "Firewall", NOT_CONFIGURED,
                     "nftables presente ma non attivo")
    return Check("firewall", "Firewall", NOT_CONFIGURED, "nessun firewall attivo")


def check_encryption() -> Check:
    crypt = _run(["sh", "-c", "lsblk -o TYPE 2>/dev/null | grep -c crypt"])
    if crypt and crypt != "0":
        return Check("encryption", "Cifratura del disco", ACTIVE,
                     "%s volume/i cifrato/i (LUKS)" % crypt)
    return Check("encryption", "Cifratura del disco", NOT_CONFIGURED,
                 "nessun volume cifrato rilevato")


def check_secure_boot() -> Check:
    data = _run(["sh", "-c",
                 "od -An -t u1 /sys/firmware/efi/efivars/SecureBoot-* 2>/dev/null | awk '{print $NF}'"])
    if not os.path.exists("/sys/firmware/efi"):
        return Check("secureboot", "Avvio sicuro", NOT_CONFIGURED, "sistema non UEFI")
    if data.strip() == "1":
        return Check("secureboot", "Avvio sicuro", ACTIVE, "Secure Boot attivo")
    return Check("secureboot", "Avvio sicuro", NOT_CONFIGURED, "Secure Boot non attivo")


def check_updates() -> Check:
    out = _run(["sh", "-c",
                "apt-get -s upgrade 2>/dev/null | grep -c '^Inst'"])
    n = int(out) if out.isdigit() else -1
    if n == 0:
        return Check("updates", "Aggiornamenti", ACTIVE, "sistema aggiornato")
    if n > 0:
        return Check("updates", "Aggiornamenti", WARNING, "%d aggiornamenti disponibili" % n)
    return Check("updates", "Aggiornamenti", NOT_CONFIGURED, "stato non determinato")


def check_apparmor() -> Check:
    if _run(["sh", "-c", "aa-status --enabled 2>/dev/null; echo $?"]).endswith("0"):
        n = _run(["sh", "-c", "aa-status 2>/dev/null | grep -oE '[0-9]+ profiles' | head -1"])
        return Check("apparmor", "Isolamento applicazioni", ACTIVE, n or "AppArmor attivo")
    return Check("apparmor", "Isolamento applicazioni", NOT_CONFIGURED, "AppArmor non attivo")


def check_audit() -> Check:
    if _service_active("auditd"):
        return Check("audit", "Registro di controllo", ACTIVE, "auditd in esecuzione")
    return Check("audit", "Registro di controllo", NOT_CONFIGURED, "auditd non attivo")


def check_network() -> Check:
    listening = _run(["sh", "-c",
                      "ss -tulnH 2>/dev/null | grep -vE '127\\.0\\.0\\.1|::1' | wc -l"])
    n = int(listening) if listening.isdigit() else 0
    if n == 0:
        return Check("network", "Rete", ACTIVE, "nessun servizio esposto verso l'esterno")
    return Check("network", "Rete", CONFIGURED, "%d servizi in ascolto sulla rete" % n)


ALL_CHECKS = [check_firewall, check_encryption, check_secure_boot, check_updates,
              check_apparmor, check_audit, check_network]


def collect() -> list[Check]:
    return [fn() for fn in ALL_CHECKS]


def summary() -> str:
    lines = ["STATO DI SICUREZZA", "─" * 40]
    for c in collect():
        lines.append("%-24s %s" % (c.label, c.state))
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
