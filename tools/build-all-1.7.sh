#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Costruisce le quattro immagini di ZETA RAYS 1.7 e le copia nella cartella di
# consegna.
#
# Regole, imparate a proprie spese:
#  - si parte SEMPRE da zero. Prima, se una ISO arm64 esisteva già, veniva
#    riusata in silenzio: bastava che la cancellazione a mano non riuscisse e
#    si consegnava un'immagine vecchia accanto a tre nuove.
#  - al primo errore ci si ferma. Prima una OVA fallita veniva solo annotata,
#    e la consegna copiava le altre lasciando sulla Scrivania la OVA vecchia.
#  - si consegna solo se tutte e quattro sono riuscite, e ogni copia viene
#    confrontata con l'originale.
set -uo pipefail
# Il percorso si ricava dalla posizione di questo script invece di
# scriverlo a mano: così la cartella di lavoro sul Mac si può
# rinominare senza rompere nulla.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/out"
DEST="${ZETA_CONSEGNA:-$HOME/Desktop/ZETA RAYS 1.7}"
IMMAGINI="zetarays-1.7-arm64.iso zetarays-1.7-arm64.ova zetarays-1.7-amd64.iso zetarays-1.7-amd64.ova"
log() { echo "[$(date '+%H:%M:%S')] $*"; }
fallita() { log "FALLITA: $* — niente consegna, la cartella sulla Scrivania resta com'era"; exit 1; }

# «consegna»: solo la copia sulla Scrivania delle immagini gia' costruite e
# controllate in out/ (dopo una costruzione con SOLO_COSTRUZIONE=1)
if [ "${1:-}" = consegna ]; then
    for f in $IMMAGINI; do
        [ -s "$OUT/$f" ] || fallita "manca $f in out/"
    done
    SALTA_COSTRUZIONE=1
else
    SALTA_COSTRUZIONE=0
fi

# 1) nessuna costruzione in corso, niente immagini vecchie in giro
if [ "$SALTA_COSTRUZIONE" = 1 ]; then :; elif pgrep -f "build.sh (arm64|amd64)" >/dev/null || pgrep -f "make-ova.sh" >/dev/null; then
    fallita "c'è già una costruzione in corso"
fi
if [ "$SALTA_COSTRUZIONE" = 0 ]; then
for f in $IMMAGINI zetarays-1.7-arm64.vmdk zetarays-1.7-amd64.vmdk; do
    rm -f "$OUT/$f"
done
log "cartella out/ ripulita: si parte da zero"

# 2) le quattro immagini, in ordine; ognuna deve riuscire
log "costruisco la ISO arm64"
"$ROOT/build.sh" arm64 > "$OUT/run-arm64.log" 2>&1 || fallita "ISO arm64 (vedi run-arm64.log)"
log "ISO arm64 pronta ($(du -h "$OUT/zetarays-1.7-arm64.iso" | cut -f1))"

# Il disco virtuale di Colima non restituisce da solo lo spazio liberato:
# dopo la costruzione amd64 il Mac restava con un paio di GB e l'esportazione
# della OVA falliva per disco pieno. Si restituisce prima di ogni OVA.
libera_spazio() {
    command -v colima >/dev/null && colima ssh -- sudo fstrim -a >/dev/null 2>&1 || true
    log "spazio libero: $(df -h "$OUT" | awk 'NR==2{print $4}')"
}

libera_spazio
log "creo la OVA arm64"
ZETA_ARCH=arm64 "$ROOT/tools/make-ova.sh" > "$OUT/run-ova-arm64.log" 2>&1 || fallita "OVA arm64 (vedi run-ova-arm64.log)"
log "OVA arm64 pronta ($(du -h "$OUT/zetarays-1.7-arm64.ova" | cut -f1))"

libera_spazio
log "costruisco la ISO amd64"
"$ROOT/build.sh" amd64 > "$OUT/run-amd64.log" 2>&1 || fallita "ISO amd64 (vedi run-amd64.log)"
log "ISO amd64 pronta ($(du -h "$OUT/zetarays-1.7-amd64.iso" | cut -f1))"

libera_spazio
log "creo la OVA amd64"
ZETA_ARCH=amd64 "$ROOT/tools/make-ova.sh" > "$OUT/run-ova-amd64.log" 2>&1 || fallita "OVA amd64 (vedi run-ova-amd64.log)"
log "OVA amd64 pronta ($(du -h "$OUT/zetarays-1.7-amd64.ova" | cut -f1))"

for f in $IMMAGINI; do
    [ -s "$OUT/$f" ] || fallita "manca $f"
done

fi   # fine della costruzione (saltata con «consegna»)

# Con SOLO_COSTRUZIONE=1 ci si ferma qui: le immagini restano in out/ per il
# controllo completo, e si consegnano dopo con: tools/build-all-1.7.sh consegna
if [ "${SOLO_COSTRUZIONE:-0}" = 1 ]; then
    log "COSTRUITE — non consegnate: prima il controllo completo (immagini in $OUT)"
    exit 0
fi

# 3) consegna: copia sotto un nome provvisorio e poi rinomina, così un'
#    interruzione non lascia mai sulla Scrivania un file tagliato a metà
mkdir -p "$DEST"
for f in $IMMAGINI; do
    cp -f "$OUT/$f" "$DEST/.$f.parziale" || fallita "copia di $f"
    if [ "$(stat -f%z "$OUT/$f")" != "$(stat -f%z "$DEST/.$f.parziale")" ]; then
        rm -f "$DEST/.$f.parziale"; fallita "copia di $f incompleta"
    fi
    mv -f "$DEST/.$f.parziale" "$DEST/$f"
    log "copiato $f"
done
log "FATTO — immagini in $DEST"
ls -la "$DEST"
