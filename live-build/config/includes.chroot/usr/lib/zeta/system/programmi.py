# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA RAYS — software and command discovery.

One answer to "where is X?", "which command starts X?", "which package
provides X?", used by ZETA (the assistant), `zeta-app trova` and search.
Everything is discovered from the system, never from a hard-coded list:

  - applications: the app registry (applicazioni.py: APT, Flatpak, AppImage,
    /opt, /usr/local, the user's own entries), with their desktop entry,
    executable, launch command, version and source;
  - commands: every directory of $PATH, plus the sbin directories (shown
    as "not in your PATH" when the user's PATH lacks them), the user's
    ~/.local/bin; for each: real path, symlink target, script or program,
    owning Debian package and its version;
  - system services (systemd units) and shared libraries (ldconfig cache).

Several installations of the same program (APT and Flatpak and AppImage)
are all returned, each with its source, so nobody launches the wrong one.
"""
import os
import re
import shlex
import shutil
import subprocess

from system import applicazioni as reg

from i18n import tr  # noqa: E402

C = dict(os.environ, LC_ALL="C.UTF-8", LANGUAGE="C")
# where a command comes from when no Debian package owns it
FONTI_COMANDO = {"user": tr("your own (~/.local/bin)"), "opt": tr("installed by hand in /opt"),
                 "local": tr("installed by hand in /usr/local"), "flatpak": "Flatpak",
                 "system": tr("part of the system")}
EXTRA_DIRS = ("/usr/local/sbin", "/usr/sbin", "/sbin")


def _run(argv, timeout=8):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=C)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def path_dirs():
    """The user's PATH, in order, without duplicates or missing folders."""
    out = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        d = os.path.normpath(os.path.expanduser(d)) if d else ""
        if d and os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def package_of(path):
    """Debian package that installed this file ("" when none)."""
    for p in dict.fromkeys((path, os.path.realpath(path))):
        rc, out = _run(["dpkg-query", "-S", p])
        for line in out.splitlines() if rc == 0 else []:
            # "pkg1, pkg2: /path", "pkg:arch: /path"; "diversion by X from/to:"
            # lines describe a renamed file, not its owner
            if line.startswith("diversion by "):
                continue
            pkg = line.rsplit(": ", 1)[0].split(",")[0].strip()
            return pkg.split(":")[0]
    return ""


def package_version(pkg):
    if not pkg:
        return ""
    rc, out = _run(["dpkg-query", "-W", "-f", "${Version}", pkg])
    return out.strip() if rc == 0 else ""


def _kind_of_file(path):
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return "program"
    if head.startswith(b"\x7fELF"):
        if len(head) > 10 and head[8:10] == b"AI":
            return "appimage"
        return "program"
    if head.startswith(b"#!"):
        return "script"
    return "program"


def _source_of(path, pkg):
    if pkg:
        return "apt"
    real = os.path.realpath(path)
    home = os.path.expanduser("~")
    if real.startswith(home + os.sep):
        return "user"
    if real.startswith("/opt/"):
        return "opt"
    if real.startswith("/usr/local/"):
        return "local"
    if real.startswith(("/var/lib/flatpak/", os.path.join(home, ".local/share/flatpak/"))):
        return "flatpak"
    return "system"


def commands(name):
    """Every executable called exactly `name` in PATH (first one wins when
    you type it), then in sbin directories missing from PATH."""
    found, seen = [], set()
    in_path = path_dirs()
    extra = [d for d in EXTRA_DIRS if os.path.isdir(d) and d not in in_path]
    first = shutil.which(name)
    for d in in_path + extra:
        p = os.path.join(d, name)
        if not (os.path.isfile(p) and os.access(p, os.X_OK)):
            continue
        real = os.path.realpath(p)
        if real in seen:
            continue                     # /bin -> /usr/bin on merged-/usr systems
        seen.add(real)
        pkg = package_of(p)
        found.append({
            "kind": "command",
            "name": name,
            "path": p,
            "target": real if real != p else "",
            "file_kind": _kind_of_file(real),
            "in_path": d in in_path,
            "default": bool(first) and os.path.realpath(first) == real,
            "package": pkg,
            "version": package_version(pkg),
            "source": _source_of(p, pkg),
            "launch": name if d in in_path else p,
        })
    return found


def apps(query):
    """Applications of the registry matching the query (name, id, program,
    Flatpak id), best matches first."""
    q = query.casefold().strip()
    if not q:
        return []
    out = []
    for a in reg.tutte():
        if a.servizio:
            continue
        nome = a.nome.casefold()
        stem = a.id[:-len(".desktop")].casefold() if a.id.endswith(".desktop") else a.id.casefold()
        prog = os.path.basename(a.eseguibile or "").casefold()
        fid = (a.flatpak_id or "").casefold()
        if q == nome or q == prog or q == stem or q == fid or stem.endswith("." + q):
            score = 0
        elif nome.startswith(q) or prog.startswith(q) or q in stem.split(".") or q in fid:
            score = 1
        elif q in nome or q in stem:
            score = 2
        else:
            continue
        out.append((score, a))
    out.sort(key=lambda t: (t[0], t[1].nome.casefold(), t[1].fonte))
    res = []
    for _s, a in out:
        pkg = reg.pacchetto_app(a) if a.fonte not in ("flatpak", "appimage") else ""
        res.append({
            "kind": "app",
            "name": a.nome,
            "id": a.id,
            "source": a.fonte,
            "source_label": reg.FONTI.get(a.fonte, a.fonte),
            "desktop": a.desktop,
            "path": a.appimage or a.eseguibile or "",
            # as typed in a terminal: no %U/%F placeholders of the menu entry
            "command": " ".join(reg._senza_codici(a.comando).split()),
            "launch": "zeta-app launch %s" % shlex.quote(a.id),
            "flatpak_id": a.flatpak_id or "",
            "package": pkg,
            "version": reg.versione(a) or package_version(pkg),
            "in_menu": a.nel_menu,
            "protected": a.protetta,
            "icon": a.icona,
        })
    return res


def services(query):
    q = query.casefold().strip()
    if len(q) < 2:
        return []
    rc, out = _run(["systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"])
    res = []
    for line in out.splitlines() if rc == 0 else []:
        parts = line.split()
        if parts and q in parts[0].casefold():
            st, act = _run(["systemctl", "is-active", parts[0]])
            res.append({"kind": "service", "name": parts[0],
                        "enabled": parts[1] if len(parts) > 1 else "",
                        "active": act.strip()})
    return res[:10]


def libraries(query):
    q = query.casefold().strip()
    if len(q) < 3 or not re.fullmatch(r"[a-z0-9+._-]+", q):
        return []
    rc, out = _run(["ldconfig", "-p"])
    res, seen = [], set()
    for line in out.splitlines()[1:] if rc == 0 else []:
        m = re.match(r"\s*(\S+)\s.*=>\s*(\S+)", line)
        if m and q in m.group(1).casefold() and m.group(2) not in seen:
            seen.add(m.group(2))
            res.append({"kind": "library", "name": m.group(1), "path": m.group(2),
                        "package": package_of(m.group(2))})
    return res[:10]


def find(query, services_too=True, libraries_too=False):
    """Everything known about `query`: apps, commands, services, libraries."""
    query = query.strip()
    if not query:
        return []
    res = apps(query)
    if re.fullmatch(r"[A-Za-z0-9+._-]+", query):
        res += commands(query)
        low = query.lower()
        if low != query:
            res += commands(low)
    if services_too:
        res += services(query)
    if libraries_too:
        res += libraries(query)
    return res


def appimages():
    """Every AppImage found on this computer, integrated or not."""
    integrate = {os.path.realpath(a.appimage): a for a in reg.tutte() if a.appimage}
    out = []
    for p in reg.appimage_trovate():
        a = integrate.get(p)
        out.append({"kind": "appimage", "path": p, "name": a.nome if a else os.path.basename(p),
                    "id": a.id if a else "", "in_menu": bool(a and a.nel_menu)})
    return out
