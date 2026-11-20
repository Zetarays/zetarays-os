#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the ZETA RAYS Debian packages (no dpkg needed: plain Python).

    tools/make-zeta-debs.py [--version 3.0] [--out out/debs] [--release-only]

  zeta-rays-release_V_all.deb   the package source of the ZETA RAYS updates:
                                the ZETA RAYS source (active only while
                                https://zetarays.org/apt/ answers) and the
                                public signing key. Installed in the image
                                (hook 9993) and by the 2.5 -> 3.0 upgrade.
  zeta-rays-desktop_V_all.deb   the ZETA RAYS files, the same ones the image
                                gets from includes.chroot (tools/upgrade/zeta_files.py
                                decides which). Published in the repository;
                                the 3.0 image does NOT install it yet (see
                                docs/UPDATES.md).

The version comes from the VERSION file. The public key must exist
(tools/apt/gen-repo-key.py); without it nothing is built.
"""
import argparse
import hashlib
import io
import os
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "upgrade"))
import zeta_files as zf  # noqa: E402

APT = os.path.join(HERE, "apt")
KEYRING = os.path.join(APT, "zeta-rays-archive-keyring.gpg")
SOURCES = os.path.join(APT, "zeta-rays.sources")
INCLUDES = os.path.join(ROOT, "live-build", "config", "includes.chroot")
OLD_INCLUDES = os.path.join(ROOT, ".cache", "src-2.5-release-config", "includes.chroot")
MAINTAINER = "ZETA RAYS OS <info@zetarays.org>"
COPYRIGHT = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: ZETA RAYS OS
Source: https://zetarays.org/

Files: *
Copyright: ZETA RAYS OS
License: GPL-3.0-or-later
 On Debian systems, the complete text of the GNU General Public License
 version 3 can be found in /usr/share/common-licenses/GPL-3.
"""


def _ti(name, kind=tarfile.REGTYPE, mode=0o644, size=0, target=""):
    ti = tarfile.TarInfo(name)
    ti.type = kind
    ti.mode = mode
    ti.size = size
    ti.linkname = target
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = "root"
    ti.mtime = int(time.time())
    return ti


def tar_xz(entries):
    """entries: {"./path": ("file", mode, bytes) | ("link", target)} -> .tar.xz
    with every parent directory listed first (dpkg needs them)."""
    dirs = set()
    for name in entries:
        parts = name.split("/")[1:-1]
        for i in range(len(parts)):
            dirs.add("./" + "/".join(parts[:i + 1]) + "/")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz", format=tarfile.GNU_FORMAT) as tar:
        tar.addfile(_ti("./", tarfile.DIRTYPE, 0o755))
        for d in sorted(dirs):
            tar.addfile(_ti(d, tarfile.DIRTYPE, 0o755))
        for name in sorted(entries):
            e = entries[name]
            if e[0] == "link":
                tar.addfile(_ti(name, tarfile.SYMTYPE, 0o777, target=e[1]))
            else:
                tar.addfile(_ti(name, mode=e[1], size=len(e[2])), io.BytesIO(e[2]))
    return buf.getvalue()


def ar(members):
    out = [b"!<arch>\n"]
    now = int(time.time())
    for name, data in members:
        out.append(("%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, now, 0, 0, "100644", len(data))).encode())
        out.append(data + (b"\n" if len(data) % 2 else b""))
    return b"".join(out)


def build(out_dir, package, version, description, files, conffiles=(), scripts=None, depends=""):
    """files: {"/abs/path": ("file", mode, bytes) | ("link", target)}"""
    entries = {"." + p: e for p, e in files.items()}
    doc = "./usr/share/doc/%s/copyright" % package
    entries.setdefault(doc, ("file", 0o644, COPYRIGHT.encode()))
    size_kb = sum(len(e[2]) for e in entries.values() if e[0] == "file") // 1024 + 1
    control = ["Package: " + package, "Version: " + version, "Architecture: all",
               "Maintainer: " + MAINTAINER, "Installed-Size: %d" % size_kb,
               "Section: admin", "Priority: optional", "Homepage: https://zetarays.org/"]
    if depends:
        control.append("Depends: " + depends)
    summary, long = description
    control.append("Description: " + summary)
    control += [" " + (l if l else ".") for l in long.strip().split("\n")]
    md5 = "".join("%s  %s\n" % (hashlib.md5(e[2]).hexdigest(), n[2:])
                  for n, e in sorted(entries.items()) if e[0] == "file")
    cfiles = {"./control": ("file", 0o644, ("\n".join(control) + "\n").encode()),
              "./md5sums": ("file", 0o644, md5.encode())}
    if conffiles:
        cfiles["./conffiles"] = ("file", 0o644, "".join(c + "\n" for c in sorted(conffiles)).encode())
    for name, text in (scripts or {}).items():
        cfiles["./" + name] = ("file", 0o755, text.encode())
    deb = ar([("debian-binary", b"2.0\n"), ("control.tar.xz", tar_xz(cfiles)), ("data.tar.xz", tar_xz(entries))])
    path = os.path.join(out_dir, "%s_%s_all.deb" % (package, version))
    with open(path, "wb") as f:
        f.write(deb)
    print("%s (%d files, %.1f KB)" % (path, len(entries), len(deb) / 1024.0))
    return path


def release_package(out_dir, version):
    sources = open(SOURCES, "rb").read()
    keyring = open(KEYRING, "rb").read()
    check = open(os.path.join(APT, "zeta-rays-source-check"), "rb").read()
    files = {
        # The source itself is NOT shipped in /etc/apt/sources.list.d: the
        # check script copies this pristine file there only while the
        # repository answers (a missing repository would make every
        # "apt update" fail), and removes it otherwise.
        "/usr/share/zeta-rays-release/zeta-rays.sources": ("file", 0o644, sources),
        "/usr/share/zeta-rays-release/check-source": ("file", 0o755, check),
        "/etc/apt/apt.conf.d/50zeta-rays-source": ("file", 0o644, RELEASE_APT_CONF.encode()),
        "/usr/share/keyrings/zeta-rays-archive-keyring.gpg": ("file", 0o644, keyring),
    }
    return build(out_dir, "zeta-rays-release", version,
                 ("ZETA RAYS OS updates: package source and signing key",
                  "The package source of the ZETA RAYS components (https://zetarays.org/apt/)\n"
                  "and the public key their updates are signed with. Software Update\n"
                  "shows ZETA RAYS updates next to the Debian ones."),
                 files, conffiles=["/etc/apt/apt.conf.d/50zeta-rays-source"],
                 scripts={"postinst": RELEASE_POSTINST, "postrm": RELEASE_POSTRM})


RELEASE_APT_CONF = """// ZETA RAYS: the ZETA RAYS package source is active only while its
// repository answers (see /usr/share/zeta-rays-release/check-source).
APT::Update::Pre-Invoke { "[ ! -x /usr/share/zeta-rays-release/check-source ] || /usr/share/zeta-rays-release/check-source || true"; };
"""

RELEASE_POSTINST = """#!/bin/sh
set -e
if [ "$1" = configure ]; then
    # a copy left by an earlier version that shipped the source directly
    /usr/share/zeta-rays-release/check-source || true
fi
exit 0
"""

RELEASE_POSTRM = """#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = purge ]; then
    rm -f /etc/apt/sources.list.d/zeta-rays.sources
fi
exit 0
"""


POSTINST = r'''#!/bin/sh
# ZETA RAYS: files that Debian packages may also ship are copied by this
# script instead of being owned by the package; then the caches the build
# hooks prepare. Settings files changed on this computer are kept: the new
# version goes next to them as FILE.dpkg-dist.
set -e
D=/usr/share/zeta-rays-desktop
if [ "$1" = configure ]; then
    while IFS='	' read -r path policy known; do
        src="$D/files$path"
        [ -e "$src" ] || [ -L "$src" ] || continue
        if [ "$policy" = conffile ] && { [ -e "$path" ] || [ -L "$path" ]; }; then
            cur=$(sha256sum < "$path" 2>/dev/null | cut -c1-64)
            new=$(sha256sum < "$src" | cut -c1-64)
            [ "$cur" = "$new" ] && continue
            case ",$known," in
                *",$cur,"*) ;;
                *) cp -a "$src" "$path.dpkg-dist"; continue ;;
            esac
        fi
        mkdir -p "$(dirname "$path")"
        rm -f "$path.zeta-new"
        cp -a "$src" "$path.zeta-new"
        mv -f "$path.zeta-new" "$path"
    done < "$D/managed.list"
    glib-compile-schemas /usr/share/glib-2.0/schemas || true
    for t in /usr/share/icons/zeta /usr/share/icons/hicolor; do
        [ -f "$t/index.theme" ] && gtk-update-icon-cache -q -f "$t" || true
    done
    update-desktop-database -q /usr/share/applications || true
    python3 -m compileall -q -j0 /usr/lib/zeta >/dev/null 2>&1 || true
    if [ -d /run/systemd/system ]; then systemctl daemon-reload || true; fi
fi
exit 0
'''


def desktop_package(out_dir, version):
    new = zf.collect(INCLUDES, version)
    old = zf.collect(OLD_INCLUDES, "2.5") if os.path.isdir(OLD_INCLUDES) else {}
    files, conffiles, managed = {}, [], []
    for path, e in sorted(new.items()):
        rel = path[1:]
        item = ("link", e["target"]) if e["type"] == "link" else ("file", e["mode"], e["data"])
        own = zf.is_zeta_named(rel) or rel.startswith("usr/local/")
        if own:
            files[path] = item
            if e["policy"] in ("conffile", "skel") and e["type"] == "file":
                conffiles.append(path)
        else:
            files["/usr/share/zeta-rays-desktop/files" + path] = item
            known = [old[path]["sha256"]] if path in old else []
            managed.append("%s\t%s\t%s" % (path, "conffile" if rel.startswith("etc/") else "replace",
                                          ",".join(known)))
    files["/usr/share/zeta-rays-desktop/managed.list"] = ("file", 0o644, ("\n".join(managed) + "\n").encode())
    return build(out_dir, "zeta-rays-desktop", version,
                 ("ZETA RAYS OS desktop, assistant and system tools",
                  "The ZETA RAYS components: desktop session, Settings, ZETA (the local\n"
                  "assistant), security center, themes, icons and default settings."),
                 files, conffiles=conffiles, scripts={"postinst": POSTINST})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="")
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "debs"))
    ap.add_argument("--release-only", action="store_true")
    a = ap.parse_args()
    version = a.version or open(os.path.join(ROOT, "VERSION")).read().strip()
    if not os.path.exists(KEYRING):
        print("make-zeta-debs: the repository key does not exist yet: run tools/apt/gen-repo-key.py", file=sys.stderr)
        return 1
    os.makedirs(a.out, exist_ok=True)
    release_package(a.out, version)
    if not a.release_only:
        desktop_package(a.out, version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
