#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS in-place upgrade (runs on the installed system, as root).

Started by the .run file (tools/upgrade/stub.sh) after it has checked and
unpacked its payload into a temporary folder:

    python3 -I zeta_upgrade.py --bundle DIR [--dry-run] [--yes] [--gui] [--lang it]

Steps (each one stops before changing anything if something is wrong):
  1. checks: ZETA RAYS FROM (or TO, re-run), architecture, not the live
     session, free space, network, no other package manager running
  2. backup of every file that will be replaced or removed into
     /var/backups/zeta-rays-FROM-DATE/ (+ the list of new files and
     rollback.sh, which puts everything back)
  3. apt-get update, the packages new in TO, the pending Debian updates
  4. the ZETA RAYS files (/etc files changed by the user are kept: the new
     version goes next to them as FILE.dpkg-dist), the Ollama runtime, the
     new version number
  5. what the build hooks do for those files: services, translations,
     schemas, icon and menu caches, precompiled Python, legal documents
  6. summary, log in /var/log/zeta-rays-upgrade.log, restart

If step 4 fails, the ZETA RAYS files are put back at once (packages
installed by apt stay). Running it again is safe: unchanged files are
skipped and an interrupted run resumes with the same backup.

Test options (no root needed, nothing outside DIR is touched):
    --root DIR     treat DIR as the system root; apt, systemctl and the
                   other system commands are only printed
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time

# ------------------------------------------------------------ texts

IT = {}
LANG = "en"


def _(text):
    """The user's language (English or Italian, from the bundle's table)."""
    if LANG == "it":
        return IT.get(text, text)
    return text


# ------------------------------------------------------------ helpers

class Failure(Exception):
    """A step failed: the message is already translated."""


class Ctx:
    root = "/"
    test = False
    dry = False
    log = None
    bundle = ""
    m = {}


C = Ctx()


def R(path):
    """A system path inside the root (the real one, or the test folder)."""
    if C.root == "/":
        return path
    return os.path.join(C.root, path.lstrip("/"))


def say(text="", detail=""):
    line = text + (" " + detail if detail else "")
    try:
        print(line, flush=True)
    except OSError:          # the terminal window was closed: the log goes on
        pass
    log_line(line)


def log_line(line):
    if C.log:
        C.log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
        C.log.flush()


def head(n, text):
    say()
    say("== %s. %s" % (n, text))


def file_sha(path):
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode):
        return hashlib.sha256(("link:" + os.readlink(path)).encode()).hexdigest()
    if not stat.S_ISREG(st.st_mode):
        return "not-a-file"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(cmd, check=False, quiet=False, env=None, stdin=None):
    """Run a system command, its output shown and logged. In test mode
    (--root) it is only printed. Returns the exit code."""
    shown = " ".join(cmd)
    if C.test:
        log_line("[test mode, not run] " + shown)
        if not quiet:
            print("   [test mode, not run] " + shown)
        return 0
    log_line("$ " + shown)
    e = dict(os.environ, LC_ALL="C.UTF-8") if env is None else env
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=e,
                             stdin=stdin if stdin is not None else subprocess.DEVNULL,
                             text=True, errors="replace")
    except OSError as err:
        log_line("  %s" % err)
        if check:
            raise Failure(_("Command failed: {cmd}").format(cmd=shown))
        return 127
    for line in p.stdout:
        line = line.rstrip("\n")
        log_line("  " + line)
        if not quiet:
            print("   " + line, flush=True)
    rc = p.wait()
    if rc != 0:
        log_line("  exit code %d" % rc)
        if check:
            raise Failure(_("Command failed: {cmd}").format(cmd=shown))
    return rc


def capture(cmd):
    """Output of a read-only query ("" in test mode or when it fails)."""
    if C.test:
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                              env=dict(os.environ, LC_ALL="C.UTF-8")).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def os_release():
    data = {}
    try:
        with open(R("/etc/os-release"), encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    data[k] = v.strip().strip('"')
    except OSError:
        pass
    return data


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return str(n)


# ------------------------------------------------------------ 1. checks

def checks(args):
    m = C.m
    problems = []
    rel = os_release()
    have = rel.get("VERSION_ID", "")
    if rel.get("ID") != "zeta":
        problems.append(_("This is not ZETA RAYS OS (/etc/os-release)."))
    elif have not in (m["from"], m["to"]):
        problems.append(_("This upgrade is for ZETA RAYS {old}: this system is {have}.").format(
            old=m["from"], have=have or "?"))
    say("   " + _("System: ZETA RAYS {version}").format(version=have or "?"))

    arch = capture(["dpkg", "--print-architecture"]).strip() or args.arch or m["arch"]
    if arch != m["arch"]:
        problems.append(_("This file is for {want} computers, this one is {have}: use the {have} file.").format(
            want=m["arch"], have=arch))
    say("   " + _("Architecture: {arch}").format(arch=arch))

    if os.path.isdir(R("/run/live/medium")) or "boot=live" in _read(R("/proc/cmdline")):
        problems.append(_("This is the live session (USB stick): install ZETA RAYS first, or upgrade the installed system."))

    need = m["space_needed"]
    free = shutil.disk_usage(R("/") if os.path.exists(R("/")) else "/").free
    var_free = shutil.disk_usage(R("/var")).free if os.path.isdir(R("/var")) else free
    say("   " + _("Free space: {free} (needed about {need})").format(free=human(min(free, var_free)), need=human(need)))
    if min(free, var_free) < need:
        problems.append(_("Not enough free space: {need} needed, {free} free.").format(
            need=human(need), free=human(min(free, var_free))))

    if not C.test and not args.no_apt:
        if network_ok():
            say("   " + _("Network: the package servers answer"))
        else:
            problems.append(_("No connection to the package servers (deb.debian.org): connect to the internet and try again."))
        busy = package_manager_busy()
        if busy:
            problems.append(_("Another program is installing software ({what}): wait until it finishes.").format(what=busy))
        audit = capture(["dpkg", "--audit"]).strip()
        if audit:
            say("   " + _("Note: some packages are not fully configured; the upgrade completes them first."))
            log_line(audit)
    elif C.test:
        say("   " + _("Test mode: network and package checks skipped"))
    return problems


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def network_ok():
    hosts = set()
    for path in ("/etc/apt/sources.list.d/debian.sources", "/etc/apt/sources.list"):
        for m in re.finditer(r"https?://([A-Za-z0-9.-]+)", _read(R(path))):
            hosts.add(m.group(1))
    hosts = sorted(hosts) or ["deb.debian.org"]
    for host in hosts[:3]:
        try:
            with socket.create_connection((host, 80), timeout=8):
                return True
        except OSError:
            continue
    return False


def package_manager_busy():
    for lock in ("/var/lib/dpkg/lock-frontend", "/var/lib/dpkg/lock", "/var/lib/apt/lists/lock"):
        try:
            fd = os.open(lock, os.O_RDWR)
        except OSError:
            continue
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.lockf(fd, fcntl.LOCK_UN)
        except OSError:
            return lock
        finally:
            os.close(fd)
    return ""


# ------------------------------------------------------------ plan

def plan_files():
    """What happens to each file: same, new, replace, conflict, kept-deleted,
    invalid; and to each file ZETA RAYS no longer ships: remove, keep."""
    actions = {}
    for path, e in sorted(C.m["files"].items()):
        cur = file_sha(R(path))
        if cur == e["sha256"]:
            act = "same"
        elif cur == "not-a-file" or (os.path.isdir(R(path)) and not os.path.islink(R(path))):
            act = "invalid"
        elif e["policy"] in ("zeta", "skel"):
            act = "new" if cur is None else "replace"
        else:
            # /etc: like dpkg with a conffile. When the release did not
            # change the file, whatever this computer has stays as it is.
            unchanged = e["sha256"] in e.get("old", [])
            if cur is None:
                act = "new" if not e.get("shipped_before") else ("keep" if unchanged else "kept-deleted")
            elif cur in e.get("old", []):
                act = "replace"
            else:
                act = "keep" if unchanged else "conflict"
        actions[path] = act
    removals = {}
    for path, e in sorted(C.m.get("remove", {}).items()):
        cur = file_sha(R(path))
        if cur is None:
            continue
        if e["policy"] == "zeta" or cur in e.get("old", []):
            removals[path] = "remove"
        else:
            removals[path] = "keep"
    return actions, removals


def plan_packages():
    """New packages of the release not installed yet."""
    want = C.m["packages"]["new"]
    if C.test or not want:
        return list(want), []
    out = capture(["dpkg-query", "-W", "-f=${Package} ${db:Status-Status}\n"] + want)
    installed = {l.split()[0] for l in out.splitlines() if l.endswith(" installed")}
    missing = [p for p in want if p not in installed]
    return missing, sorted(installed)


def plan_ollama():
    o = C.m.get("ollama")
    if not o:
        return None
    cur = file_sha(R("/usr/bin/ollama"))
    return None if cur == o["binary_sha256"] else o


def plan_hyprland():
    h = C.m.get("hyprland")
    if not h:
        return None
    cur = capture(["dpkg-query", "-W", "-f=${Version}", "hyprland"]).strip()
    return None if cur == h["version"] else h


# ------------------------------------------------------------ output of the plan

def show_plan(actions, removals, missing, already, ollama, hypr, upgradable):
    m = C.m
    count = {}
    for a in actions.values():
        count[a] = count.get(a, 0) + 1
    say("   " + _("ZETA RAYS files: {new} new, {changed} changed, {same} already up to date").format(
        new=count.get("new", 0), changed=count.get("replace", 0), same=count.get("same", 0)))
    for path, a in actions.items():
        if a == "new":
            log_line("   new      " + path)
        elif a == "replace":
            log_line("   replace  " + path)
    if C.dry:
        for path, a in actions.items():
            if a in ("new", "replace"):
                print("     %-8s %s" % ("+" if a == "new" else "~", path))
    conflicts = [p for p, a in actions.items() if a == "conflict"]
    if conflicts:
        say("   " + _("Settings files changed on this computer: kept as they are, the new version is saved next to them (.dpkg-dist):"))
        for p in conflicts:
            say("     " + p)
    for p, a in actions.items():
        if a == "kept-deleted":
            say("   " + _("Not restored (deleted on this computer): {path}").format(path=p))
        elif a == "invalid":
            say("   " + _("Skipped (a folder or special file is in the way): {path}").format(path=p))
    for p, a in removals.items():
        if a == "remove":
            say("   " + _("No longer part of ZETA RAYS, removed (a copy is kept): {path}").format(path=p))
        else:
            say("   " + _("No longer part of ZETA RAYS, kept because it was changed: {path}").format(path=p))
    if missing:
        say("   " + _("New packages: {names}").format(names=" ".join(missing)))
    else:
        say("   " + _("New packages: none missing"))
    if upgradable is not None:
        say("   " + _("Pending Debian updates: {n}").format(n=upgradable))
    if hypr:
        say("   " + _("Hyprland: {version} with title bars rebuilt").format(version=hypr["version"]))
    if ollama:
        say("   " + _("AI engine (Ollama): updated to the version of ZETA RAYS {version}").format(version=m["to"]))
    else:
        say("   " + _("AI engine (Ollama): already up to date"))
    units = m.get("units", {})
    if any(units.get(k) for k in units):
        say("   " + _("Services: {list}").format(list=", ".join(
            "%s %s" % (k, u) for k in sorted(units) for u in units[k])))
    say("   " + _("Version: {old} -> {new}").format(old=os_release().get("VERSION_ID", "?"), new=m["to"]))


def count_upgradable():
    if C.test:
        return None
    out = capture(["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"])
    return sum(1 for l in out.splitlines() if l.startswith("Inst "))


# ------------------------------------------------------------ state and backup

STATE_DIR = "/var/lib/zeta/upgrade-%s"


def state_path():
    return R(STATE_DIR % C.m["to"] + "/state.json")


def load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(**kw):
    s = load_state()
    s.update(kw)
    os.makedirs(os.path.dirname(state_path()), exist_ok=True)
    tmp = state_path() + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, state_path())


class Backup:
    def __init__(self, path):
        self.dir = path            # system path (without the test root)
        self.real = R(path)
        os.makedirs(os.path.join(self.real, "files"), exist_ok=True)
        os.chmod(self.real, 0o700)
        self.replaced = self._list("replaced.txt")
        self.created = self._list("created.txt")

    def _list(self, name):
        try:
            with open(os.path.join(self.real, name), encoding="utf-8") as f:
                return [l.rstrip("\n") for l in f if l.strip()]
        except OSError:
            return []

    def _write(self, name, items):
        with open(os.path.join(self.real, name), "w", encoding="utf-8") as f:
            f.write("".join(p + "\n" for p in items))

    def save(self, path):
        """Keep a copy of a system file before it changes (only once: a
        resumed run never overwrites the copy of the original)."""
        if path in self.replaced or path in self.created:
            return
        src = R(path)
        if os.path.lexists(src):
            dest = os.path.join(self.real, "files", path.lstrip("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            # a run interrupted before flush() left a copy but no list entry:
            # never symlink onto it (FileExistsError) or copy through it
            if os.path.lexists(dest):
                os.unlink(dest)
            if os.path.islink(src):
                os.symlink(os.readlink(src), dest)
            else:
                shutil.copy2(src, dest)
            self.replaced.append(path)
        else:
            self.created.append(path)

    def flush(self):
        self._write("replaced.txt", self.replaced)
        self._write("created.txt", self.created)


def new_backup():
    s = load_state()
    if s.get("status") in ("in-progress", "failed") and s.get("backup") and os.path.isdir(R(s["backup"])):
        say("   " + _("Resuming the interrupted upgrade, backup: {dir}").format(dir=s["backup"]))
        return Backup(s["backup"])
    ver = os_release().get("VERSION_ID", C.m["from"])
    base = "/var/backups/zeta-rays-%s-%s" % (ver, time.strftime("%Y%m%d-%H%M%S"))
    return Backup(base)


ROLLBACK_SH = r'''#!/bin/bash
# ZETA RAYS: puts back the files that the upgrade to @TO@ replaced, from this
# folder (made by the upgrade on @DATE@). Packages that apt installed or
# updated stay installed: they are Debian packages and work with both.
#
#   sudo bash @DIR@/rollback.sh
#
# After it: log out (or restart) so that the desktop uses the old files.
set -u
B="$(cd "$(dirname "$0")" && pwd)"
ROOT="${ZETA_ROOT:-@ROOT@}"
ROOT="${ROOT%/}"
if [ -z "$ROOT" ] && [ "$(id -u)" != 0 ]; then
    echo "Administrator rights needed: sudo bash $0"
    exit 1
fi
sys() { if [ -z "$ROOT" ]; then "$@"; else echo "[test mode, not run] $*"; fi; }
echo "ZETA RAYS: restoring the files saved in $B"
while IFS= read -r p; do
    [ -n "$p" ] && rm -f -- "$ROOT$p"
done < "$B/created.txt"
while IFS= read -r p; do
    [ -n "$p" ] || continue
    mkdir -p -- "$(dirname -- "$ROOT$p")"
    rm -f -- "$ROOT$p"
    cp -a -- "$B/files$p" "$ROOT$p" || echo "   could not restore $p"
done < "$B/replaced.txt"
if [ -d "$B/ollama/lib" ] || [ -e "$B/ollama/bin/ollama" ]; then
    sys systemctl stop ollama.service
    if [ -d "$B/ollama/lib" ]; then rm -rf -- "$ROOT/usr/lib/ollama"; cp -a -- "$B/ollama/lib" "$ROOT/usr/lib/ollama"; fi
    [ -e "$B/ollama/bin/ollama" ] && cp -a -- "$B/ollama/bin/ollama" "$ROOT/usr/bin/ollama"
fi
if [ -s "$B/units.txt" ]; then
    while read -r verb unit; do
        case "$verb" in
            enable) sys systemctl disable "$unit" ;;
            disable) sys systemctl enable "$unit" ;;
            global-enable) sys systemctl --global disable "$unit" ;;
            global-disable) sys systemctl --global enable "$unit" ;;
        esac
    done < "$B/units.txt"
fi
sys systemctl daemon-reload
sys glib-compile-schemas /usr/share/glib-2.0/schemas
sys gtk-update-icon-cache -q -f /usr/share/icons/zeta
sys update-desktop-database -q /usr/share/applications
sys python3 -m compileall -q -j0 /usr/lib/zeta
if [ -d "$B/ollama" ]; then sys systemctl try-restart ollama.service; sys systemctl start ollama.service; fi
S="$ROOT@STATEDIR@/state.json"
if [ -f "$S" ]; then
    python3 - "$S" <<'PY'
import json, sys
p = sys.argv[1]
s = json.load(open(p))
s["status"] = "rolled-back"
json.dump(s, open(p, "w"), indent=1)
PY
fi
echo "ZETA RAYS: files restored. Version now: $(. "$ROOT/etc/os-release" 2>/dev/null; echo "${VERSION_ID:-?}")"
echo "Log out or restart the computer to finish."
'''


def write_rollback(bk):
    text = (ROLLBACK_SH.replace("@TO@", C.m["to"]).replace("@DATE@", time.strftime("%Y-%m-%d %H:%M"))
            .replace("@DIR@", bk.dir).replace("@ROOT@", "" if C.root == "/" else C.root.rstrip("/"))
            .replace("@STATEDIR@", STATE_DIR % C.m["to"]))
    p = os.path.join(bk.real, "rollback.sh")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(p, 0o700)
    with open(os.path.join(bk.real, "info.txt"), "w", encoding="utf-8") as f:
        f.write("ZETA RAYS upgrade %s -> %s (%s), %s\n" % (
            os_release().get("VERSION_ID", "?"), C.m["to"], C.m["arch"], time.strftime("%Y-%m-%d %H:%M:%S")))
        f.write("replaced.txt: files changed or removed (originals in files/)\n")
        f.write("created.txt: files that did not exist before\n")
        f.write("rollback.sh: puts everything back (packages stay)\n")


VERSION_FILES = ("/usr/lib/os-release", "/etc/os-release", "/etc/issue", "/etc/issue.net", "/etc/motd",
                 "/usr/share/zeta/version")


def make_backup(bk, actions, removals, ollama):
    for path, a in actions.items():
        if a in ("new", "replace"):
            bk.save(path)
        elif a == "conflict":
            bk.save(path + ".dpkg-dist")
    for path, a in removals.items():
        if a == "remove":
            bk.save(path)
    for path in VERSION_FILES:
        if os.path.lexists(R(path)) and not os.path.islink(R(path)):
            bk.save(path)
    bk.flush()
    write_rollback(bk)
    if not C.test:
        with open(os.path.join(bk.real, "packages-before.txt"), "w") as f:
            f.write(capture(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${db:Status-Status}\n"]))
        with open(os.path.join(bk.real, "apt-manual-before.txt"), "w") as f:
            f.write(capture(["apt-mark", "showmanual"]))


# ------------------------------------------------------------ 3. packages

APT_ENV = None


def apt(*args):
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", APT_LISTCHANGES_FRONTEND="none",
               NEEDRESTART_MODE="l", LC_ALL="C.UTF-8")
    base = ["apt-get", "-y", "-q", "-o", "Dpkg::Options::=--force-confdef",
            "-o", "Dpkg::Options::=--force-confold", "-o", "Dpkg::Use-Pty=0"]
    return run(base + list(args), env=env)


def raspi_firmware_step():
    """2.5 arm64 images carry raspi-firmware (live-build installs every
    firmware package). On a computer that is not a Raspberry Pi /boot/firmware
    is not a mounted partition, its initramfs hook exits with an error and
    every kernel update fails. Nothing depends on it: remove it."""
    if C.test:
        return
    state = capture(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", "raspi-firmware"]).strip()
    if state[:1] in ("i", "h") and not os.path.ismount("/boot/firmware"):
        say(_("Removing the Raspberry Pi firmware (not used here, it blocked kernel updates)"))
        run(["dpkg", "--purge", "raspi-firmware"], env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))


def packages_step(missing, hypr):
    raspi_firmware_step()
    if not C.test and capture(["dpkg", "--audit"]).strip():
        run(["dpkg", "--configure", "-a"], env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
    if apt("update") != 0:
        raise Failure(_("The package lists could not be updated (network or package servers): nothing was changed."))
    for what in (["install", "--no-install-recommends"] + missing if missing else None, ["dist-upgrade"]):
        gone = removed_by(what) if what else []
        if gone:
            raise Failure(_("Installing the packages would remove {names}: stopping, the ZETA RAYS files were not changed.").format(
                names=" ".join(gone)))
    if missing:
        if apt("install", "--no-install-recommends", *missing) != 0:
            raise Failure(_("The new packages could not be installed: the ZETA RAYS files were not changed."))
    if apt("dist-upgrade") != 0:
        raise Failure(_("The Debian updates could not be installed: the ZETA RAYS files were not changed."))
    if hypr:
        hyprland_step(hypr)
    if not C.test:
        v = capture(["dpkg-query", "-W", "-f=${Version}", "hyprland"]).strip()
        if v and "+zeta" not in v:
            raise Failure(_("Hyprland {version} was installed without the ZETA RAYS fixes: stopping.").format(version=v))


def removed_by(args):
    """Packages apt would remove for this command (simulated, nothing done)."""
    out = capture(["apt-get", "-s", "-o", "Debug::NoLocking=1"] + args)
    return sorted({l.split()[1] for l in out.splitlines() if l.startswith("Remv ")})


def hyprland_step(h):
    """Replays hooks 0350 (patched Hyprland) and 0400 (title bars)."""
    dest = R("/usr/share/zeta/hyprland-patched")
    os.makedirs(dest, exist_ok=True)
    for deb in h["debs"]:
        shutil.copy2(os.path.join(C.bundle, "hyprland", deb), dest)
    run(["apt-mark", "unhold", "hyprland"])
    for hook in ("0350-zeta-hyprland-patched.hook.chroot", "0400-zeta-hyprbars.hook.chroot"):
        if run(["sh", os.path.join(C.bundle, "hooks", hook)]) != 0:
            raise Failure(_("Hyprland could not be updated ({step}): the ZETA RAYS files were not changed.").format(step=hook))
    shutil.rmtree(dest, ignore_errors=True)
    if not C.test and not os.path.exists("/usr/lib/zeta/hypr/hyprbars.so"):
        raise Failure(_("The window title bars could not be rebuilt for the new Hyprland."))


# ------------------------------------------------------------ 4. files

def validate(path, data):
    """Checks a new system file before it is installed ("" when fine)."""
    if C.test:
        return ""
    tmp = "/run/zeta-upgrade-check"
    checker = None
    if path.startswith("/etc/sudoers.d/"):
        checker = ["visudo", "-c", "-q", "-f", tmp]
    elif path == "/etc/nftables.conf" and shutil.which("nft"):
        checker = ["nft", "-c", "-f", tmp]
    if not checker:
        return ""
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        r = subprocess.run(checker, capture_output=True, text=True)
        return "" if r.returncode == 0 else (r.stderr or r.stdout).strip()[:300]
    finally:
        os.unlink(tmp)


def install_entry(path, e, data, dest_path=None):
    dest = R(dest_path or path)
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    tmp = dest + ".zeta-new"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    if e["type"] == "link":
        os.symlink(e["target"], tmp)
    else:
        with open(tmp, "wb") as f:
            f.write(data)
        os.chmod(tmp, e["mode"] if not dest_path else 0o644)
        if not C.test:
            os.chown(tmp, 0, 0)
    os.replace(tmp, dest)


def files_step(bk, actions, removals, fail_at):
    done = 0
    conflicts, skipped = [], []
    with tarfile.open(os.path.join(C.bundle, "files.tar.gz")) as tar:
        members = {"/" + m.name: m for m in tar.getmembers()}
        for path, a in actions.items():
            if a not in ("new", "replace", "conflict"):
                continue
            e = C.m["files"][path]
            data = b""
            if e["type"] == "file":
                data = tar.extractfile(members[path]).read()
                if hashlib.sha256(data).hexdigest() != e["sha256"]:
                    raise Failure(_("The upgrade file is damaged ({path}): download it again.").format(path=path))
                problem = validate(path, data)
                if problem:
                    say("   " + _("Not installed, it does not pass the check: {path}").format(path=path))
                    log_line(problem)
                    skipped.append(path)
                    continue
            if a == "conflict":
                install_entry(path, e, data, dest_path=path + ".dpkg-dist")
                conflicts.append(path)
            else:
                install_entry(path, e, data)
            done += 1
            if fail_at and done >= fail_at:
                raise Failure("test failure after %d files (ZETA_UPGRADE_FAIL_AT)" % done)
    for path, a in removals.items():
        if a == "remove" and os.path.lexists(R(path)):
            os.unlink(R(path))
    say("   " + _("{n} files installed").format(n=done))
    return conflicts, skipped


def ollama_step(bk, o):
    was_active = not C.test and capture(["systemctl", "is-active", "ollama.service"]).strip() == "active"
    run(["systemctl", "stop", "ollama.service"], quiet=True)
    keep = os.path.join(bk.real, "ollama")
    os.makedirs(os.path.join(keep, "bin"), exist_ok=True)
    if os.path.isdir(R("/usr/lib/ollama")) and not os.path.exists(os.path.join(keep, "lib")):
        shutil.move(R("/usr/lib/ollama"), os.path.join(keep, "lib"))
    else:
        shutil.rmtree(R("/usr/lib/ollama"), ignore_errors=True)
    if os.path.exists(R("/usr/bin/ollama")) and not os.path.exists(os.path.join(keep, "bin", "ollama")):
        shutil.copy2(R("/usr/bin/ollama"), os.path.join(keep, "bin", "ollama"))
    with tarfile.open(os.path.join(C.bundle, o["archive"])) as tar:
        for member in tar.getmembers():
            if not (member.name.startswith(("bin/", "lib/ollama/")) or member.name in ("bin", "lib", "lib/ollama")):
                raise Failure(_("The upgrade file is damaged ({path}): download it again.").format(path=member.name))
        os.makedirs(R("/usr"), exist_ok=True)
        if os.path.exists(R("/usr/bin/ollama")):
            os.unlink(R("/usr/bin/ollama"))
        tar.extractall(R("/usr"), filter="tar")
    if file_sha(R("/usr/bin/ollama")) != o["binary_sha256"]:
        raise Failure(_("The AI engine was not installed correctly."))
    if not C.test:
        os.chown(R("/usr/bin/ollama"), 0, 0)
        version = capture(["/usr/bin/ollama", "--version"]).strip().splitlines()
        say("   " + _("AI engine: {version}").format(version=(version or ["?"])[-1]))
    return was_active


def write_version():
    m = C.m
    old = os_release().get("VERSION_ID", m["from"])
    for path in ("/usr/lib/os-release", "/etc/os-release"):
        p = R(path)
        if not os.path.exists(p) or os.path.islink(p):
            continue
        text = _read(p)
        text = re.sub(r'^PRETTY_NAME=.*$', 'PRETTY_NAME="ZETA RAYS OS %s"' % m["to"], text, flags=re.M)
        text = re.sub(r'^VERSION_ID=.*$', 'VERSION_ID="%s"' % m["to"], text, flags=re.M)
        text = re.sub(r'^VERSION=.*$', 'VERSION="%s"' % m["to"], text, flags=re.M)
        _write_text(p, text)
    for path in ("/etc/issue", "/etc/issue.net", "/etc/motd"):
        p = R(path)
        text = _read(p)
        if text and ("ZETA RAYS OS " + old) in text:
            _write_text(p, text.replace("ZETA RAYS OS " + old, "ZETA RAYS OS " + m["to"]))
    # Left behind by the image build (the hooks read it); keep it in step so
    # nothing ever finds the old number there.
    p = R("/usr/share/zeta/version")
    if os.path.isfile(p) and not os.path.islink(p):
        _write_text(p, m["to"] + "\n")


def _write_text(p, text):
    st = os.stat(p)
    tmp = p + ".zeta-new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, stat.S_IMODE(st.st_mode))
    os.replace(tmp, p)


def units_step(bk):
    done = []
    for verb in ("enable", "disable", "global-enable", "global-disable"):
        for unit in C.m.get("units", {}).get(verb, []):
            cmd = ["systemctl"] + (["--global"] if verb.startswith("global") else []) + [verb.split("-")[-1], unit]
            if run(cmd, quiet=True) == 0:
                done.append("%s %s" % (verb, unit))
    with open(os.path.join(bk.real, "units.txt"), "a", encoding="utf-8") as f:
        f.write("".join(x + "\n" for x in done))


def rollback(bk):
    """Puts back the files saved before the change (same as rollback.sh)."""
    say(_("Restoring the previous ZETA RAYS files..."))
    for path in bk.created:
        try:
            if os.path.lexists(R(path)) and not os.path.isdir(R(path)):
                os.unlink(R(path))
        except OSError as e:
            log_line("rollback: %s: %s" % (path, e))
    for path in bk.replaced:
        src = os.path.join(bk.real, "files", path.lstrip("/"))
        try:
            if os.path.lexists(R(path)) and not os.path.isdir(R(path)):
                os.unlink(R(path))
            os.makedirs(os.path.dirname(R(path)), exist_ok=True)
            if os.path.islink(src):
                os.symlink(os.readlink(src), R(path))
            else:
                shutil.copy2(src, R(path))
        except OSError as e:
            log_line("rollback: %s: %s" % (path, e))
    keep = os.path.join(bk.real, "ollama")
    if os.path.isdir(os.path.join(keep, "lib")):
        shutil.rmtree(R("/usr/lib/ollama"), ignore_errors=True)
        shutil.copytree(os.path.join(keep, "lib"), R("/usr/lib/ollama"), symlinks=True)
    if os.path.exists(os.path.join(keep, "bin", "ollama")):
        shutil.copy2(os.path.join(keep, "bin", "ollama"), R("/usr/bin/ollama"))
    run(["systemctl", "daemon-reload"], quiet=True)
    run(["systemctl", "try-restart", "ollama.service"], quiet=True)
    caches(changed=set(), quiet=True)
    save_state(status="rolled-back")


# ------------------------------------------------------------ 5. what the hooks do

def caches(changed, quiet=False):
    """Schemas, icon caches, menus, precompiled Python (hooks 0100, 0500, 9996)."""
    run(["glib-compile-schemas", "/usr/share/glib-2.0/schemas"], quiet=quiet)
    themes = {"/usr/share/icons/zeta"}
    for p in changed:
        mm = re.match(r"(/usr/share/icons/[^/]+)/", p)
        if mm:
            themes.add(mm.group(1))
    for t in sorted(themes):
        if os.path.exists(R(t + "/index.theme")):
            run(["gtk-update-icon-cache", "-q", "-f", t], quiet=quiet)
    run(["update-desktop-database", "-q", "/usr/share/applications"], quiet=quiet)
    if os.path.isdir(R("/usr/local/share/applications")):
        run(["update-desktop-database", "-q", "/usr/local/share/applications"], quiet=quiet)
    run(["python3", "-m", "compileall", "-q", "-j0", "/usr/lib/zeta"], quiet=True)


def post_steps(changed, ollama_was_active, ollama_new):
    warnings = []

    def step(cmd, what):
        if run(cmd) != 0:
            warnings.append(what)

    step(["systemctl", "daemon-reload"], "systemctl daemon-reload")
    if any(p.startswith("/etc/udev/") for p in changed):
        step(["udevadm", "control", "--reload"], "udev")
    if any(p.startswith("/etc/sysctl.d/") for p in changed):
        step(["sysctl", "--system"], "sysctl")
    for p in sorted(changed):
        if p.startswith("/etc/tmpfiles.d/") and p.endswith(".conf"):
            step(["systemd-tmpfiles", "--create", p], p)
    caches(changed)
    if any(p.startswith(("/usr/share/fonts/", "/etc/fonts/")) for p in changed):
        step(["fc-cache", "-f"], "fc-cache")
    if "/usr/share/zeta/languages.json" in changed:
        if not C.test:
            enable_locales()
        step(["locale-gen"], "locale-gen")
    for hook in C.m.get("replay", []):
        say("   " + _("Running: {step}").format(step=hook))
        step(["sh", os.path.join(C.bundle, "hooks", hook)], hook)
    boot_theme = any(p.startswith(("/usr/share/plymouth/themes/zeta/", "/etc/initramfs-tools/"))
                     or p == "/usr/share/zeta/brand/zeta-logo.svg.in" for p in changed)
    if boot_theme:
        say("   " + _("Boot screen changed: rebuilding the boot image (about a minute)"))
        if not C.test:
            boot_images()
        step(["update-initramfs", "-u", "-k", "all"], "update-initramfs")
    if any(p.startswith(("/etc/default/grub.d/", "/etc/grub.d/")) for p in changed) and \
            (C.test or shutil.which("update-grub")):
        step(["update-grub"], "update-grub")
    if ollama_new and (ollama_was_active or C.test):
        step(["systemctl", "start", "ollama.service"], "ollama")
    elif "/etc/systemd/system/ollama.service" in changed:
        step(["systemctl", "try-restart", "ollama.service"], "ollama")
    deb = C.m.get("release_deb")
    if deb:
        say("   " + _("Package source for ZETA RAYS updates"))
        step(["dpkg", "-i", os.path.join(C.bundle, deb)], deb)
    return warnings


def enable_locales():
    """New languages of languages.json enabled in /etc/locale.gen (hook 0110,
    first half: the system language stays the one the user chose)."""
    try:
        wanted = {l["locale"] for l in json.load(open("/usr/share/zeta/languages.json", encoding="utf-8"))}
        lines = open("/etc/locale.gen", encoding="utf-8").read().splitlines()
    except (OSError, ValueError, KeyError):
        return
    out = []
    for line in lines:
        mm = re.match(r"^#\s*([A-Za-z_@.0-9-]+)\s+(UTF-8)\s*$", line)
        out.append("%s UTF-8" % mm.group(1) if mm and mm.group(1) in wanted else line)
    _write_text("/etc/locale.gen", "\n".join(out) + "\n")


def boot_images():
    """Boot splash pictures from the brand logo (hook 0100)."""
    p = "/usr/share/plymouth/themes/zeta"
    svg = _read("/usr/share/zeta/brand/zeta-logo.svg.in").replace("ACCENT", "#3A8DFF")
    if svg and shutil.which("rsvg-convert"):
        with open("/run/zeta-logo.svg", "w") as f:
            f.write(svg)
        run(["rsvg-convert", "-w", "200", "-o", p + "/logo.png", "/run/zeta-logo.svg"])
        os.unlink("/run/zeta-logo.svg")


# ------------------------------------------------------------ main

def ask(question):
    try:
        # "y"/"yes" and the same two answers in the user's language
        return input(question + " ").strip().lower() in {"y", "yes", _("y"), _("yes")}
    except EOFError:
        return False


def _interrupted(_sig, _frame):
    raise KeyboardInterrupt


def main(argv):
    global LANG
    ap = argparse.ArgumentParser(prog="zeta-upgrade")
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--lang", default="")
    ap.add_argument("--root", default="/")
    ap.add_argument("--arch", default="")
    ap.add_argument("--no-apt", action="store_true")
    args = ap.parse_args(argv)
    # a closed terminal window or a shutdown: the same as Ctrl+C (the files
    # step puts everything back; elsewhere a new run resumes)
    signal.signal(signal.SIGHUP, _interrupted)
    signal.signal(signal.SIGTERM, _interrupted)

    C.bundle = os.path.abspath(args.bundle)
    with open(os.path.join(C.bundle, "manifest.json"), encoding="utf-8") as f:
        C.m = json.load(f)
    IT.update(C.m.get("i18n", {}).get("it", {}))
    LANG = "it" if args.lang.startswith("it") else "en"
    C.root = os.path.abspath(args.root)
    C.test = C.root != "/"
    C.dry = args.dry_run
    m = C.m

    if not C.test and os.geteuid() != 0:
        print(_("Administrator rights needed: run it with sudo."))
        return 1
    lock_path = R("/run/zeta-rays-upgrade.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock = open(lock_path, "w")
    try:
        fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(_("The upgrade is already running in another window."))
        return 1
    if not C.dry:
        os.makedirs(R("/var/log"), exist_ok=True)
        C.log = open(R("/var/log/zeta-rays-upgrade.log"), "a", encoding="utf-8")

    say()
    say(_("ZETA RAYS {old} -> {new} upgrade ({arch})").format(old=m["from"], new=m["to"], arch=m["arch"]))
    if C.dry:
        say(_("Test run (--dry-run): nothing is changed."))
    if C.test:
        say(_("Test mode: system root {root}").format(root=C.root))

    head(1, _("Checks"))
    problems = checks(args)
    if problems:
        for p in problems:
            say("   ! " + p)
        say(_("Nothing was changed."))
        return 2

    actions, removals = plan_files()
    missing, already = (list(m["packages"]["new"]), []) if args.no_apt else plan_packages()
    ollama = plan_ollama()
    hypr = None if args.no_apt else plan_hyprland()
    upgradable = None if args.no_apt else count_upgradable()
    head(2, _("What will change"))
    show_plan(actions, removals, missing, already, ollama, hypr, upgradable)
    prev = load_state()
    if prev.get("status") == "done":
        say("   " + _("This system was already upgraded on {date}: running again repairs missing or damaged files.").format(
            date=prev.get("finished", "?")))
    if C.dry:
        say()
        say(_("Backup folder: /var/backups/zeta-rays-{version}-DATE").format(version=os_release().get("VERSION_ID", "?")))
        say(_("Test run finished: nothing was changed."))
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            say(_("Add --yes to run without questions."))
            return 1
        if not ask(_("Continue? [y/N]")):
            say(_("Cancelled: nothing was changed."))
            return 1

    head(3, _("Backup"))
    bk = new_backup()
    save_state(status="in-progress", backup=bk.dir, started=time.strftime("%Y-%m-%d %H:%M:%S"),
               bundle=m.get("bundle_id", ""), stage="backup")
    make_backup(bk, actions, removals, ollama)
    say("   " + _("Copies of the files that will change: {dir}").format(dir=bk.dir))

    head(4, _("Packages"))
    save_state(stage="packages")
    try:
        if args.no_apt:
            say("   " + _("Skipped (--no-apt)"))
        else:
            packages_step(missing, hypr)
    except Failure as e:
        say("   ! " + str(e))
        save_state(status="failed", stage="packages")
        say(_("Log: /var/log/zeta-rays-upgrade.log"))
        return 1

    head(5, _("ZETA RAYS files"))
    save_state(stage="files")
    fail_at = int(os.environ.get("ZETA_UPGRADE_FAIL_AT", "0") or 0) if C.test else 0
    ollama_was_active = False
    try:
        conflicts, skipped = files_step(bk, actions, removals, fail_at)
        if ollama:
            say("   " + _("AI engine (Ollama)"))
            ollama_was_active = ollama_step(bk, ollama)
        write_version()
        units_step(bk)
    except (Failure, OSError, tarfile.TarError, KeyError, KeyboardInterrupt) as e:
        say("   ! " + (str(e) or _("Interrupted.")))
        rollback(bk)
        say(_("The upgrade did not complete: the ZETA RAYS files are as before (packages installed by apt stay)."))
        say(_("Log: /var/log/zeta-rays-upgrade.log"))
        return 1
    save_state(stage="post")

    head(6, _("Finishing"))
    changed = {p for p, a in actions.items() if a in ("new", "replace")} | set(removals)
    warnings = post_steps(changed, ollama_was_active, bool(ollama))
    save_state(status="done", stage="done", finished=time.strftime("%Y-%m-%d %H:%M:%S"))

    say()
    say(_("ZETA RAYS {version} is installed.").format(version=m["to"]))
    say("   " + _("Backup and rollback: sudo bash {dir}/rollback.sh").format(dir=bk.dir))
    say("   " + _("Log: /var/log/zeta-rays-upgrade.log"))
    if conflicts:
        say("   " + _("Compare these settings files with the new version (.dpkg-dist) when you have time:"))
        for p in conflicts:
            say("     " + p)
    if skipped:
        say("   " + _("Not installed (check failed): {list}").format(list=", ".join(skipped)))
    for w in warnings:
        say("   " + _("Warning: {step} did not complete (see the log)").format(step=w))
    if m.get("models"):
        say("   " + _("AI: your current model keeps working. Settings > AI recommends the model of this release ({models}) and downloads it with one click.").format(
            models=", ".join(m["models"])))
    say("   " + _("Your settings are brought up to date at your next login."))
    say(_("Restart the computer to finish."))
    if args.gui and not C.test:
        if ask(_("Restart now? [y/N]")):
            run(["systemctl", "reboot"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print()
        print(_("Interrupted. Run the upgrade again to complete it (it resumes safely)."))
        sys.exit(130)
