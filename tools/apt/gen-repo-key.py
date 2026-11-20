#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The signing key of the ZETA RAYS package repository.

    tools/apt/gen-repo-key.py            create it once (never replaced), export the public key
    tools/apt/gen-repo-key.py --show     print the fingerprint

The PRIVATE key stays on the owner's computer, outside the repository and the
images: ~/RAiX/.cache/v30/repo-key/ (or $ZETA_REPO_KEY_DIR), folder mode 0700,
file 0600. Back it up offline: without it no update can ever be signed for
systems that trust this key (a new key means shipping it first, signed by the
old one). The PUBLIC key is written into the repository, where the image and
the packages take it from:
    tools/apt/zeta-rays-archive-keyring.gpg   (binary, apt Signed-By)
    tools/apt/zeta-rays-archive-keyring.asc   (text, for the website)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openpgp import Key, armor  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
KEY_DIR = os.environ.get("ZETA_REPO_KEY_DIR", os.path.join(ROOT, ".cache", "v30", "repo-key"))
UID = "ZETA RAYS OS package signing key <info@zetarays.org>"


def load():
    meta = json.load(open(os.path.join(KEY_DIR, "key.json"), encoding="utf-8"))
    with open(os.path.join(KEY_DIR, "private-ed25519.pem"), "rb") as f:
        return Key(f.read(), meta["created"]), meta


def main():
    priv = os.path.join(KEY_DIR, "private-ed25519.pem")
    if "--show" not in sys.argv and not os.path.exists(priv):
        os.makedirs(KEY_DIR, mode=0o700, exist_ok=True)
        os.chmod(KEY_DIR, 0o700)
        pem = Key.generate()
        fd = os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        created = int(time.time())
        key = Key(pem, created)
        with open(os.path.join(KEY_DIR, "key.json"), "w", encoding="utf-8") as f:
            json.dump({"created": created, "uid": UID, "fingerprint": key.fingerprint.hex().upper(),
                       "algorithm": "Ed25519 (OpenPGP v4, EdDSALegacy)"}, f, indent=1)
        print("new key created in", KEY_DIR)
    key, meta = load()
    pub = key.public_key(meta["uid"])
    if "--show" not in sys.argv:
        with open(os.path.join(HERE, "zeta-rays-archive-keyring.gpg"), "wb") as f:
            f.write(pub)
        with open(os.path.join(HERE, "zeta-rays-archive-keyring.asc"), "w") as f:
            f.write(armor(pub, "PUBLIC KEY BLOCK"))
        print("public key written to tools/apt/zeta-rays-archive-keyring.{gpg,asc}")
    fp = key.fingerprint.hex().upper()
    print("fingerprint:", " ".join(fp[i:i + 4] for i in range(0, 40, 4)))


if __name__ == "__main__":
    main()
