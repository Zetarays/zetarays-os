#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the signed APT repository of ZETA RAYS from .deb files.

    tools/make-apt-repo.py [--debs out/debs] [--out out/apt] [--keep-old DIR]

Result (upload the whole folder to https://zetarays.org/apt/, see
docs/UPDATES.md):

  out/apt/
    zeta-rays-archive-keyring.asc        public key (for people, the website)
    pool/main/z/<package>/<package>_<version>_<arch>.deb
    dists/trixie/InRelease               signed index (cleartext signature)
    dists/trixie/Release + Release.gpg   the same, detached signature
    dists/trixie/main/binary-{amd64,arm64}/Packages{,.gz,.xz}

Packages of every version found in --debs and in the pool already there
(--keep-old, usually a copy of what is online) are listed: apt picks the
newest, and older ones stay installable. The private key is read from
~/RAiX/.cache/v30/repo-key (tools/apt/gen-repo-key.py) and never copied.
"""
import argparse
import email.utils
import json
import gzip
import hashlib
import io
import lzma
import os
import shutil
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "apt"))
from openpgp import Key  # noqa: E402

SUITE = "trixie"
COMPONENT = "main"
ARCHES = ("amd64", "arm64")
KEY_DIR = os.environ.get("ZETA_REPO_KEY_DIR", os.path.join(ROOT, ".cache", "v30", "repo-key"))


def ar_members(data):
    assert data[:8] == b"!<arch>\n", "not a .deb"
    pos, out = 8, {}
    while pos < len(data):
        head = data[pos:pos + 60]
        name = head[:16].decode().strip().rstrip("/")
        size = int(head[48:58])
        out[name] = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size % 2)
    return out


def control_of(deb_bytes):
    members = ar_members(deb_bytes)
    name = next(n for n in members if n.startswith("control.tar"))
    with tarfile.open(fileobj=io.BytesIO(members[name])) as tar:
        for m in tar.getmembers():
            if m.name in ("./control", "control"):
                return tar.extractfile(m).read().decode("utf-8")
    raise ValueError("control file missing")


def field(control, key):
    for line in control.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--debs", default=os.path.join(ROOT, "out", "debs"))
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "apt"))
    ap.add_argument("--keep-old", default="")
    a = ap.parse_args()
    meta = json.load(open(os.path.join(KEY_DIR, "key.json")))
    key = Key(open(os.path.join(KEY_DIR, "private-ed25519.pem"), "rb").read(), meta["created"])

    sources = [os.path.join(a.debs, f) for f in sorted(os.listdir(a.debs)) if f.endswith(".deb")]
    if a.keep_old:
        for base, _d, fns in os.walk(os.path.join(a.keep_old, "pool")):
            sources += [os.path.join(base, f) for f in sorted(fns) if f.endswith(".deb")]
    if not sources:
        print("no .deb files in %s" % a.debs, file=sys.stderr)
        return 1
    tmp = a.out + ".partial"
    shutil.rmtree(tmp, ignore_errors=True)
    stanzas = {arch: [] for arch in ARCHES}
    seen = set()
    for src in sources:
        data = open(src, "rb").read()
        control = control_of(data)
        pkg, ver, arch = field(control, "Package"), field(control, "Version"), field(control, "Architecture")
        if (pkg, ver, arch) in seen:
            continue
        seen.add((pkg, ver, arch))
        rel = "pool/%s/%s/%s/%s_%s_%s.deb" % (COMPONENT, pkg[0], pkg, pkg, ver, arch)
        os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
        with open(os.path.join(tmp, rel), "wb") as f:
            f.write(data)
        stanza = control.rstrip("\n") + "\nFilename: %s\nSize: %d\nMD5sum: %s\nSHA256: %s\n" % (
            rel, len(data), hashlib.md5(data).hexdigest(), hashlib.sha256(data).hexdigest())
        for target in (ARCHES if arch == "all" else (arch,)):
            if target in stanzas:
                stanzas[target].append(stanza)
        print("  %s %s %s" % (pkg, ver, arch))

    dist = os.path.join(tmp, "dists", SUITE)
    index_files = []
    for arch in ARCHES:
        d = os.path.join(dist, COMPONENT, "binary-" + arch)
        os.makedirs(d)
        text = "\n".join(stanzas[arch]).encode("utf-8")
        for name, blob in (("Packages", text), ("Packages.gz", gzip.compress(text, 9, mtime=0)),
                           ("Packages.xz", lzma.compress(text))):
            with open(os.path.join(d, name), "wb") as f:
                f.write(blob)
            index_files.append(("%s/binary-%s/%s" % (COMPONENT, arch, name), blob))
    now = time.time()
    release = ["Origin: ZETA RAYS", "Label: ZETA RAYS", "Suite: " + SUITE, "Codename: " + SUITE,
               "Date: " + email.utils.formatdate(now, usegmt=True),
               "Architectures: " + " ".join(ARCHES), "Components: " + COMPONENT,
               "Description: ZETA RAYS OS components", "SHA256:"]
    release += [" %s %8d %s" % (hashlib.sha256(b).hexdigest(), len(b), n) for n, b in index_files]
    release_text = "\n".join(release) + "\n"
    with open(os.path.join(dist, "Release"), "w") as f:
        f.write(release_text)
    with open(os.path.join(dist, "Release.gpg"), "w") as f:
        f.write(key.detached(release_text.encode("utf-8"), int(now)))
    with open(os.path.join(dist, "InRelease"), "w") as f:
        f.write(key.cleartext(release_text, int(now)))
    shutil.copy2(os.path.join(HERE, "apt", "zeta-rays-archive-keyring.asc"), tmp)
    shutil.rmtree(a.out, ignore_errors=True)
    os.rename(tmp, a.out)
    fp = key.fingerprint.hex().upper()
    print("repository ready: %s (key %s)" % (a.out, " ".join(fp[i:i + 4] for i in range(0, 40, 4))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
