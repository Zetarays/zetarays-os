#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scrive testo nella VM VirtualBox usando la mappatura della tastiera italiana.

VBoxManage keyboardputstring assume la tastiera americana: in ZETA RAYS il layout è
italiano, quindi «-», «/», «:» e simili finirebbero sbagliati. Qui ogni
carattere diventa lo scancode giusto per il layout italiano.

  vbox-tasti.py "nome vm" "testo da scrivere" [--invio]
"""
import subprocess
import sys

VBM = "/Applications/VirtualBox.app/Contents/MacOS/VBoxManage"

LETTERS = {c: s for c, s in zip(
    "qwertyuiopasdfghjklzxcvbnm",
    [0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,
     0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26,
     0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x32])}
DIGITS = {str(d): 0x02 + i for i, d in enumerate("1234567890")}

# carattere -> (scancode, shift?, altgr?)
SPECIAL = {
    " ": (0x39, False, False), "-": (0x35, False, False), "_": (0x35, True, False),
    ".": (0x34, False, False), ":": (0x34, True, False),
    ",": (0x33, False, False), ";": (0x33, True, False),
    "'": (0x0C, False, False), "?": (0x0C, True, False),
    "+": (0x1B, False, False), "*": (0x1B, True, False),
    "\\": (0x29, False, False), "|": (0x29, True, False),
    "/": (0x08, True, False), "(": (0x09, True, False), ")": (0x0A, True, False),
    "=": (0x0B, True, False), "\"": (0x03, True, False), "!": (0x02, True, False),
    "$": (0x05, True, False), "%": (0x06, True, False), "&": (0x07, True, False),
    "^": (0x0D, True, False),
    "@": (0x27, False, True), "#": (0x28, False, True),
    "[": (0x1A, False, True), "]": (0x1B, False, True),
    "{": (0x1A, True, True), "}": (0x1B, True, True),
    "~": (0x0D, False, True), "<": (0x56, False, False), ">": (0x56, True, False),
}


def codes_for(ch):
    if ch in LETTERS or ch.lower() in LETTERS:
        sc, shift, altgr = LETTERS[ch.lower()], ch.isupper(), False
    elif ch in DIGITS:
        sc, shift, altgr = DIGITS[ch], False, False
    elif ch in SPECIAL:
        sc, shift, altgr = SPECIAL[ch]
    else:
        return []
    out = []
    if shift:
        out += [0x2A]
    if altgr:
        out += [0xE0, 0x38]
    out += [sc, sc | 0x80]
    if altgr:
        out += [0xE0, 0xB8]
    if shift:
        out += [0xAA]
    return out


def main():
    vm, text = sys.argv[1], sys.argv[2]
    codes = []
    for ch in text:
        codes += codes_for(ch)
    if "--invio" in sys.argv[3:]:
        codes += [0x1C, 0x9C]
    if not codes:
        return 0
    # a blocchi: VBoxManage ha un limite di argomenti
    for i in range(0, len(codes), 60):
        chunk = codes[i:i + 60]
        subprocess.run([VBM, "controlvm", vm, "keyboardputscancode"]
                       + ["%02x" % c for c in chunk], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
