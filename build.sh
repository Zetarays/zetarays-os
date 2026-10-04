#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Costruisce l'ISO di ZETA RAYS dentro un container Debian 13.
# Uso:  ./build.sh            -> ISO amd64 (PC Intel/AMD)
#       ./build.sh arm64      -> ISO arm64 (per provarla veloce sul Mac in una VM)
# Richiede Docker (sul Mac: Colima con Rosetta).
set -euo pipefail

ARCH="${1:-amd64}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/out"
mkdir -p "$OUT"

python3 "$ROOT/tools/gen-assets.py"


# --- Modello AI locale (llama3.2:1b): non sta nel repository (1,3 GB) ---
"$ROOT/tools/scarica-modello-ai.sh" || { echo "ERRORE: modello AI non disponibile" >&2; exit 1; }

# --- Runtime Ollama: dalla cache locale, non dalla rete ---
# Il motore dell'AI veniva scaricato da GitHub a ogni costruzione. Quando il
# download falliva (rete lenta, GitHub irraggiungibile) il hook proseguiva in
# silenzio e l'immagine usciva con il modello ma senza motore: ZETA non
# funzionava, e la costruzione dichiarava comunque successo. Ora il runtime si
# scarica UNA volta in cache/ e da li entra nell'immagine; la rete serve solo
# la prima volta.
OLLAMA_CACHE="$ROOT/cache/ollama-linux-$ARCH.tar.zst"
OLLAMA_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/ollama-runtime.tar.zst"
if [ ! -s "$OLLAMA_CACHE" ]; then
  echo "Runtime Ollama non in cache per $ARCH: lo scarico una volta sola…"
  mkdir -p "$ROOT/cache"
  curl -fL --retry 5 --retry-delay 3 --retry-all-errors --max-time 1800 \
       -o "$OLLAMA_CACHE.tmp" \
       "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-$ARCH.tar.zst" \
    && mv "$OLLAMA_CACHE.tmp" "$OLLAMA_CACHE" \
    || { rm -f "$OLLAMA_CACHE.tmp"; echo "ERRORE: impossibile procurarsi il runtime Ollama per $ARCH." >&2; exit 1; }
fi
mkdir -p "$(dirname "$OLLAMA_DEST")"
cp -f "$OLLAMA_CACHE" "$OLLAMA_DEST"

# --- Hyprland con la correzione del crash dei menu a comparsa ---
# Compilato da tools/build-hyprland-zeta.sh (sorgente Debian ufficiale +
# correzione #15416). Entra nell'immagine solo per il tempo della costruzione:
# lo installa il hook 0350 e lo cancella il hook 0400.
HYPR_CACHE="$ROOT/cache/hyprland-zeta/$ARCH"
# libhyprutils-dev 0.13.1 (intestazioni per hyprbars): da snapshot.debian.org
# se manca, con controllo dell'impronta SHA-1 pubblicata dall'archivio
HU="$HYPR_CACHE/libhyprutils-dev_0.13.1-2~bpo13+1_$ARCH.deb"
case "$ARCH" in
  arm64) HU_SHA1=3694da8333b627317c59c8de87578a4490da456b ;;
  amd64) HU_SHA1=e87186879ee5ee33134ffeb38a9ad42d30e82c82 ;;
esac
if [ ! -s "$HU" ]; then
  mkdir -p "$HYPR_CACHE"
  curl -fsL --retry 3 -o "$HU.tmp" "https://snapshot.debian.org/file/$HU_SHA1" && mv "$HU.tmp" "$HU" \
    || { rm -f "$HU.tmp"; echo "ERRORE: libhyprutils-dev non scaricabile" >&2; exit 1; }
fi
echo "$HU_SHA1  $HU" | shasum -a 1 -c - >/dev/null || { echo "ERRORE: impronta di $HU sbagliata" >&2; exit 1; }
HYPR_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/hyprland-corretto"
rm -rf "$HYPR_DEST"; mkdir -p "$HYPR_DEST"
# libhyprutils-dev 0.13.1: le intestazioni della stessa hyprutils con cui gira
# questo Hyprland (libhyprutils12). Il 3 ottobre 2026 i backports sono passati
# alla 0.14, che non compila con Hyprland 0.55.2: hyprbars (le barre del titolo)
# saltava. Preso da snapshot.debian.org (impronta SHA-1 controllata).
for p in hyprland hyprland-dev libaquamarine10 libaquamarine-dev libhyprutils-dev; do
  f=$(ls "$HYPR_CACHE"/${p}_*_"$ARCH".deb 2>/dev/null | head -1)
  [ -n "$f" ] || { echo "ERRORE: manca $p per $ARCH: lancia tools/build-hyprland-zeta.sh $ARCH" >&2; exit 1; }
  cp -f "$f" "$HYPR_DEST/"
done

# --- ZETA Share: LocalSend, pacchetto ufficiale di localsend.org ------------
# Non e' in Debian: si usa il .deb pubblicato dagli autori, scaricato una volta
# in cache/ e controllato con l'impronta SHA-256 pubblicata su GitHub prima di
# ogni costruzione. Lo installa il hook 0360 (con apt, che porta le dipendenze).
LOCALSEND_VER=1.18.2
case "$ARCH" in
  arm64) LS_NOME=arm-64; LS_SHA=bbd8347b7979f936d3bae176a3f0d9b81431605707c585270d6240f7670feb1f ;;
  amd64) LS_NOME=x86-64; LS_SHA=cc42a4f3eacdcb25ec31f0016b1272acb003145ab30484db8965450e20c72cd2 ;;
esac
LS_FILE="LocalSend-$LOCALSEND_VER-linux-$LS_NOME.deb"
LS_CACHE="$ROOT/cache/localsend/$LS_FILE"
LS_DEST="$ROOT/live-build/config/includes.chroot/usr/share/zeta/localsend"
if [ ! -s "$LS_CACHE" ]; then
  mkdir -p "$(dirname "$LS_CACHE")"
  curl -fL --retry 5 --retry-delay 3 -o "$LS_CACHE.tmp" \
       "https://github.com/localsend/localsend/releases/download/v$LOCALSEND_VER/$LS_FILE" \
    && mv "$LS_CACHE.tmp" "$LS_CACHE" \
    || { rm -f "$LS_CACHE.tmp"; echo "ERRORE: impossibile scaricare LocalSend per $ARCH." >&2; exit 1; }
fi
echo "$LS_SHA  $LS_CACHE" | shasum -a 256 -c - >/dev/null 2>&1 \
  || { echo "ERRORE: $LS_FILE non corrisponde all'impronta ufficiale: non lo uso." >&2; exit 1; }
rm -rf "$LS_DEST"; mkdir -p "$LS_DEST"
cp -f "$LS_CACHE" "$LS_DEST/"
# Pulizia all'uscita, in UNA sola funzione. Un «trap ... EXIT» sostituisce il
# precedente invece di aggiungersi: con due trap separati, per amd64 quello di
# colima cancellava questo, l'archivio da 1,3 GB restava nei sorgenti e
# make-ova.sh lo copiava nel disco della OVA.
RIPRISTINA_BINFMT=0
pulizia() {
  rm -f "$OLLAMA_DEST"
  rm -rf "$HYPR_DEST"
  rm -rf "$LS_DEST"
  if [ "$RIPRISTINA_BINFMT" = 1 ]; then
    colima ssh -- sudo sh -c "echo 1 > $BINFMT/rosetta; echo 0 > $BINFMT/qemu-x86_64" || true
  fi
}
trap pulizia EXIT

# Pagina iniziale di Firefox: copia del sito (sito-zetarays/) senza risorse
# esterne e con i link spenti; online passa da sola a https://zetarays.org/
# Il sito online usa Clash Display, che la sua licenza non permette di
# ridistribuire: nelle immagini va la copia con Syne (SIL OFL).
SITO_LIBERO="$ROOT/.cache/sito-font-libero"
python3 "$ROOT/tools/sito-font-libero.py" "$ROOT/sito-zetarays" "$SITO_LIBERO" \
    || { echo "copia del sito con font libero non generata"; exit 1; }
python3 "$ROOT/tools/genera-pagina-firefox.py" "$SITO_LIBERO" \
    "$ROOT/live-build/config/includes.chroot/usr/share/zetarays/start" \
    || { echo "pagina iniziale di Firefox non generata"; exit 1; }

# Stesso tema di avvio per il disco di installazione e per il sistema installato,
# ma con le scritte in lingua diversa: la chiavetta parla inglese (la lingua si
# sceglie poi nell'installer), il sistema installato resta in italiano.
mkdir -p "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta"
cp -f "$ROOT"/live-build/config/bootloaders/grub-pc/live-theme/* \
      "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta/"
sed -i.bak \
    -e 's/text = "Starting automatically in %d seconds"/text = "Avvio automatico tra %d secondi"/' \
    -e 's/text = "Arrows: choose · Enter: start · E: edit"/text = "Frecce: scegli · Invio: avvia · E: modifica"/' \
    "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta/theme.txt"
rm -f "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta/theme.txt.bak"
grep -q 'Avvio automatico tra' "$ROOT/live-build/config/includes.chroot/usr/share/grub/themes/zeta/theme.txt" \
    || { echo "tema GRUB del sistema installato non in italiano"; exit 1; }

# Sul Mac con chip Apple, per amd64 usa l'emulatore QEMU al posto di Rosetta:
# Rosetta non funziona nel chroot di debootstrap (manca /proc).
BINFMT=/proc/sys/fs/binfmt_misc
if [ "$ARCH" = "amd64" ] && [ "$(uname -m)" = "arm64" ] && command -v colima >/dev/null; then
  colima ssh -- sudo sh -c "echo 0 > $BINFMT/rosetta; echo 1 > $BINFMT/qemu-x86_64"
  RIPRISTINA_BINFMT=1   # lo rimette a posto pulizia() all'uscita
fi

docker run --rm --privileged \
  --platform "linux/$ARCH" \
  -e ZETA_ARCH="$ARCH" \
  -v "$ROOT/live-build:/src:ro" \
  -v "$OUT:/out" \
  -v "zetarays-cache-$ARCH:/build/cache" \
  debian:trixie bash -euxo pipefail -c '
    apt-get update
    apt-get install -y --no-install-recommends live-build debootstrap ca-certificates xorriso squashfs-tools dosfstools mtools
    cp -a /src/. /build/ && cd /build
    # Bytecode lasciato da prove sul computer di sviluppo: non deve finire
    # nella immagine. È compilato per una versione diversa di Python, non serve
    # a nulla, occupa spazio e confonde chi va a leggere il sistema.
    find config/includes.chroot -name __pycache__ -type d -prune -exec rm -rf {} + || true
    find config/includes.chroot -name "*.pyc" -delete || true
    chmod +x auto/config config/hooks/normal/*.hook.chroot config/includes.chroot/usr/local/bin/* config/includes.chroot/usr/lib/live/config/*
    lb config
    # amd64 su Mac ARM gira emulato (Rosetta o QEMU): a volte python3.13 va in
    # crash (SIGSEGV) mentre dpkg configura un pacchetto, a caso, e la
    # costruzione intera falliva. Se succede: si ripete solo la configurazione
    # dei pacchetti («dpkg --configure -a», fino a 5 volte) e live-build
    # riprende da dove si era fermato (le fasi gia fatte restano segnate in
    # .build/). Gli errori veri (pacchetto inesistente, hook rotto) si
    # ripresentano uguali e fanno fallire comunque.
    if ! lb build 2>&1 | tee /out/build-$ZETA_ARCH.log; then
      for tentativo in 1 2 3; do
        echo "=== ZETA RAYS: costruzione interrotta, ripresa n. $tentativo ===" | tee -a /out/build-$ZETA_ARCH.log
        mount -t proc proc chroot/proc 2>/dev/null || true
        mount -t sysfs sys chroot/sys 2>/dev/null || true
        mount --bind /dev chroot/dev 2>/dev/null || true
        mount --bind /dev/pts chroot/dev/pts 2>/dev/null || true
        for giro in 1 2 3 4 5; do
          chroot chroot env DEBIAN_FRONTEND=noninteractive dpkg --configure -a \
            >> /out/build-$ZETA_ARCH.log 2>&1 && break
          echo "=== dpkg --configure -a: giro $giro non riuscito, riprovo ===" | tee -a /out/build-$ZETA_ARCH.log
        done
        umount chroot/dev/pts chroot/dev chroot/sys chroot/proc 2>/dev/null || true
        if lb build 2>&1 | tee -a /out/build-$ZETA_ARCH.log; then break; fi
        [ "$tentativo" = 3 ] && { echo "=== ZETA RAYS: costruzione fallita dopo 3 riprese ==="; exit 1; }
      done
    fi
    cp -v *.iso /out/zetarays-1.7-$ZETA_ARCH.iso
  '

# --- Controllo finale: l'installer deve poter partire ---
# Senza il logo del branding, Calamares esce subito con un errore e l'utente
# clicca "Installa" senza che accada nulla. E successo davvero: il percorso nel
# hook era rimasto al vecchio nome. Qui si verifica che il file ci sia.
if ! grep -q "ZETA RAYS: logo dell.installer generato" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERRORE: logo dell'installer assente nell'immagine $ARCH." >&2
  echo "        Calamares non partirebbe: «Installa» non farebbe nulla." >&2
  exit 1
fi

# --- Controllo finale: l'avvio sicuro deve essere nell'immagine ---
# Con lo shim, live-build mette in EFI/boot anche mm<arch>.efi (il gestore
# delle chiavi). Se non c'e, la ISO non parte sui computer con Avvio Sicuro
# attivo e l'utente resta bloccato senza capire perche: meglio fallire qui.
# live-build installa da se i pacchetti firmati nella fase finale, li usa e li
# rimuove; lo shim finisce in EFI/boot/boot<arch>.efi, quindi NON esiste un
# file «shim*.efi» da cercare: il segnale affidabile e la riga che stampa.
if ! grep -q "UEFI Secure Boot support enabled" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERRORE: avvio sicuro non abilitato nell'immagine $ARCH." >&2
  echo "        Sui computer con Avvio Sicuro attivo la ISO non partirebbe." >&2
  exit 1
fi
echo "Avvio sicuro: abilitato (shim firmato come boot loader)"

# --- Controllo finale: l'immagine deve contenere il motore dell'AI ---
# Meglio una costruzione che fallisce di un'immagine consegnata con ZETA muto.
if ! grep -q "ZETA RAYS: runtime Ollama installato" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERRORE: il runtime Ollama non risulta installato nell'immagine $ARCH." >&2
  echo "        L'AI non funzionerebbe. Costruzione considerata fallita." >&2
  exit 1
fi

# --- Controllo finale: nessun pacchetto da aggiornare (apt update + upgrade) ---
if ! grep -q "ZETA RAYS: pacchetti aggiornati, ne restano da aggiornare: 0" "$OUT/build-$ARCH.log" 2>/dev/null; then
  echo "ERRORE: l'aggiornamento dei pacchetti (hook 9990) non risulta completato in $ARCH." >&2
  exit 1
fi

echo "ISO pronta: $OUT/zetarays-1.7-$ARCH.iso"
