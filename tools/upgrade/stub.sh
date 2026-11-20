#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# ZETA RAYS @TO@ upgrade for an installed ZETA RAYS @FROM@ (@ARCH@).
#
#   sudo bash @NAME@ --dry-run    show what would change, change nothing
#   sudo bash @NAME@              upgrade (asks before starting)
#
# Opened from the file manager (the file must be allowed to run as a
# program): a terminal window opens and the administrator password is asked
# by the system. Built by tools/make-upgrade.sh; the payload after the
# script is checked (SHA-256) before anything else.
set -u
ZU_OFFSET=@OFFSET@
ZU_SIZE=@SIZE@
ZU_SHA256=@SHA256@
ZU_TO=@TO@
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

# --- language: Italian or English (the table is filled in by make-upgrade.sh)
ZU_LANG=""
for a in "$@"; do
    case "$a" in --lang=*) ZU_LANG="${a#--lang=}" ;; esac
done
if [ -z "$ZU_LANG" ]; then
    case "${LANGUAGE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in
        it*) ZU_LANG=it ;;
        *) ZU_LANG=en ;;
    esac
fi
t() {
    if [ "$ZU_LANG" = it ]; then
        case "$1" in
            "@I18N@") ;;
        esac
    fi
    printf '%s' "$1"
}

GUI=0; ROOT_TEST=0; PASS=()
for a in "$@"; do
    case "$a" in
        --gui) GUI=1 ;;
        --lang=*) ;;
        --root=*|--root) ROOT_TEST=1; PASS+=("$a") ;;
        -h|--help)
            printf '%s\n' "$(t "ZETA RAYS upgrade. Options: --dry-run (show what would change), --yes (no questions).")"
            exit 0 ;;
        *) PASS+=("$a") ;;
    esac
done

# --- administrator rights -------------------------------------------------
if [ "$(id -u)" != 0 ] && [ "$ROOT_TEST" = 0 ]; then
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        # opened from the file manager: show the progress in a terminal window
        if command -v foot >/dev/null 2>&1 && [ -n "${WAYLAND_DISPLAY:-}" ]; then
            exec foot --app-id=zeta-upgrade --title="ZETA RAYS $ZU_TO" -- /bin/bash "$SELF" --gui --lang="$ZU_LANG" ${PASS[@]+"${PASS[@]}"}
        fi
        command -v notify-send >/dev/null 2>&1 && \
            notify-send "ZETA RAYS $ZU_TO" "$(t "Open a terminal and run:") sudo bash $SELF" 2>/dev/null
        exit 1
    fi
    if [ "$GUI" = 1 ]; then
        printf '\n%s\n\n' "$(t "The system asks for the administrator password to upgrade ZETA RAYS.")"
        pkexec /bin/bash "$SELF" --gui --lang="$ZU_LANG" ${PASS[@]+"${PASS[@]}"}
        rc=$?
        if [ "$rc" = 126 ] || [ "$rc" = 127 ]; then
            printf '%s\n' "$(t "Not authorized: nothing was changed.")"
        fi
        printf '\n%s' "$(t "Press Enter to close this window.")"
        read -r _
        exit "$rc"
    fi
    printf '%s\n' "$(t "Administrator rights needed: the password is asked by sudo.")"
    exec sudo /bin/bash "$SELF" --lang="$ZU_LANG" ${PASS[@]+"${PASS[@]}"}
fi

# --- check and unpack the payload -------------------------------------------
fail() {
    printf '%s\n' "$1" >&2
    exit 1
}
sum256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi; }
total=$(wc -c < "$SELF" | tr -d ' ')
[ "$((total - ZU_OFFSET))" = "$ZU_SIZE" ] \
    || fail "$(t "The file is incomplete (interrupted download?): download it again.")"
printf '%s\n' "$(t "Checking the file (SHA-256)...")"
have=$(tail -c +"$((ZU_OFFSET + 1))" "$SELF" | sum256 | cut -c1-64)
[ "$have" = "$ZU_SHA256" ] || fail "$(t "The file is damaged (wrong checksum): download it again.")"

W=$(mktemp -d /var/tmp/zeta-upgrade.XXXXXX) || fail "mktemp"
trap 'rm -rf "$W"' EXIT
tail -c +"$((ZU_OFFSET + 1))" "$SELF" | tar -xf - -C "$W" || fail "$(t "The file could not be unpacked: is there free space in /var/tmp?")"
(cd "$W" && while read -r sum name; do
    [ "$(sum256 < "$name" | cut -c1-64)" = "$sum" ] || exit 1
done < SHA256SUMS) || fail "$(t "The file is damaged (wrong checksum): download it again.")"

ARGS=(--bundle "$W" --lang="$ZU_LANG")
[ "$GUI" = 1 ] && ARGS+=(--gui)
python3 -I "$W/zeta_upgrade.py" "${ARGS[@]}" ${PASS[@]+"${PASS[@]}"}
exit $?
