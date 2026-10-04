#!/usr/bin/env python3
"""Genera aggiorna-rete-zeta-rays.sh: porta la rete/SSH/firewall dell'immagine
attuale su un ZETA RAYS gia' installato con un'immagine precedente."""
import os, sys
R = os.path.expanduser("~/RAiX/live-build/config/includes.chroot")
FILE = {
    "/etc/nftables.conf": "etc/nftables.conf",
    "/etc/ssh/sshd_config.d/zeta.conf": "etc/ssh/sshd_config.d/zeta.conf",
    "/etc/systemd/system/ssh.service.d/zeta-chiavi.conf": "etc/systemd/system/ssh.service.d/zeta-chiavi.conf",
    "/usr/local/bin/zeta-ssh": "usr/local/bin/zeta-ssh",
}
out = sys.argv[1]
parti = []
for dest, src in FILE.items():
    testo = open(os.path.join(R, src)).read()
    assert "ZETAFINE" not in testo
    modo = "0755" if dest.endswith("zeta-ssh") else "0644"
    parti.append('scrivi %s %s <<\'ZETAFINE\'\n%sZETAFINE\n' % (dest, modo, testo if testo.endswith("\n") else testo + "\n"))
corpo = open(os.path.join(os.path.dirname(__file__), "aggiorna-rete-zeta-rays.sh.in")).read()
open(out, "w").write(corpo.replace("@@FILE@@", "".join(parti)))
os.chmod(out, 0o755)
print("scritto", out)
