# ZETA RAYS OS — che cosa esce dal tuo computer

Questo documento dice, senza giri di parole, quali dati lasciano il computer
quando usi ZETA RAYS OS, verso chi vanno e come fermarli.

## La regola

**ZETA RAYS non raccoglie nulla.** Non c'è telemetria, non c'è un server di
ZETA RAYS a cui il sistema manda statistiche, segnalazioni di errore o
abitudini d'uso. Il sistema non ha un account e non chiede di registrarsi.

Ciò che esce dal computer esce solo per fare una cosa che hai chiesto tu, e
qui sotto c'è l'elenco completo.

## 1. Aggiornamenti del sistema

**Dove**: `deb.debian.org`, `security.debian.org` e i loro mirror.
**Quando**: quando controlli gli aggiornamenti o installi programmi
(Impostazioni › Aggiornamento software, Synaptic, oppure `apt`). Su un sistema
installato anche una volta al giorno per gli aggiornamenti di sicurezza
automatici (attivi dopo l'installazione), e una volta a settimana se attivi il
promemoria degli aggiornamenti. Mai nella sessione live, se non lo chiedi tu.
**Che cosa**: quali pacchetti chiedi. Il tuo indirizzo IP è visibile al
server, come per qualunque scaricamento.
**Gli aggiornamenti di ZETA RAYS** arrivano da `zetarays.org/apt` allo stesso
modo e negli stessi momenti: prima di ogni controllo dei pacchetti il sistema
chiede a quell'indirizzo se l'archivio di ZETA RAYS c'è (una sola piccola
richiesta, senza dati su di te o sul computer) e lo usa solo se risponde.
**Si può evitare**: sì. Disattiva "Installa automaticamente gli aggiornamenti
di sicurezza" in Impostazioni › Aggiornamento software, e non aggiornare. È
sconsigliato: gli aggiornamenti portano le correzioni di sicurezza.

## 2. Assistente ZETA

**ZETA usa solo modelli di AI che funzionano sul tuo computer.** Da ZETA
RAYS 2.5 nel sistema non ci sono servizi di AI online: nessun modello remoto
di nessuna azienda, nessuna chiave API e
nessun ripiego sul cloud quando il modello locale è occupato o ha poca
memoria (in quel caso ZETA usa un modello locale più piccolo, oppure te lo
dice). Domande, risposte, conversazione, le cose che chiedi a ZETA di
ricordare, la tua voce e i tuoi file non escono mai dal computer. Funziona
anche senza rete.

Il modello gira in Ollama, che ascolta solo su `127.0.0.1` (questo computer)
e ha le sue funzioni cloud spente (`OLLAMA_NO_CLOUD=1`): i modelli "cloud" di
Ollama, che girerebbero su ollama.com, non si possono usare, e ZETA li
rifiuta.

**Scaricare un altro modello (solo se lo chiedi tu).** *Impostazioni › AI ›
Scarica un modello* prende i file del modello da `registry.ollama.ai` (la
libreria di Ollama). Parte solo il nome del modello, come in ogni download. I
modelli inclusi nell'immagine non richiedono download.

**Cercare informazioni aggiornate (acceso di serie).** Un modello conosce il
mondo solo fino alla data del suo addestramento. Per le domande su fatti
attuali (chi ricopre una carica, notizie, prezzi, versioni, meteo, risultati)
ZETA consulta prima fonti pubbliche, così la risposta è aggiornata. Solo
quelle domande: tutto il resto resta sul computer. Puoi spegnerlo con
l'interruttore in *Impostazioni › AI › Informazioni aggiornate*.

| Cosa | Dove va |
|---|---|
| La tua domanda, ridotta alle parole chiave | `it.wikipedia.org` o `en.wikipedia.org` (ricerca ed estratto della pagina) |
| La stessa, solo se accendi anche questa opzione | `api.duckduckgo.com` (risposte istantanee) |
| Una domanda su Linux o su un comando, ridotta alle parole chiave | `wiki.archlinux.org` (l'ArchWiki; la pagina di manuale del comando si legge sul computer) |

Parte solo la domanda: mai la conversazione, mai i tuoi file, nient'altro.
Nessun cookie viene conservato, le richieste si presentano come ZETA RAYS
(User-Agent) e si fermano dopo 5 secondi. Le fonti usate compaiono sotto la
risposta, con indirizzo e data. Con l'interruttore spento, o senza rete, ZETA
dice che i fatti attuali non si possono verificare.

Quello che ZETA ricorda sta in un solo file, `~/.local/share/zeta/memory.db`,
leggibile solo da te (permessi 600, cartella 700): l'ultima conversazione
(conservata 30 giorni, se non scegli diversamente), i ricordi a lungo termine
che hai chiesto e le fonti web di risposte precedenti. *Impostazioni › AI ›
Memoria* li elenca, li esporta e li cancella; `zeta --forget-all` li cancella
dal terminale. Niente viene ricordato a lungo termine se non lo chiedi tu.

Le versioni precedenti potevano conservare chiavi API di servizi online in
`~/.config/zeta/keys/`. ZETA RAYS 2.5 non le legge più; puoi cancellare quella
cartella.

## 3. Riconoscimento vocale

Avviene **sul tuo computer** con il motore Vosk e il modello italiano
installato nell'immagine. L'audio del microfono non esce dal computer e non
viene registrato su disco: viene trascritto e scartato.

## 4. Ricerca nei file e riconoscimento del testo

L'indice dei documenti e il riconoscimento del testo nelle immagini (OCR)
funzionano **solo in locale**, con Tesseract. L'indice sta in
`~/.cache/zeta/` e non esce dal computer. Lo stesso vale per «cosa c'è sullo
schermo?» e «Chiedi a ZETA di riassumere»: l'immagine della finestra viene
letta sul computer e cancellata subito, e il testo va solo al modello locale.

**La cronologia degli appunti** (Super+V) tiene le ultime 100 cose copiate in
`~/.cache/cliphist`, leggibile solo da te. Ciò che i gestori di password
segnano come password non viene mai salvato. L'interruttore nel pannello la
spegne e la cancella; «Cancella tutto» la svuota quando vuoi.

**Le catture e le registrazioni dello schermo** vengono salvate solo dove le
vedi (Immagini/Screenshots, Video/Screen recordings).

## 5. Monitor di sistema — posizione di rete

Questa è l'unica richiesta esterna che può sorprendere, quindi vale la pena
leggerla.

La pagina *Mappa* del Monitor mostra da dove risulta collegato il computer.
Per farlo interroga **`ipwho.is`**, un servizio esterno, che dal tuo indirizzo
IP pubblico ricava città, paese e operatore.

- **Che cosa viene inviato**: il tuo indirizzo IP pubblico (implicitamente,
  come in ogni connessione) o un indirizzo che chiedi tu esplicitamente.
- **Che cosa non viene inviato**: nessun dato del computer, nessun nome
  utente, nessun contenuto.
- **Quando**: solo quando apri il Monitor con quella funzione attiva.
- **Memoria**: il risultato resta in `~/.cache/zeta/geo.json` per non ripetere
  la richiesta.
- **Come fermarla**: la geolocalizzazione si disattiva dal Monitor stesso. Con
  quella spenta, nessuna richiesta parte.

Un `ping` verso un host che scrivi tu, sempre nel Monitor, contatta
ovviamente quell'host: è il senso del comando.

## 6. Navigatore web

Firefox ESR ha una propria informativa e propri collegamenti a Mozilla
(aggiornamenti, protezione dal tracciamento). ZETA RAYS non li modifica e non
li intercetta: vale l'informativa di Mozilla.

## 7. Sorveglianza della sicurezza (ZETA WATCH)

ZETA WATCH lavora **solo sul computer**. Legge i registri del sistema
(accessi, azioni da amministratore, nuovi utenti, firewall, porte aperte) e
scrive quello che trova in `/var/log/zeta-watch/`, leggibile solo dagli
amministratori. Nessun evento, nessun indirizzo e nessun registro viene
mandato da nessuna parte. Il blocco di un indirizzo dopo troppe password SSH
sbagliate avviene nel firewall del computer.

Due strumenti di sicurezza scaricano solo i propri dati, mai niente su di te:

- **ClamAV** (antivirus) aggiorna le firme dei virus da
  `database.clamav.net`, al massimo una volta al giorno e a bassa priorità,
  solo su un sistema installato.
- **Suricata** (sorveglianza della rete) non è installato di serie. Se lo
  accendi in *Impostazioni › ZETA WATCH*, viene installato da Debian e
  scarica le regole Emerging Threats Open da `rules.emergingthreats.net`.

I controlli contro i rootkit (rkhunter, chkrootkit) lavorano senza rete.

## Dove stanno i tuoi dati, sul computer

| Che cosa | Dove |
|---|---|
| Impostazioni della scrivania | `~/.config/zeta/` |
| Conversazioni e ricordi di ZETA | `~/.local/share/zeta/memory.db` |
| Che cosa ha fatto ZETA sul computer (password nascoste) | `~/.local/share/zeta/actions.log` |
| Indice della ricerca, cache | `~/.cache/zeta/` |
| Cronologia degli appunti | `~/.cache/cliphist/` |
| Catture e registrazioni | `~/Pictures/Screenshots/`, `~/Videos/Screen recordings/` |
| Registro degli accessi | `/var/lib/wtmpdb/` |
| Eventi di ZETA WATCH | `/var/log/zeta-watch/` (solo amministratori) |

Sono file tuoi, sul tuo disco. Si cancellano cancellandoli.

## Sistema live

Avviando da chiavetta o da immagine senza installare, **nulla viene scritto
sul disco del computer**: tutto sta in memoria e sparisce allo spegnimento.

---

*Ultimo aggiornamento: con ZETA RAYS OS 3.5.*
