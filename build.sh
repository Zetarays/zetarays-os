#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds the ZETA RAYS ISO inside a Debian 13 container.
# Usage:  ./build.sh            -> amd64 ISO (Intel/AMD PCs)
#         ./build.sh arm64      -> arm64 ISO (to test it quickly on the Mac in a VM)
# Requires Docker (on the Mac: Colima with Rosetta).
set -euo pipefail

ARCH="${1:-amd64}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/out"
mkdir -p "$OUT"

# Release version: the VERSION file at the top of the repository is the only
# place where it is written (see docs/BUILD.md, "Version").
ZETA_VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION" 2>/dev/null || true)"
if ! [[ "$ZETA_VERSION" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
  echo "ERROR: VERSION is missing or not a version number (e.g. 2.1): '$ZETA_VERSION'" >&2
  exit 1
fi
ISO_NAME="zetarays-$ZETA_VERSION-$ARCH.iso"

python3 "$ROOT/tools/gen-assets.py"
# ZETA translations: every string shown by ZETA must have its translation,
# then po/*.po become the .mo files the system reads (never stale ones)
python3 "$ROOT/tools/i18n.py" check >/dev/null || { python3 "$ROOT/tools/i18n.py" check | tail -20; echo "ZETA RAYS: translations incomplete" >&2; exit 1; }
rm -f "$ROOT"/live-build/config/includes.chroot/usr/share/locale/*/LC_MESSAGES/zetarays.mo
python3 "$ROOT/tools/i18n.py" compile


# --- Local AI model (qwen3:4b-instruct): not stored in the repository (2.5 GB) ---
"$ROOT/tools/download-ai-model.sh" || { echo "ERROR: AI model not available" >&2; exit 1; }

# --- Ollama runtime: from the local cache, not from the network ---
# The AI engine used to be downloaded from GitHub on every build. When the
# download failed (slow network, GitHub unreachable) the hook carried on
# silently and the image came out with the model but without the engine: ZETA
# did not work, and the build still reported success. Now the runtime is
# downloaded ONCE into cache/ and goes into the image from there; the network
# is only needed the first time.
OLLAMA_CACHE="$ROOT/cache/ollama-linux-$ARCH.tar.zst"
OLLAMA_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/ollama-runtime.tar.zst"
if [ ! -s "$OLLAMA_CACHE" ]; then
  echo "Ollama runtime not cached for $ARCH: downloading it once…"
  mkdir -p "$ROOT/cache"
  curl -fL --retry 5 --retry-delay 3 --retry-all-errors --max-time 1800 \
       -o "$OLLAMA_CACHE.tmp" \
       "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-$ARCH.tar.zst" \
    && mv "$OLLAMA_CACHE.tmp" "$OLLAMA_CACHE" \
    || { rm -f "$OLLAMA_CACHE.tmp"; echo "ERROR: could not obtain the Ollama runtime for $ARCH." >&2; exit 1; }
fi
mkdir -p "$(dirname "$OLLAMA_DEST")"
cp -f "$OLLAMA_CACHE" "$OLLAMA_DEST"

# --- Voice: Kokoro and Piper (natural synthesis), Vosk (recognition), from the cache ---
# Same as Ollama: downloaded once into cache/ and from there into the image.
# On October 7 a transient DNS error during the download had left amd64
# without a voice: the build must not depend on the network.
case "$ARCH" in arm64) VOICE_ARCH=aarch64 ;; *) VOICE_ARCH=x86_64 ;; esac
PIPER_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/piper-cache"
VOSK_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/vosk-cache"
for f in "$ROOT/cache/piper/piper_linux_$VOICE_ARCH.tar.gz" "$ROOT/cache/vosk/$VOICE_ARCH" "$ROOT/cache/vosk/models" \
         "$ROOT/cache/piper/voices/it_IT-serena-high.onnx" \
         "$ROOT/cache/kokoro/kokoro-v1.0.int8.onnx" "$ROOT/cache/kokoro/voices-v1.0.bin"; do
  [ -e "$f" ] || { echo "ERROR: $f is missing (ZETA's voice): run tools/download-voice.sh" >&2; exit 1; }
done
ls "$ROOT"/cache/piper/voices/*.onnx >/dev/null 2>&1 || { echo "ERROR: the Piper voices are missing from cache/piper/voices" >&2; exit 1; }
rm -rf "$PIPER_DEST" "$VOSK_DEST"
mkdir -p "$PIPER_DEST/voices" "$PIPER_DEST/kokoro" "$VOSK_DEST"
# -X: without the Mac's extended attributes (they would end up in the image)
cp -X "$ROOT/cache/piper/piper_linux_$VOICE_ARCH.tar.gz" "$PIPER_DEST/"
cp -X "$ROOT"/cache/piper/voices/*.onnx "$ROOT"/cache/piper/voices/*.onnx.json "$PIPER_DEST/voices/"
cp -X "$ROOT"/cache/kokoro/kokoro-v1.0.int8.onnx "$ROOT"/cache/kokoro/voices-v1.0.bin "$PIPER_DEST/kokoro/"
cp -RX "$ROOT/cache/vosk/$VOICE_ARCH" "$ROOT/cache/vosk/models" "$VOSK_DEST/"

# --- Hyprland with the fix for the popup menu crash ---
# Built by tools/build-hyprland-zeta.sh (official Debian source + fix
# #15416). It stays in the image only for the duration of the build:
# hook 0350 installs it and hook 0400 deletes it.
HYPR_CACHE="$ROOT/cache/hyprland-zeta/$ARCH"
# libhyprutils-dev 0.13.1 (headers for hyprbars): from snapshot.debian.org
# when missing, checked against the SHA-1 checksum published by the archive
HU="$HYPR_CACHE/libhyprutils-dev_0.13.1-2~bpo13+1_$ARCH.deb"
case "$ARCH" in
  arm64) HU_SHA1=3694da8333b627317c59c8de87578a4490da456b ;;
  amd64) HU_SHA1=e87186879ee5ee33134ffeb38a9ad42d30e82c82 ;;
esac
if [ ! -s "$HU" ]; then
  mkdir -p "$HYPR_CACHE"
  curl -fsL --retry 3 -o "$HU.tmp" "https://snapshot.debian.org/file/$HU_SHA1" && mv "$HU.tmp" "$HU" \
    || { rm -f "$HU.tmp"; echo "ERROR: libhyprutils-dev could not be downloaded" >&2; exit 1; }
fi
echo "$HU_SHA1  $HU" | shasum -a 1 -c - >/dev/null || { echo "ERROR: wrong checksum for $HU" >&2; exit 1; }
HYPR_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/hyprland-patched"
rm -rf "$HYPR_DEST"; mkdir -p "$HYPR_DEST"
# libhyprutils-dev 0.13.1: the headers of the same hyprutils this Hyprland
# runs with (libhyprutils12). On October 3, 2026 the backports moved to 0.14,
# which does not build with Hyprland 0.55.2: hyprbars (the title bars) was
# skipped. Taken from snapshot.debian.org (SHA-1 checksum verified).
for p in hyprland hyprland-dev libaquamarine10 libaquamarine-dev libhyprutils-dev; do
  f=$(ls "$HYPR_CACHE"/${p}_*_"$ARCH".deb 2>/dev/null | head -1)
  [ -n "$f" ] || { echo "ERROR: $p is missing for $ARCH: run tools/build-hyprland-zeta.sh $ARCH" >&2; exit 1; }
  cp -f "$f" "$HYPR_DEST/"
done

# --- ZETA Share: LocalSend, official package from localsend.org -------------
# It is not in Debian: we use the .deb published by the authors, downloaded
# once into cache/ and checked against the SHA-256 checksum published on
# GitHub before every build. Hook 0360 installs it (with apt, which pulls in
# the dependencies).
LOCALSEND_VER=1.18.2
case "$ARCH" in
  arm64) LS_NAME=arm-64; LS_SHA=bbd8347b7979f936d3bae176a3f0d9b81431605707c585270d6240f7670feb1f ;;
  amd64) LS_NAME=x86-64; LS_SHA=cc42a4f3eacdcb25ec31f0016b1272acb003145ab30484db8965450e20c72cd2 ;;
esac
LS_FILE="LocalSend-$LOCALSEND_VER-linux-$LS_NAME.deb"
LS_CACHE="$ROOT/cache/localsend/$LS_FILE"
LS_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/localsend"
if [ ! -s "$LS_CACHE" ]; then
  mkdir -p "$(dirname "$LS_CACHE")"
  curl -fL --retry 5 --retry-delay 3 -o "$LS_CACHE.tmp" \
       "https://github.com/localsend/localsend/releases/download/v$LOCALSEND_VER/$LS_FILE" \
    && mv "$LS_CACHE.tmp" "$LS_CACHE" \
    || { rm -f "$LS_CACHE.tmp"; echo "ERROR: could not download LocalSend for $ARCH." >&2; exit 1; }
fi
echo "$LS_SHA  $LS_CACHE" | shasum -a 256 -c - >/dev/null 2>&1 \
  || { echo "ERROR: $LS_FILE does not match the official checksum: not using it." >&2; exit 1; }
rm -rf "$LS_DEST"; mkdir -p "$LS_DEST"
cp -f "$LS_CACHE" "$LS_DEST/"
# Cleanup on exit, in ONE single function. A «trap ... EXIT» replaces the
# previous one instead of adding to it: with two separate traps, on amd64 the
# colima one overrode this one, the 1.3 GB archive stayed in the sources and
# make-ova.sh copied it into the OVA disk.
RESTORE_BINFMT=0
VERSION_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/version"
cleanup() {
  rm -f "$OLLAMA_DEST"
  rm -f "$VERSION_DEST"
  rm -rf "$PIPER_DEST" "$VOSK_DEST"
  rm -rf "$HYPR_DEST"
  rm -rf "$LS_DEST"
  if [ "$RESTORE_BINFMT" = 1 ]; then
    colima ssh -- sudo sh -c "echo 1 > $BINFMT/rosetta; echo 0 > $BINFMT/qemu-x86_64" || true
  fi
}
trap cleanup EXIT

# Firefox start page: a copy of the website (site-zetarays/) without external
# resources and with links disabled; when online it switches by itself to
# https://zetarays.org/
# The online site uses Clash Display, whose license does not allow
# redistribution: the images get the copy with Syne (SIL OFL).
FREE_FONT_SITE="$ROOT/.cache/site-free-font"
python3 "$ROOT/tools/site-free-font.py" "$ROOT/site-zetarays" "$FREE_FONT_SITE" \
    || { echo "site copy with free font not generated"; exit 1; }
python3 "$ROOT/tools/gen-firefox-start-page.py" "$FREE_FONT_SITE" \
    "$ROOT/live-build/config/includes.chroot/usr/share/zetarays/start" \
    || { echo "Firefox start page not generated"; exit 1; }

# Same boot theme for the installation disk and the installed system, with
# English text in both: GRUB does not translate theme text, and English is
# the base language of ZETA RAYS (translations live in the apps).
# from scratch every time: files from a previous theme (icons, fonts of other
# sizes) must not remain in the image
rm -rf "${ROOT:?}/live-build/config/includes.chroot/usr/share/grub/themes/zeta"
mkdir -p "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta"
# the whole folder: fonts (.pf2), the selected-entry highlight and the logo
cp -Rf "$ROOT"/live-build/config/bootloaders/grub-pc/live-theme/. \
      "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta/"
grep -q 'Starting automatically in' "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta/theme.txt" \
    || { echo "GRUB theme of the installed system is not the expected one"; exit 1; }

# On a Mac with Apple silicon, amd64 uses the QEMU emulator instead of Rosetta:
# Rosetta does not work in the debootstrap chroot (/proc is missing).
BINFMT=/proc/sys/fs/binfmt_misc
if [ "$ARCH" = "amd64" ] && [ "$(uname -m)" = "arm64" ] && command -v colima >/dev/null; then
  colima ssh -- sudo sh -c "echo 0 > $BINFMT/rosetta; echo 1 > $BINFMT/qemu-x86_64"
  RESTORE_BINFMT=1   # cleanup() restores it on exit
fi

# The version for the image. Hooks run inside the chroot and cannot see the
# repository: they read /usr/share/zeta/version (written here, removed again
# by cleanup()); hook 0100 turns it into /etc/os-release, which is what the
# running system reads. auto/config and the container get it as ZETA_VERSION.
printf '%s\n' "$ZETA_VERSION" > "$VERSION_DEST"

docker run --rm --privileged \
  --platform "linux/$ARCH" \
  -e ZETA_ARCH="$ARCH" \
  -e ZETA_VERSION="$ZETA_VERSION" \
  -v "$ROOT/live-build:/src:ro" \
  -v "$OUT:/out" \
  -v "zetarays-cache-$ARCH:/build/cache" \
  debian:trixie bash -euxo pipefail -c '
    apt-get update
    apt-get install -y --no-install-recommends live-build debootstrap ca-certificates xorriso squashfs-tools dosfstools mtools
    cp -a /src/. /build/ && cd /build
    # Bytecode left over from tests on the development computer: it must not
    # end up in the image. It is compiled for a different Python version, is
    # useless, takes up space and confuses anyone reading the system.
    find config/includes.chroot -name __pycache__ -type d -prune -exec rm -rf {} + || true
    find config/includes.chroot -name "*.pyc" -delete || true
    chmod +x auto/config config/hooks/normal/*.hook.chroot config/includes.chroot/usr/local/bin/* config/includes.chroot/usr/lib/live/config/*
    # Version in the boot menu of the installation media (the theme of the
    # installed system is filled in by hook 0100)
    sed -i "s/@VERSION@/$ZETA_VERSION/g" config/bootloaders/grub-pc/live-theme/theme.txt
    if grep -q "@VERSION@" config/bootloaders/grub-pc/live-theme/theme.txt; then echo "GRUB theme: version not filled in"; exit 1; fi
    lb config
    # amd64 on an ARM Mac runs emulated (Rosetta or QEMU): sometimes python3.13
    # crashes (SIGSEGV) at random while dpkg configures a package, and the
    # whole build failed. If that happens: only the package configuration is
    # repeated («dpkg --configure -a», up to 5 times) and live-build resumes
    # from where it stopped (the stages already done stay marked in
    # .build/). Real errors (nonexistent package, broken hook) show up again
    # the same way and make it fail anyway.
    if ! lb build 2>&1 | tee /out/build-$ZETA_ARCH.log; then
      for attempt in 1 2 3; do
        echo "=== ZETA RAYS: build interrupted, resume no. $attempt ===" | tee -a /out/build-$ZETA_ARCH.log
        mount -t proc proc chroot/proc 2>/dev/null || true
        mount -t sysfs sys chroot/sys 2>/dev/null || true
        mount --bind /dev chroot/dev 2>/dev/null || true
        mount --bind /dev/pts chroot/dev/pts 2>/dev/null || true
        for round in 1 2 3 4 5; do
          chroot chroot env DEBIAN_FRONTEND=noninteractive dpkg --configure -a \
            >> /out/build-$ZETA_ARCH.log 2>&1 && break
          echo "=== dpkg --configure -a: round $round failed, retrying ===" | tee -a /out/build-$ZETA_ARCH.log
        done
        umount chroot/dev/pts chroot/dev chroot/sys chroot/proc 2>/dev/null || true
        if lb build 2>&1 | tee -a /out/build-$ZETA_ARCH.log; then break; fi
        [ "$attempt" = 3 ] && { echo "=== ZETA RAYS: build failed after 3 resumes ==="; exit 1; }
      done
    fi
    cp -v *.iso /out/zetarays-$ZETA_VERSION-$ZETA_ARCH.iso
  '

# --- Final check: the version from VERSION is the one in the image ---
if ! grep -q "ZETA RAYS: version $ZETA_VERSION written to os-release" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERROR: hook 0100 did not write version $ZETA_VERSION into the $ARCH image." >&2
  exit 1
fi

# --- Final check: the installer must be able to start ---
# Without the branding logo, Calamares exits immediately with an error and the
# user clicks "Install" with nothing happening. It really happened: the path in
# the hook had been left at the old name. Here we check that the file is there.
if ! grep -q "ZETA RAYS: installer logo generated" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERROR: installer logo missing from the $ARCH image." >&2
  echo "       Calamares would not start: «Install» would do nothing." >&2
  exit 1
fi

# --- Final check: secure boot must be in the image ---
# With shim, live-build also puts mm<arch>.efi (the key manager) in EFI/boot.
# If it is missing, the ISO does not boot on computers with Secure Boot
# enabled and the user is stuck without understanding why: better to fail here.
# live-build installs the signed packages by itself in the final stage, uses
# them and removes them; shim ends up in EFI/boot/boot<arch>.efi, so there is
# NO «shim*.efi» file to look for: the reliable signal is the line it prints.
if ! grep -q "UEFI Secure Boot support enabled" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERROR: secure boot not enabled in the $ARCH image." >&2
  echo "       On computers with Secure Boot enabled the ISO would not boot." >&2
  exit 1
fi
echo "Secure boot: enabled (signed shim as boot loader)"

# --- Final check: the image must contain the AI engine ---
# Better a build that fails than an image shipped with a mute ZETA.
if ! grep -q "ZETA RAYS: Ollama runtime installed" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERROR: the Ollama runtime does not appear to be installed in the $ARCH image." >&2
  echo "       The AI would not work. Build considered failed." >&2
  exit 1
fi

# --- Final check: ZETA's voice (natural synthesis and recognition) ---
for line in "ZETA RAYS: natural voice (Piper) installed" "ZETA RAYS: natural voice (Kokoro) installed" \
            "ZETA RAYS: vosk (python) installed" \
            "ZETA RAYS: speech model model-it installed" "ZETA RAYS: speech model model-en installed"; do
  if ! grep -q "$line" "$OUT/build-$ARCH.log" 2>/dev/null; then
    echo "ERROR: «$line» not found in the $ARCH log: ZETA would not speak or listen." >&2
    exit 1
  fi
done

# --- Final check: no packages left to upgrade (apt update + upgrade) ---
if ! grep -q "ZETA RAYS: packages upgraded, still upgradable: 0" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERROR: the package upgrade (hook 9990) does not appear to have completed in $ARCH." >&2
  exit 1
fi

echo "ISO ready: $OUT/$ISO_NAME"
