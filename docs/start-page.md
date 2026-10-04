# Pagina iniziale di Firefox in ZETA RAYS OS

## Come funziona

Firefox ESR apre come pagina iniziale un file **locale**, installato nel sistema:

    file:///usr/share/zetarays/start/index.html

- **Con internet**: la pagina controlla che `https://zetarays.org/` risponda
  davvero (una richiesta `HEAD` con 2,5 secondi di tempo massimo) e passa da
  sola al sito online. Avere un cavo o il Wi-Fi collegati non basta: si
  controlla la risposta del sito.
- **Senza internet** (o se il sito non risponde): resta sulla copia locale del
  sito, con lo stesso aspetto e gli stessi testi, ma **con tutti i link spenti**
  (non si possono cliccare) e una piccola nota «Copia offline di zetarays.org ·
  link disattivati». La pagina d'errore di Firefox non compare mai.

La copia locale non carica nulla da internet: niente Google Fonts (JetBrains
Mono e Roboto sono installati nel sistema), font Clash Display e miniature
degli sfondi copiati accanto alla pagina.

## Da dove viene

La pagina **non si modifica a mano**: la genera, a ogni costruzione delle
immagini, `tools/genera-pagina-firefox.py` partendo da `sito-zetarays/`
(chiamato da `build.sh`). Così è sempre uguale al sito che si pubblica:

    python3 tools/genera-pagina-firefox.py sito-zetarays \
        live-build/config/includes.chroot/usr/share/zetarays/start

Lo script toglie i collegamenti a Google Fonts e il `canonical`, toglie
`href`/`target` da tutti i link (anche da quelli nei testi in inglese), aggiunge
il controllo «online → zetarays.org» e si ferma con un errore se nella pagina
resta una risorsa esterna.

## Politica di Firefox

`live-build/config/includes.chroot/usr/share/firefox-esr/distribution/policies.json`

In Debian `/usr/lib/firefox-esr/distribution` è un collegamento a
`/usr/share/firefox-esr/distribution`: il file sta nella cartella vera, così il
collegamento del pacchetto resta intatto e Firefox lo legge dal percorso
consueto.

```json
{
  "policies": {
    "Homepage": {
      "URL": "file:///usr/share/zetarays/start/index.html",
      "StartPage": "homepage",
      "Locked": false
    }
  }
}
```

`Locked: false`: l'utente può cambiare la pagina iniziale nelle impostazioni di
Firefox. `OverrideFirstRunPage` e `OverridePostUpdatePage` vuoti: al primo avvio
e dopo un aggiornamento Firefox apre la pagina di ZETA RAYS invece delle sue
pagine di benvenuto. In `/etc/firefox-esr/zeta-rays.js` (valori predefiniti,
modificabili) sono spente la pagina «about:welcome» e la scheda
dell'informativa sulla privacy, che senza rete finiva su una pagina d'errore.
Hyprland apre la finestra principale di Firefox all'80% dello schermo (regola
`zeta-browser-misura`), così la pagina si vede intera fin dal primo avvio.

## Controlli automatici

- l'hook `0100-zeta-branding.hook.chroot` ferma la costruzione se mancano
  `index.html` o `policies.json`, o se la politica non punta alla pagina;
- l'ispezione della ISO (`ispeziona-iso.sh`) controlla pagina, font, assenza di
  risorse esterne, politica e collegamento di Debian.

## Lato server

Non serve nulla di speciale: la verifica usa una richiesta `no-cors`, quindi
**non** servono intestazioni CORS. Serve solo che il sito sia pubblicato.

**Da fare (TODO)**: oggi (3 ottobre 2026) `https://zetarays.org/` rimanda a
`https://www.zetarays.org/`, che mostra ancora la pagina di cortesia di Aruba.
Finché non si caricano i file di `sito-zetarays.org/`, con internet Firefox
mostra quella pagina.

## Come provarla

1. **Con rete**: avvia Firefox → si apre la pagina locale e, in un attimo,
   `www.zetarays.org`.
2. **Senza rete** (Wi-Fi spento o cavo staccato): avvia Firefox → copia
   locale del sito, nota «Copia offline», i link non reagiscono ai clic.
3. **Politica attiva**: scrivi `about:policies` nella barra degli indirizzi:
   deve comparire «Homepage» con l'URL qui sopra.
4. **Cambio manuale**: Impostazioni di Firefox › Pagina iniziale › scegli
   un'altra pagina: viene accettata (la politica non è bloccata).

Provato con un profilo nuovo (primo avvio vero) e senza rete: una sola
scheda, la copia del sito, finestra grande, nessuna pagina d'errore.
