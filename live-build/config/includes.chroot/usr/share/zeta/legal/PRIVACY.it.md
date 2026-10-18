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
**Si può evitare**: sì. Disattiva "Installa automaticamente gli aggiornamenti
di sicurezza" in Impostazioni › Aggiornamento software, e non aggiornare. È
sconsigliato: gli aggiornamenti portano le correzioni di sicurezza.

## 2. Assistente ZETA

ZETA funziona in due modi, e la differenza conta.

**Modello locale (predefinito).** Il modello locale gira **sul tuo
computer**. Le domande, le risposte e la cronologia non escono mai. Funziona
anche senza rete.

**Provider cloud (solo se ne scegli uno).** Se in *Impostazioni › AI*
inserisci una chiave API e scegli quel provider, le tue domande vengono
inviate a lui. ZETA non passa mai da solo a un servizio online: quando il
modello locale non può rispondere, può solo proporne uno nella chat, e la
domanda parte solo se accetti con un click, per quella domanda. Dove vanno i
dati:

| Provider | Dove vanno i dati |
|---|---|
| Claude (Anthropic) | `api.anthropic.com` |
| Gemini (Google) | `generativelanguage.googleapis.com` |
| OpenAI | `api.openai.com` |
| DeepSeek | `api.deepseek.com` |
| Qwen (Alibaba) | `dashscope-intl.aliyuncs.com` |
| Perplexity | `api.perplexity.ai` |
| Mistral | `api.mistral.ai` |
| Groq | `api.groq.com` |
| xAI Grok | `api.x.ai` |
| OpenRouter | `openrouter.ai` (che a sua volta inoltra al modello scelto) |
| Personalizzato | l'indirizzo che scrivi tu (se è `localhost`, resta sul computer) |

Da quel momento valgono le condizioni e l'informativa **di quel provider**,
non queste. ZETA RAYS non vede e non conserva nulla di quel traffico.
**Senza chiave API, nessuna di queste connessioni avviene.**

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

Parte solo la domanda: mai la conversazione, mai i tuoi file, nient'altro.
Nessun cookie viene conservato, le richieste si presentano come ZETA RAYS
(User-Agent) e si fermano dopo 5 secondi. Le fonti usate compaiono sotto la
risposta, con indirizzo e data. Con l'interruttore spento, o senza rete, ZETA
dice che i fatti attuali non si possono verificare.

Le chiavi API sono conservate nel portachiavi del sistema, se ce n'è uno
attivo; altrimenti in file cifrati leggibili solo da te, in
`~/.config/zeta/keys/` (permessi 600, cartella 700), come fanno ssh e
gli strumenti a riga di comando dei servizi cloud. Non compaiono nei registri,
nei rapporti di diagnosi né negli argomenti dei processi.

## 3. Riconoscimento vocale

Avviene **sul tuo computer** con il motore Vosk e il modello italiano
installato nell'immagine. L'audio del microfono non esce dal computer e non
viene registrato su disco: viene trascritto e scartato.

## 4. Ricerca nei file e riconoscimento del testo

L'indice dei documenti e il riconoscimento del testo nelle immagini (OCR)
funzionano **solo in locale**, con Tesseract. L'indice sta in
`~/.cache/zeta/` e non esce dal computer.

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

## Dove stanno i tuoi dati, sul computer

| Che cosa | Dove |
|---|---|
| Impostazioni della scrivania | `~/.config/zeta/` |
| Conversazioni con ZETA | `~/.local/share/zeta/` |
| Indice della ricerca, cache | `~/.cache/zeta/` |
| Chiavi API dei provider cloud | portachiavi del sistema |
| Registro degli accessi | `/var/lib/wtmpdb/` |

Sono file tuoi, sul tuo disco. Si cancellano cancellandoli.

## Sistema live

Avviando da chiavetta o da immagine senza installare, **nulla viene scritto
sul disco del computer**: tutto sta in memoria e sparisce allo spegnimento.

---

*Ultimo aggiornamento: con ZETA RAYS OS 2.0.*
