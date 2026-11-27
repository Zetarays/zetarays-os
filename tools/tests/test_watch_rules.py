#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for usr/lib/zeta/security/watch_rules.py with real Debian 13 log
lines (sshd, PAM, sudo, shadow utils, kernel, auditd).

    python3 tools/tests/test_watch_rules.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "live-build", "config", "includes.chroot",
                                "usr", "lib", "zeta"))
from security import watch_rules as W  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


def j(ident, msg, uid="0"):
    """A journal entry as the real program writes it (root, or the kernel)."""
    e = {"SYSLOG_IDENTIFIER": ident, "MESSAGE": msg, "_UID": uid}
    if ident == "kernel":
        e["_TRANSPORT"] = "kernel"
    return W.from_journal(e)


def codes(events):
    return [e["code"] for e in events]


# --- SSH
e = j("sshd-session", "Failed password for zeta from 203.0.113.7 port 51234 ssh2")
check("ssh failed", codes(e) == ["ssh_failed"] and e[0]["params"]["address"] == "203.0.113.7"
      and e[0]["params"]["local"] is False, e)
e = j("sshd", "Failed password for invalid user admin from 198.51.100.4 port 4444 ssh2")
check("ssh failed invalid user", codes(e) == ["ssh_failed"] and e[0]["params"]["user"] == "admin", e)
check("ssh invalid user line counted once", j("sshd", "Invalid user admin from 198.51.100.4 port 4444") == [])
# log injection: the user name contains "from ADDRESS port N"; the address is
# the real one, at the end of the line
e = j("sshd-session", "Failed password for invalid user x from 127.0.0.1 port 1 from 198.51.100.9 port 40222 ssh2")
check("injected address ignored", codes(e) == ["ssh_failed"] and e[0]["params"]["address"] == "198.51.100.9", e)
e = j("sshd-session", "Failed password for invalid user x from 127.0.0.1 port 1", uid="0")
check("line ending inside the name still parsed honestly", e == [] or e[0]["params"]["address"] == "127.0.0.1")
# a normal user writing a line that claims to be sshd (logger -t sshd)
check("spoofed sshd line from a user ignored",
      j("sshd", "Failed password for zeta from 10.9.9.9 port 1 ssh2", uid="1000") == [])
check("spoofed useradd line ignored", j("useradd", "new user: name=x, UID=1005, GID=1005", uid="1000") == [])
check("spoofed kernel line ignored", W.from_journal({"SYSLOG_IDENTIFIER": "kernel", "_UID": "1000",
      "MESSAGE": "zeta-fw ssh rejected: SRC=1.2.3.4 DST=x"}) == [])
e = j("sshd-session", "Failed publickey for zeta from 192.168.1.5 port 22 ssh2: ED25519 SHA256:abc")
check("refused key is not a password guess", e and e[0]["params"]["password"] is False and e[0]["severity"] == "info", e)
e = j("sshd-session", "Accepted password for zeta from 192.168.1.20 port 50022 ssh2")
check("ssh accepted", codes(e) == ["ssh_login"] and e[0]["params"]["local"] is True
      and e[0]["severity"] == "notice", e)
e = j("sshd-session", "Accepted publickey for root from 203.0.113.9 port 50022 ssh2: ED25519 SHA256:x")
check("ssh root accepted is critical", codes(e) == ["ssh_login_root"] and e[0]["severity"] == "critical", e)
e = j("sshd-session", "error: maximum authentication attempts exceeded for invalid user x from 2001:db8::5 port 22 ssh2 [preauth]")
check("ssh maxauth ipv6", codes(e) == ["ssh_maxauth"] and e[0]["params"]["address"] == "2001:db8::5", e)
check("ssh unrelated", j("sshd", "Server listening on 0.0.0.0 port 22.") == [])

# --- local logins
e = j("sddm-helper", "pam_unix(sddm:auth): authentication failure; logname= uid=0 euid=0 tty=/dev/tty1 ruser= rhost=  user=zeta")
check("sddm failure", codes(e) == ["login_failed"] and e[0]["params"]["kind"] == "login"
      and e[0]["params"]["user"] == "zeta", e)
e = j("hyprlock", "pam_unix(hyprlock:auth): authentication failure; logname=zeta uid=1000 euid=1000 tty= ruser= rhost=  user=zeta")
check("lock screen failure", codes(e) == ["login_failed"] and e[0]["severity"] == "notice", e)
e = j("sudo", "pam_unix(sudo:auth): authentication failure; logname=zeta uid=1000 euid=0 tty=/dev/pts/0 ruser=zeta rhost=  user=zeta")
check("sudo pam failure", codes(e) == ["login_failed"] and e[0]["severity"] == "warning", e)
check("sshd pam failure not twice", j("sshd-session", "pam_unix(sshd:auth): authentication failure; logname= uid=0 euid=0 tty=ssh ruser= rhost=203.0.113.7  user=zeta") == [])

# --- root
e = j("sddm-helper", "pam_unix(sddm:session): session opened for user root(uid=0) by root(uid=0)")
check("root desktop login", codes(e) == ["root_login"] and e[0]["severity"] == "warning", e)
check("sudo root session ordinary", j("sudo", "pam_unix(sudo:session): session opened for user root(uid=0) by zeta(uid=1000)") == [])
check("cron root session ordinary", j("CRON", "pam_unix(cron:session): session opened for user root(uid=0) by root(uid=0)") == [])
e = j("su", "pam_unix(su-l:session): session opened for user root(uid=0) by zeta(uid=1000)")
check("su to root", codes(e) == ["root_su"], e)
e = j("sudo", "    zeta : 3 incorrect password attempts ; TTY=pts/0 ; PWD=/home/zeta ; USER=root ; COMMAND=/usr/bin/ls")
check("sudo bad password", codes(e) == ["sudo_failed"] and e[0]["params"]["attempts"] == 3, e)
e = j("sudo", "   guest : user NOT in sudoers ; TTY=pts/1 ; PWD=/home/guest ; USER=root ; COMMAND=/bin/sh")
check("sudo denied", codes(e) == ["sudo_denied"], e)
e = j("sudo", "    zeta : TTY=pts/0 ; PWD=/home/zeta ; USER=root ; COMMAND=/usr/bin/apt update")
check("sudo command is info", codes(e) == ["sudo_command"] and e[0]["severity"] == "info", e)

# --- accounts
e = j("useradd", "new user: name=backdoor, UID=1002, GID=1002, home=/home/backdoor, shell=/bin/bash, from=/dev/pts/0")
check("user created", codes(e) == ["user_created"] and e[0]["params"]["user"] == "backdoor", e)
e = j("usermod", "add 'backdoor' to group 'sudo'")
check("admin granted", codes(e) == ["admin_granted"] and e[0]["severity"] == "warning", e)
e = j("usermod", "add 'zeta' to group 'audio'")
check("ordinary group info", codes(e) == ["group_added"] and e[0]["severity"] == "info", e)
e = j("gpasswd", "user backdoor added by root to group sudo")
check("gpasswd admin", codes(e) == ["admin_granted"], e)
e = j("passwd", "pam_unix(passwd:chauthtok): password changed for root")
check("root password changed", codes(e) == ["password_changed"] and e[0]["severity"] == "warning", e)
e = j("userdel", "delete user 'backdoor'")
check("user deleted", codes(e) == ["user_deleted"], e)

# --- kernel firewall log
e = j("kernel", "zeta-fw ssh rejected: IN=eth0 OUT= MAC=aa SRC=203.0.113.50 DST=10.0.2.15 LEN=60 PROTO=TCP SPT=40000 DPT=22")
check("firewall rejected ssh", codes(e) == ["ssh_rejected"] and e[0]["params"]["address"] == "203.0.113.50", e)

# --- audit
lines = [
    'type=SYSCALL msg=audit(1764150000.123:4242): arch=c00000b7 syscall=56 success=yes exit=3 a0=ffffff9c items=2 ppid=900 pid=901 auid=1000 uid=0 gid=0 euid=0 comm="tee" exe="/usr/bin/tee" subj=unconfined key="zeta-privilege"',
    'type=CWD msg=audit(1764150000.123:4242): cwd="/home/zeta"',
    'type=PATH msg=audit(1764150000.123:4242): item=0 name="/etc/sudoers.d/" inode=1 nametype=PARENT',
    'type=PATH msg=audit(1764150000.123:4242): item=1 name="/etc/sudoers.d/99-evil" inode=2 nametype=CREATE',
]
recs = [W.parse_audit_line(l) for l in lines]
check("audit parse", all(recs) and recs[0][1] == "4242")
e = W.from_audit([(t, f) for t, _s, f in recs])
check("audit sudoers change", codes(e) == ["file_changed"] and e[0]["params"]["path"] == "/etc/sudoers.d/99-evil"
      and e[0]["severity"] == "warning" and e[0]["params"]["program"] == "/usr/bin/tee", e)
dpkg = [(t, dict(f, exe="/usr/bin/dpkg", comm="dpkg") if t == "SYSCALL" else f) for t, _s, f in recs]
check("audit dpkg quiet", W.from_audit(dpkg) == [])
rk = [(t, dict(f, key="zeta-rootkit", exe="/usr/bin/dpkg") if t == "SYSCALL" else f) for t, _s, f in recs]
check("audit rootkit never quiet", codes(W.from_audit(rk)) == ["file_changed"] and W.from_audit(rk)[0]["severity"] == "critical")
check("audit other key ignored", W.from_audit([("SYSCALL", {"key": "something"})]) == [])

mod = [("SYSCALL", {"key": "zeta-modules", "comm": "modprobe", "exe": "/usr/bin/kmod", "auid": "4294967295"})]
check("module loaded by the system is quiet", W.from_audit(mod) == [])
mod = [("SYSCALL", {"key": "zeta-modules", "comm": "insmod", "exe": "/usr/bin/kmod", "auid": "1000"})]
check("module loaded by a user", codes(W.from_audit(mod)) == ["kernel_module"])

# --- snapshots
before = {("tcp", "0.0.0.0", 22, "sshd")}
now = before | {("tcp", "0.0.0.0", 4444, "nc"), ("tcp", "127.0.0.1", 11434, "ollama")}
e = W.new_listeners(before, now)
check("new listener (not loopback)", codes(e) == ["new_listener"] and e[0]["params"]["port"] == 4444, e)
check("process from tmp", W.suspicious_process(10, "/tmp/.x/miner", "zeta")["code"] == "process_from_temp")
check("AppImage mount not suspicious", W.suspicious_process(10, "/tmp/.mount_ObsidiXXXX/obsidian", "zeta") is None)
check("deleted system binary ok", W.suspicious_process(10, "/usr/bin/python3.13 (deleted)", "root") is None)
check("deleted other binary", W.suspicious_process(10, "/home/zeta/.cache/x (deleted)", "zeta")["code"] == "process_deleted_binary")
check("ordinary process", W.suspicious_process(10, "/usr/bin/firefox-esr", "zeta") is None)
check("https not unusual", W.unusual_connection("/usr/bin/firefox-esr", "93.184.216.34", 443, "zeta") is None)
check("lan not unusual", W.unusual_connection("/usr/bin/x", "192.168.1.5", 7000, "zeta") is None)
u = W.unusual_connection("/tmp/x", "203.0.113.1", 6667, "zeta")
check("tmp program unusual port is warning", u and u["severity"] == "warning", u)

print("watch rules: %d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
