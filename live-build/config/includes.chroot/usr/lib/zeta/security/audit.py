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
import sys
from dataclasses import dataclass

sys.path.insert(0, "/usr/lib/zeta")
from i18n import ntr, tr  # noqa: E402

# stati: chiavi stabili; il testo da mostrare e' state_label()
ACTIVE = "active"
CONFIGURED = "configured"
NOT_CONFIGURED = "not-configured"
WARNING = "warning"


def state_label(state: str) -> str:
    return {ACTIVE: tr("ACTIVE"), CONFIGURED: tr("CONFIGURED"),
            NOT_CONFIGURED: tr("NOT CONFIGURED"), WARNING: tr("ATTENTION")}.get(state, state)


@dataclass
class Check:
    key: str
    label: str
    state: str
    detail: str = ""


def _run(cmd: list[str], timeout: float = 6.0) -> str:
    # the output is parsed: always in the C locale, whatever the user's language
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C"))
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
            return Check("firewall", tr("Firewall"), ACTIVE, tr("nftables active"))
        rules = sum(1 for i in items if "rule" in i)
        blocks = any(i["chain"].get("hook") == "input" and i["chain"].get("policy") == "drop"
                     for i in items if "chain" in i)
        parts = [tr("nftables active"), ntr("{n} rule", "{n} rules", rules).format(n=rules)]
        if blocks:
            parts.append(tr("unsolicited incoming traffic blocked"))
        return Check("firewall", tr("Firewall"), ACTIVE, " · ".join(parts))
    if shutil.which("nft"):
        return Check("firewall", tr("Firewall"), NOT_CONFIGURED,
                     tr("nftables installed but not active"))
    return Check("firewall", tr("Firewall"), NOT_CONFIGURED, tr("no active firewall"))


def check_encryption() -> Check:
    crypt = _run(["sh", "-c", "lsblk -o TYPE 2>/dev/null | grep -c crypt"])
    n = int(crypt) if crypt.isdigit() else 0
    if n:
        return Check("encryption", tr("Disk encryption"), ACTIVE,
                     ntr("{n} encrypted volume (LUKS)", "{n} encrypted volumes (LUKS)", n).format(n=n))
    return Check("encryption", tr("Disk encryption"), NOT_CONFIGURED,
                 tr("no encrypted volume detected"))


def check_secure_boot() -> Check:
    data = _run(["sh", "-c",
                 "od -An -t u1 /sys/firmware/efi/efivars/SecureBoot-* 2>/dev/null | awk '{print $NF}'"])
    if not os.path.exists("/sys/firmware/efi"):
        return Check("secureboot", tr("Secure boot"), NOT_CONFIGURED, tr("not a UEFI system"))
    if data.strip() == "1":
        return Check("secureboot", tr("Secure boot"), ACTIVE, tr("Secure Boot on"))
    return Check("secureboot", tr("Secure boot"), NOT_CONFIGURED, tr("Secure Boot off"))


def check_updates() -> Check:
    out = _run(["sh", "-c",
                "apt-get -s upgrade 2>/dev/null | grep -c '^Inst'"])
    n = int(out) if out.isdigit() else -1
    if n == 0:
        return Check("updates", tr("Updates"), ACTIVE, tr("system up to date"))
    if n > 0:
        return Check("updates", tr("Updates"), WARNING,
                     ntr("{n} update available", "{n} updates available", n).format(n=n))
    return Check("updates", tr("Updates"), NOT_CONFIGURED, tr("status unknown"))


def check_apparmor() -> Check:
    if _run(["sh", "-c", "aa-status --enabled 2>/dev/null; echo $?"]).endswith("0"):
        n = _run(["sh", "-c", "aa-status 2>/dev/null | grep -oE '[0-9]+ profiles' | head -1"]).split()
        detail = (ntr("{n} profile", "{n} profiles", int(n[0])).format(n=int(n[0]))
                  if n and n[0].isdigit() else tr("AppArmor active"))
        return Check("apparmor", tr("App isolation"), ACTIVE, detail)
    return Check("apparmor", tr("App isolation"), NOT_CONFIGURED, tr("AppArmor not active"))


def check_audit() -> Check:
    if _service_active("auditd"):
        return Check("audit", tr("Audit log"), ACTIVE, tr("auditd running"))
    return Check("audit", tr("Audit log"), NOT_CONFIGURED, tr("auditd not active"))


def check_network() -> Check:
    listening = _run(["sh", "-c",
                      "ss -tulnH 2>/dev/null | grep -vE '127\\.0\\.0\\.1|::1' | wc -l"])
    n = int(listening) if listening.isdigit() else 0
    if n == 0:
        return Check("network", tr("Network"), ACTIVE, tr("no services exposed to the outside"))
    return Check("network", tr("Network"), CONFIGURED,
                 ntr("{n} service listening on the network", "{n} services listening on the network",
                     n).format(n=n))


ALL_CHECKS = [check_firewall, check_encryption, check_secure_boot, check_updates,
              check_apparmor, check_audit, check_network]


def collect() -> list[Check]:
    return [fn() for fn in ALL_CHECKS]


def summary() -> str:
    lines = [tr("SECURITY STATUS"), "─" * 40]
    for c in collect():
        lines.append("%-24s %s" % (c.label, state_label(c.state)))
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
