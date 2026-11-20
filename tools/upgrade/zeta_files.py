# SPDX-License-Identifier: GPL-3.0-or-later
"""The ZETA RAYS files of an image, as the upgrade bundle and the Debian
packages see them (build-side helper, standard library only).

One list, two users:
  tools/upgrade/make_bundle.py   the in-place upgrade (zetarays-X-upgrade-ARCH.run)
  tools/make-zeta-debs.py        zeta-rays-desktop_X_all.deb (same files)

Every path of live-build/config/includes.chroot gets a policy:
  zeta       under /usr: owned by ZETA RAYS, replaced (a copy is kept)
  skel       /etc/skel: the template for new users, replaced; existing
             users get the changes from zeta-migrate-user at their next login
  conffile   anything else under /etc: replaced only when the installed copy
             is one ZETA RAYS shipped (or missing because it is new); a copy
             changed by the user or by the system stays and the new version
             is written next to it as FILE.dpkg-dist
and some paths are left out (models, live session only, installer, inputs
of the build hooks).
"""
import hashlib
import os
import re
import stat

# Never part of an upgrade or a package.
EXCLUDE_PREFIXES = (
    # AI models (gigabytes): Settings > AI offers the download
    "usr/share/ollama/",
    # build inputs consumed and deleted by the hooks
    "usr/share/zeta/ollama-runtime.tar.zst",
    "usr/share/zeta/piper-cache/",
    "usr/share/zeta/vosk-cache/",
    "usr/share/zeta/hyprland-patched/",
    "usr/share/zeta/localsend/",
    "usr/share/zeta/apt-release/",
    "usr/share/zeta/version",
    # live session only (live-config)
    "etc/live/",
    "usr/lib/live/",
    # the installer: Calamares removes itself from the installed system
    "etc/calamares/",
    "usr/share/calamares/",
)
EXCLUDE_NAMES = ("__pycache__", ".DS_Store")
EXCLUDE_SUFFIXES = (".pyc", ".pyo", "~", ".orig", ".rej")


def excluded(rel):
    for x in EXCLUDE_PREFIXES:
        if rel == x or rel == x.rstrip("/") or (x.endswith("/") and rel.startswith(x)):
            return True
    parts = rel.split("/")
    if any(p in EXCLUDE_NAMES or p.startswith("._") for p in parts):
        return True
    return rel.endswith(EXCLUDE_SUFFIXES)


def policy(rel):
    if rel.startswith("etc/skel/"):
        return "skel"
    if rel.startswith("etc/"):
        return "conffile"
    return "zeta"


def is_zeta_named(rel):
    """An /etc file whose name says it belongs to ZETA RAYS (no Debian
    package ships it). The others (nftables.conf, default/earlyoom...) are
    also files of Debian packages."""
    return rel.startswith("etc/skel/") or "zeta" in rel.lower()


def mode_for(rel, src_mode):
    """The mode the build gives the file in the image (hook 0100 included)."""
    if rel.startswith("etc/sudoers.d/"):
        return 0o440
    if re.match(r"etc/ufw/user6?\.rules$", rel):
        return 0o640
    if rel.startswith("usr/lib/zeta/") and rel.endswith(".py"):
        return 0o644
    if rel.startswith(("usr/local/bin/", "usr/local/libexec/", "usr/libexec/")):
        return 0o755
    return 0o755 if src_mode & 0o111 else 0o644


def transform(rel, data, version):
    """Text the build fills in after copying (hook 0100): the same values
    here, so the bundle carries the files exactly as an image has them."""
    if rel == "usr/share/grub/themes/zeta/theme.txt":
        data = data.replace(b"@VERSION@", version.encode())
    elif rel == "usr/share/sddm/themes/zeta/Main.qml":
        data = re.sub(rb'text: "[0-9]+\.[0-9]+"', b'text: "' + version.encode() + b'"', data)
    return data


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def collect(includes, version):
    """{"/abs/path": entry} for every file and symbolic link of the tree.

    entry: {"type": "file"|"link", "policy", "mode", "sha256", "size",
            "target" (links), "src" (files: path on this computer),
            "data" (files: content, transformed)}
    """
    out = {}
    for base, dirs, files in os.walk(includes):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_NAMES)
        for name in sorted(files) + sorted(d for d in dirs if os.path.islink(os.path.join(base, d))):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, includes).replace(os.sep, "/")
            if excluded(rel):
                continue
            st = os.lstat(full)
            e = {"policy": policy(rel)}
            if stat.S_ISLNK(st.st_mode):
                e.update(type="link", target=os.readlink(full), mode=0o777, size=0)
                e["sha256"] = sha256(("link:" + e["target"]).encode())
            elif stat.S_ISREG(st.st_mode):
                with open(full, "rb") as f:
                    data = transform(rel, f.read(), version)
                e.update(type="file", mode=mode_for(rel, st.st_mode), size=len(data),
                         sha256=sha256(data), src=full, data=data)
            else:
                continue
            out["/" + rel] = e
    return out


# ------------------------------------------------------------ package lists

def packages(list_dir, arch):
    """The package names of the live-build lists for one architecture
    (lines between «#if ARCHITECTURES x» and «#endif» only for x)."""
    names = set()
    for fn in sorted(os.listdir(list_dir)):
        if not fn.endswith(".list.chroot"):
            continue
        active = True
        with open(os.path.join(list_dir, fn), encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                m = re.match(r"#if\s+ARCHITECTURES\s+(.+)$", s)
                if m:
                    active = arch in m.group(1).split()
                    continue
                if s.startswith("#endif"):
                    active = True
                    continue
                if not s or s.startswith("#") or not active:
                    continue
                for word in s.split():
                    if word.startswith("#"):
                        break
                    names.add(word)
    return names


# ------------------------------------------------------------ hooks

UNIT = r"[A-Za-z0-9@_.:-]+\.(?:service|timer|socket|path|target|mount)"
ENABLE_RX = re.compile(r"systemctl\s+(--global\s+)?(enable|disable)\s+((?:%s\s*)+)" % UNIT)


def hook_units(hooks_dir):
    """{("enable"|"disable"|"global-enable"|"global-disable", unit)} named
    by the build hooks (systemctl enable/disable lines)."""
    found = set()
    if not os.path.isdir(hooks_dir):
        return found
    for fn in sorted(os.listdir(hooks_dir)):
        with open(os.path.join(hooks_dir, fn), encoding="utf-8", errors="replace") as f:
            for line in f:
                code = line.split("#", 1)[0]
                for m in ENABLE_RX.finditer(code):
                    verb = ("global-" if m.group(1) else "") + m.group(2)
                    for unit in re.findall(UNIT, m.group(3)):
                        found.add((verb, unit))
    return found


def heredoc(path, target):
    """The text a hook writes with «cat > TARGET <<'END'» (None if absent)."""
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    m = re.search(r"cat > %s <<'?(\w+)'?\n(.*?)\n\1\n" % re.escape(target), text, re.S)
    return m.group(2) + "\n" if m else None
