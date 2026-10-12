#!/usr/bin/env python3
"""Generate update-network-zeta-rays.sh: brings the network/SSH/firewall setup
of the current image to a ZETA RAYS system already installed from an earlier image.

  tools/gen-update-network.py OUTPUT_FILE
"""
import os, sys
R = os.path.expanduser("~/RAiX/live-build/config/includes.chroot")
FILES = {
    "/etc/nftables.conf": "etc/nftables.conf",
    "/etc/ssh/sshd_config.d/zeta.conf": "etc/ssh/sshd_config.d/zeta.conf",
    "/etc/systemd/system/ssh.service.d/zeta-host-keys.conf": "etc/systemd/system/ssh.service.d/zeta-host-keys.conf",
    "/usr/local/bin/zeta-ssh": "usr/local/bin/zeta-ssh",
}
out = sys.argv[1]
pieces = []
for dest, src in FILES.items():
    text = open(os.path.join(R, src)).read()
    assert "ZETAEOF" not in text
    mode = "0755" if dest.endswith("zeta-ssh") else "0644"
    pieces.append('put_file %s %s <<\'ZETAEOF\'\n%sZETAEOF\n' % (dest, mode, text if text.endswith("\n") else text + "\n"))
body = open(os.path.join(os.path.dirname(__file__), "update-network-zeta-rays.sh.in")).read()
open(out, "w").write(body.replace("@@FILES@@", "".join(pieces)))
os.chmod(out, 0o755)
print("written", out)
