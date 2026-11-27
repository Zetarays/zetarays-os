# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA WATCH: what a log line or an audit record means.

Pure functions, no I/O: the daemon (/usr/libexec/zeta-watch) feeds them the
journal entries and audit records it reads, and they return events. The same
code is tested outside the system (tools/tests/test_watch_rules.py) with real
log lines.

An event is a dict:
    {"code": "ssh_failed", "severity": "warning", "category": "ssh",
     "subject": "<what repeats: user@address>", "params": {...}}
The daemon groups repeated events (same code and subject) and writes them
to /var/log/zeta-watch/events.jsonl; the notifier in the session turns the
code and params into a sentence in the user's language.

Severity: "info" (kept in the history only), "notice", "warning",
"critical". Nothing here claims more than the log line says: a failed
password is a failed password, not "an attack".
"""
import ipaddress
import re

SEVERITIES = ("info", "notice", "warning", "critical")

# ---------------------------------------------------------------- journal

# Anchored at the END of the line, user name greedy: sshd logs an invalid
# user name as it was typed, spaces included, so a name like
# "x from 203.0.113.7 port 1" must not become the address (the classic log
# injection). The address is the last "from A port P" of the line.
_TAIL = (r" from (?P<addr>[0-9a-fA-F:.]+) port \d+(?: ssh2)?(?:: [A-Z0-9-]+ SHA256:[A-Za-z0-9+/=]+)?"
         r"(?: \[preauth\])?$")
_SSH_FAILED = re.compile(
    r"^Failed (?P<method>password|publickey|keyboard-interactive/pam) for (?:invalid user )?(?P<user>.*?)" + _TAIL)
_SSH_ACCEPTED = re.compile(r"^Accepted (?P<method>\S+) for (?P<user>.*?)" + _TAIL)
_SSH_MAXAUTH = re.compile(
    r"^(?:error: )?maximum authentication attempts exceeded for (?:invalid user )?(?P<user>.*?)" + _TAIL)
_PAM_FAIL = re.compile(
    r"pam_unix\((?P<service>[^:)]+):auth\): authentication failure;.*?(?:\buser=(?P<user>\S+))?$")
_PAM_SESSION_ROOT = re.compile(
    r"pam_unix\((?P<service>[^:)]+):session\): session opened for user root\(uid=0\) by (?P<by>\S*)")
_SUDO_BAD = re.compile(r"^\s*(?P<user>\S+) : (?P<n>\d+) incorrect password attempts?")
_SUDO_NOT_ALLOWED = re.compile(r"^\s*(?P<user>\S+) : user NOT in sudoers")
_SUDO_CMD = re.compile(r"^\s*(?P<user>\S+) : .*?USER=(?P<as>\S+) ; COMMAND=(?P<cmd>.*)$")
_NEW_USER = re.compile(r"^new user: name=(?P<user>[^,]+), UID=(?P<uid>\d+)")
_DEL_USER = re.compile(r"^delete user '(?P<user>[^']+)'")
_ADD_GROUP_MEMBER = re.compile(
    r"(?:^add '(?P<user1>[^']+)' to group '(?P<group1>[^']+)'"
    r"|^user (?P<user2>\S+) added by \S+ to group (?P<group2>\S+))")
_PASSWORD_CHANGED = re.compile(r"password changed for (?P<user>\S+)")
_FW_SSH_REJECTED = re.compile(r"zeta-fw ssh rejected: .*SRC=(?P<addr>[0-9a-fA-F:.]+)")

ADMIN_GROUPS = ("sudo", "root", "adm", "wheel", "lpadmin", "netdev", "disk", "shadow")
# services where a local password is typed: login screen, lock screen,
# terminal logins, administrator prompts
LOCAL_SERVICES = {"sddm": "login", "login": "login", "hyprlock": "lock", "su": "su", "su-l": "su",
                  "sudo": "sudo", "polkit-1": "admin", "pkexec": "admin"}


# Programs whose log lines only count when they come from root (journald's
# _UID is set by the journal itself, not by the program): any user can write
# a line that claims to be "sshd" or "useradd" with logger.
ROOT_ONLY = {"sshd", "sshd-session", "sudo", "su", "useradd", "userdel", "usermod", "gpasswd",
             "passwd", "chpasswd", "chage", "sddm-helper", "login", "polkitd", "pkexec"}


def trusted(entry):
    """True when the journal entry really comes from where it says."""
    ident = entry.get("SYSLOG_IDENTIFIER") or entry.get("_COMM") or ""
    if ident == "kernel":
        return entry.get("_TRANSPORT") == "kernel"
    if ident in ROOT_ONLY:
        return entry.get("_UID") == "0"
    return True


def ev(code, severity, category, subject, **params):
    return {"code": code, "severity": severity, "category": category,
            "subject": subject, "params": params}


LAN_NETS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10",
    "fc00::/7", "fe80::/10")]


def is_local_address(addr):
    """Loopback or an address of the local networks (the same list as the
    firewall's local_nets sets, plus carrier-grade NAT)."""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in LAN_NETS if n.version == ip.version)


def from_journal(entry):
    """Events for one journal entry (a dict as journalctl -o json prints it)."""
    msg = entry.get("MESSAGE")
    if not isinstance(msg, str) or not trusted(entry):
        return []
    ident = entry.get("SYSLOG_IDENTIFIER") or entry.get("_COMM") or ""
    out = []
    if ident in ("sshd", "sshd-session"):
        m = _SSH_FAILED.match(msg)
        if m:
            # a refused key is not a guessed password: ssh tries every key of
            # the agent in turn, and a user with several keys would be blocked
            # while logging in normally; only passwords count for blocking
            guess = m["method"] != "publickey"
            out.append(ev("ssh_failed", "warning" if guess else "info", "ssh",
                          "%s@%s" % (m["user"][:64], m["addr"]), user=m["user"][:64], address=m["addr"],
                          local=is_local_address(m["addr"]), password=guess))
            return out
        m = _SSH_MAXAUTH.match(msg)
        if m:
            out.append(ev("ssh_maxauth", "info", "ssh", "%s@%s" % (m["user"][:64], m["addr"]),
                          user=m["user"][:64], address=m["addr"], local=is_local_address(m["addr"])))
            return out
        m = _SSH_ACCEPTED.match(msg)
        if m:
            user, addr, method = m["user"], m["addr"], m["method"]
            root = user == "root"
            out.append(ev("ssh_login_root" if root else "ssh_login",
                          "critical" if root else "notice", "ssh",
                          "%s@%s" % (user[:64], addr), user=user[:64], address=addr,
                          method=method, local=is_local_address(addr)))
        return out
    m = _PAM_FAIL.search(msg)
    if m and m["service"] not in ("sshd",):
        kind = LOCAL_SERVICES.get(m["service"], "other")
        user = m["user"] or ""
        out.append(ev("login_failed", "notice" if kind in ("lock", "login") else "warning", "login",
                      "%s:%s" % (m["service"], user), service=m["service"], kind=kind, user=user))
        return out
    m = _PAM_SESSION_ROOT.search(msg)
    if m:
        service = m["service"]
        if service in ("sddm", "login", "sshd"):
            out.append(ev("root_login", "critical" if service == "sshd" else "warning", "root",
                          service, service=service))
        elif service in ("su", "su-l"):
            out.append(ev("root_su", "notice", "root", m["by"] or "?", by=m["by"]))
        # sudo, pkexec, cron and systemd open root sessions all the time:
        # those are ordinary and reported by their own lines
        return out
    if ident == "sudo":
        m = _SUDO_BAD.match(msg)
        if m:
            out.append(ev("sudo_failed", "warning", "root", m["user"], user=m["user"], attempts=int(m["n"])))
            return out
        m = _SUDO_NOT_ALLOWED.match(msg)
        if m:
            out.append(ev("sudo_denied", "warning", "root", m["user"], user=m["user"]))
            return out
        m = _SUDO_CMD.match(msg)
        if m:
            out.append(ev("sudo_command", "info", "root", m["user"], user=m["user"],
                          target=m["as"], command=m["cmd"][:200]))
        return out
    if ident == "useradd":
        m = _NEW_USER.match(msg)
        if m:
            out.append(ev("user_created", "warning", "accounts", m["user"], user=m["user"], uid=int(m["uid"])))
        return out
    if ident == "userdel":
        m = _DEL_USER.match(msg)
        if m:
            out.append(ev("user_deleted", "notice", "accounts", m["user"], user=m["user"]))
        return out
    if ident in ("usermod", "gpasswd", "useradd"):
        m = _ADD_GROUP_MEMBER.search(msg)
        if m:
            user, group = m["user1"] or m["user2"], m["group1"] or m["group2"]
            admin = group in ADMIN_GROUPS
            out.append(ev("admin_granted" if admin else "group_added", "warning" if admin else "info",
                          "accounts", "%s:%s" % (user, group), user=user, group=group))
        return out
    if ident in ("passwd", "chpasswd", "chage") or "pam_unix(passwd:chauthtok)" in msg:
        m = _PASSWORD_CHANGED.search(msg)
        if m:
            root = m["user"] == "root"
            out.append(ev("password_changed", "warning" if root else "notice", "accounts",
                          m["user"], user=m["user"]))
        return out
    if ident == "kernel":
        m = _FW_SSH_REJECTED.search(msg)
        if m:
            out.append(ev("ssh_rejected", "info", "network", m["addr"], address=m["addr"]))
    return out


# ---------------------------------------------------------------- audit log

_AUDIT_HEAD = re.compile(r"^type=(?P<type>\S+) msg=audit\((?P<stamp>[\d.]+):(?P<serial>\d+)\): (?P<rest>.*)$")
_AUDIT_FIELD = re.compile(r'(\w+)=("(?:[^"]*)"|\S+)')

# programs whose writes to these files are the normal way to change them:
# package updates (and their scripts) and the account tools, already
# reported from the journal with a clearer message
QUIET_EXE = ("/usr/bin/dpkg", "/usr/bin/apt", "/usr/bin/apt-get", "/usr/lib/apt/methods/",
             "/usr/sbin/useradd", "/usr/sbin/usermod", "/usr/sbin/userdel", "/usr/sbin/groupadd",
             "/usr/sbin/groupdel", "/usr/sbin/groupmod", "/usr/bin/gpasswd", "/usr/bin/passwd",
             "/usr/sbin/chpasswd", "/usr/bin/chage", "/usr/sbin/adduser", "/usr/sbin/deluser",
             "/usr/bin/unattended-upgrade", "/usr/sbin/pwconv", "/usr/sbin/grpconv")
QUIET_COMM = ("dpkg", "apt", "apt-get", "unattended-upgr", "useradd", "usermod", "userdel",
              "groupadd", "gpasswd", "passwd", "chpasswd", "adduser", "deluser", "systemd",
              "systemctl", "packagekitd", "aptd")

KEY_SEVERITY = {"zeta-rootkit": "critical", "zeta-privilege": "warning", "zeta-ssh": "warning",
                "zeta-persistence": "warning", "zeta-login": "warning", "zeta-accounts": "warning",
                "zeta-modules": "notice"}


def audit_fields(rest):
    out = {}
    for k, v in _AUDIT_FIELD.findall(rest):
        out[k] = v[1:-1] if v.startswith('"') else v
    return out


def parse_audit_line(line):
    """(type, serial, fields) of one audit.log line, or None."""
    m = _AUDIT_HEAD.match(line.strip())
    if not m:
        return None
    return m["type"], m["serial"], audit_fields(m["rest"])


def from_audit(records):
    """Events for one audit event: records is the list of (type, fields)
    sharing a serial number (SYSCALL, CWD, PATH..., PROCTITLE)."""
    syscall = next((f for t, f in records if t == "SYSCALL"), None)
    if not syscall:
        return []
    key = syscall.get("key", "")
    if key not in KEY_SEVERITY:
        return []
    exe, comm = syscall.get("exe", ""), syscall.get("comm", "")
    if key != "zeta-rootkit" and (exe.startswith(QUIET_EXE) or comm in QUIET_COMM):
        return []
    if key == "zeta-modules":
        # modules loaded by the system itself (udev, systemd at boot, a USB
        # device plugged in) have no login user (auid unset): only a module
        # loaded by someone who logged in is "by hand"
        if syscall.get("auid", "") in ("", "4294967295", "-1", "unset"):
            return []
        return [ev("kernel_module", "notice", "files", comm or exe, program=exe or comm)]
    paths = [f.get("name", "") for t, f in records if t == "PATH"
             and f.get("nametype") not in ("PARENT",) and f.get("name") not in ("", "(null)")]
    if not paths:
        return []
    path = paths[-1]
    return [ev("file_changed", KEY_SEVERITY[key], "files", "%s:%s" % (key, path),
               path=path, program=exe or comm, kind=key[5:], uid=syscall.get("auid", ""))]


# ---------------------------------------------------------------- snapshots

COMMON_REMOTE_PORTS = {22, 53, 80, 123, 143, 443, 465, 587, 853, 993, 995, 5222, 5228, 8080, 8443,
                       11434, 3478, 19302, 5353, 445, 139, 631, 53317, 9418, 21, 990, 25, 110}
TEMP_PLACES = ("/tmp/", "/var/tmp/", "/dev/shm/", "/run/user/")


def new_listeners(before, now):
    """Listening sockets (proto, address, port, program) present now and not
    before, reachable from other computers (not loopback)."""
    out = []
    for item in sorted(set(now) - set(before)):
        proto, addr, port, program = item
        if addr.startswith("127.") or addr in ("::1", "[::1]"):
            continue
        out.append(ev("new_listener", "warning", "network", "%s/%s" % (proto, port),
                      proto=proto, port=port, address=addr, program=program))
    return out


def suspicious_process(pid, exe, user):
    """A program running from a temporary folder, or whose file was
    deleted while it runs: both are common with malware (and rare
    otherwise)."""
    if exe.endswith(" (deleted)"):
        base = exe[:-10]
        # updated libraries/programs still running after an upgrade are
        # normal: only programs outside the system folders are reported
        if base.startswith(("/usr/", "/opt/", "/snap/", "/var/lib/flatpak/")):
            return None
        return ev("process_deleted_binary", "warning", "processes", base, program=base, pid=pid, user=user)
    if exe.startswith(TEMP_PLACES) and not exe.startswith("/tmp/.mount_"):
        # /tmp/.mount_*: where every AppImage runs from (FUSE), not a dropped file
        return ev("process_from_temp", "warning", "processes", exe, program=exe, pid=pid, user=user)
    return None


def unusual_connection(program, remote_addr, remote_port, user):
    if is_local_address(remote_addr) or remote_port in COMMON_REMOTE_PORTS:
        return None
    severity = "warning" if program.startswith(TEMP_PLACES) else "info"
    return ev("unusual_connection", severity, "network", "%s>%s" % (program, remote_port),
              program=program, address=remote_addr, port=remote_port, user=user)
