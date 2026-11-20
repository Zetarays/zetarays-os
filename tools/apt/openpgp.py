# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal OpenPGP (RFC 4880 / RFC 9580, version 4) for signing the ZETA RAYS
package repository without GnuPG on the build computer.

Only what an APT repository needs: one Ed25519 signing key (algorithm 22,
"EdDSALegacy", the format every apt verifier reads: gpgv and Sequoia's sqv),
its transferable public key (the keyring apt's Signed-By points to), a
detached signature (Release.gpg) and a cleartext signature (InRelease).
Hash: SHA-512. Requires the "cryptography" Python package.

When GnuPG is available, check the results with:
    gpg --show-keys zeta-rays-archive-keyring.gpg
    gpgv --keyring ./zeta-rays-archive-keyring.gpg InRelease
    gpgv --keyring ./zeta-rays-archive-keyring.gpg Release.gpg Release
"""
import base64
import hashlib
import struct

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ALGO_EDDSA = 22
HASH_SHA512 = 10
ED25519_OID = bytes.fromhex("2b06010401da470f01")   # 1.3.6.1.4.1.11591.15.1


def _mpi(data):
    data = data.lstrip(b"\0") or b"\0"
    bits = (len(data) - 1) * 8 + data[0].bit_length()
    return struct.pack(">H", bits) + data


def _packet(tag, body):
    n = len(body)
    if n < 192:
        length = bytes([n])
    elif n < 8384:
        n -= 192
        length = bytes([(n >> 8) + 192, n & 0xFF])
    else:
        length = b"\xff" + struct.pack(">I", n)
    return bytes([0xC0 | tag]) + length + body


def _subpacket(kind, data):
    body = bytes([kind]) + data
    assert len(body) < 192
    return bytes([len(body)]) + body


class Key:
    def __init__(self, private_pem, created):
        self.sk = serialization.load_pem_private_key(private_pem, password=None)
        self.created = int(created)
        pk = self.sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.body = (bytes([4]) + struct.pack(">I", self.created) + bytes([ALGO_EDDSA, len(ED25519_OID)])
                     + ED25519_OID + _mpi(b"\x40" + pk))
        self.fingerprint = hashlib.sha1(b"\x99" + struct.pack(">H", len(self.body)) + self.body).digest()
        self.key_id = self.fingerprint[-8:]

    @staticmethod
    def generate():
        sk = Ed25519PrivateKey.generate()
        return sk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())

    def _sign(self, sigtype, prefix, created, extra_hashed=b""):
        hashed = (_subpacket(2, struct.pack(">I", created))
                  + _subpacket(33, bytes([4]) + self.fingerprint) + extra_hashed)
        head = bytes([4, sigtype, ALGO_EDDSA, HASH_SHA512]) + struct.pack(">H", len(hashed)) + hashed
        trailer = b"\x04\xff" + struct.pack(">I", len(head))
        digest = hashlib.sha512(prefix + head + trailer).digest()
        sig = self.sk.sign(digest)
        unhashed = _subpacket(16, self.key_id)
        body = (head + struct.pack(">H", len(unhashed)) + unhashed + digest[:2]
                + _mpi(sig[:32]) + _mpi(sig[32:]))
        return _packet(2, body)

    def public_key(self, uid):
        """Transferable public key: key, user id, self-certification."""
        uid_b = uid.encode("utf-8")
        prefix = (b"\x99" + struct.pack(">H", len(self.body)) + self.body
                  + b"\xb4" + struct.pack(">I", len(uid_b)) + uid_b)
        extra = (_subpacket(27, b"\x03")                 # certify + sign
                 + _subpacket(21, bytes([HASH_SHA512, 8]))  # preferred hashes: SHA-512, SHA-256
                 + _subpacket(22, bytes([2, 1]))         # zlib, zip (unused)
                 + _subpacket(11, bytes([9, 7]))         # AES-256, AES-128 (unused)
                 + _subpacket(30, b"\x01")               # features: modification detection
                 + _subpacket(25, b"\x01"))              # primary user id
        return (_packet(6, self.body) + _packet(13, uid_b)
                + self._sign(0x13, prefix, self.created, extra))

    def detached(self, data, created):
        """Binary-document signature (Release.gpg), armored."""
        return armor(self._sign(0x00, data, created), "SIGNATURE")

    def cleartext(self, text, created):
        """Cleartext signed message (InRelease)."""
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        signed = "\r\n".join(l.rstrip(" \t") for l in lines).encode("utf-8")
        sig = self._sign(0x01, signed, created)
        body = "".join(("- " + l if l.startswith("-") else l) + "\n" for l in lines)
        return ("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n" + body
                + armor(sig, "SIGNATURE"))


def _crc24(data):
    crc = 0xB704CE
    for b in data:
        crc ^= b << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def armor(data, kind):
    b64 = base64.b64encode(data).decode()
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    crc = base64.b64encode(struct.pack(">I", _crc24(data))[1:]).decode()
    return ("-----BEGIN PGP %s-----\n\n%s\n=%s\n-----END PGP %s-----\n"
            % (kind, "\n".join(lines), crc, kind))
