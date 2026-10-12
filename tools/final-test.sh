#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Automatic final test of the arm64 image in VirtualBox: starts the VM,
# runs a sequence of checks and saves screenshots in .cache/vm/final-*.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VM="ZETA RAYS 2.0 (arm64)"
T="$ROOT/tools/vbox-keys.py"
P="$ROOT/tools/vbox-test.sh"
VBM=/Applications/VirtualBox.app/Contents/MacOS/VBoxManage

shot() { "$P" screenshot "final-$1" >/dev/null; echo "  screenshot: final-$1"; }
type_line() { "$T" "$VM" "$1" --enter; sleep "${2:-3}"; }
super_key() { "$VBM" controlvm "$VM" keyboardputscancode e0 5b "$1" "$2" e0 db; sleep "${3:-4}"; }

echo "== startup"
"$P" start || exit 1
sleep 95
shot 01-desktop

echo "== terminal (Super+Enter) and title bar"
super_key 1c 9c 5
shot 02-terminal

echo "== does the keyboard reach the window?"
type_line "echo KEYBOARD-OK" 3
shot 03-keyboard

echo "== title bar plugin"
type_line "hyprctl plugin list | head -4" 3
shot 04-hyprbars

echo "== files on the desktop"
type_line 'D=$(xdg-user-dir DESKTOP); mkdir -p "$D/Projects"; echo hello > "$D/notes.txt"; ls "$D"' 5
shot 05-icons

echo "== minimize and restore"
type_line "zeta-windows minimize" 4
shot 06-minimized
super_key 11 91 4          # Super+W
shot 07-windows-panel
"$VBM" controlvm "$VM" keyboardputscancode 01 81; sleep 2

echo "== light theme"
super_key 1c 9c 5
type_line "zeta-appearance set theme light" 12
shot 08-light-theme
super_key 1c 9c 6
shot 09-light-terminal
type_line "zeta-appearance set theme dark" 12
shot 10-dark-theme

echo "== fastfetch"
type_line "clear; fastfetch | head -20" 5
shot 11-fastfetch
type_line "echo zeta | sudo -S fastfetch | head -12" 6
shot 12-fastfetch-sudo

echo "done: screenshots in $ROOT/.cache/vm/final-*.png"
