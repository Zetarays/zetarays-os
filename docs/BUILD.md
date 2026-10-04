# Costruire le immagini di ZETA RAYS OS

## Cosa serve

- Docker (su Mac: Colima, `colima start --memory 12 --cpu 8`).
- Circa 40 GB liberi.
- Per la OVA: VirtualBox (`VBoxManage`).
- Rete: la prima volta si scaricano i pacchetti Debian e i file grandi.

## Comandi

```bash
./build.sh arm64          # ISO arm64  → out/zetarays-1.7-arm64.iso
./build.sh amd64          # ISO amd64  → out/zetarays-1.7-amd64.iso
ZETA_ARCH=arm64 tools/make-ova.sh    # OVA dalla ISO appena costruita
tools/build-all-1.7.sh    # tutte e quattro, in ordine, fermandosi al primo errore
```

## Cosa scarica la costruzione (e controlla)

Questi file non stanno nel repository perché troppo grandi o generati:

| File | Da dove | Controllo |
|---|---|---|
| modello AI llama3.2:1b (1,3 GB) | registro ufficiale di Ollama (`tools/scarica-modello-ai.sh`) | SHA-256 del manifesto nel repository |
| runtime Ollama | GitHub, rilasci ufficiali di Ollama | presenza e avvio nell'immagine |
| LocalSend (ZETA Share) | rilasci ufficiali di LocalSend | SHA-256 fissato in `build.sh` |
| libhyprutils-dev 0.13.1 | snapshot.debian.org | SHA-1 fissato in `build.sh` |
| Hyprland 0.55.2 con la correzione #15416 | `tools/build-hyprland-zeta.sh` (da compilare una volta) | versione `+zeta1` verificata in costruzione |

La pagina iniziale di Firefox si genera dal sito (`tools/genera-pagina-firefox.py`,
con `tools/sito-font-libero.py` che usa il font libero Syne).

## Controlli automatici della costruzione

La costruzione si ferma da sola se: mancano le barre del titolo (hyprbars),
il pacchetto di avvio (initramfs) supera gli 80 MB, resta qualche pacchetto da
aggiornare, manca il logo dell'installer, l'avvio sicuro o il motore dell'AI,
o la pagina iniziale di Firefox. La costruzione amd64 su Mac Apple Silicon è
emulata: se Python va in crash mentre configura i pacchetti, `build.sh`
riprende da solo la configurazione.

## Dopo la costruzione

```bash
cd out && shasum -a 256 zetarays-1.7-*.iso zetarays-1.7-*.ova
```
