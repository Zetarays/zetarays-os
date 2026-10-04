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

**Dove**: `deb.debian.org` e i suoi mirror.
**Quando**: quando aggiorni o installi programmi (Pacchetti, oppure `apt`).
**Che cosa**: quali pacchetti chiedi. Il tuo indirizzo IP è visibile al
server, come per qualunque scaricamento.
**Si può evitare**: sì, non aggiornando — ma è sconsigliato: gli aggiornamenti
portano le correzioni di sicurezza.

## 2. Assistente ZETA

ZETA funziona in due modi, e la differenza conta.

**Modello locale (predefinito).** Il modello Llama 3.2 gira **sul tuo
computer**. Le domande, le risposte e la cronologia non escono mai. Funziona
anche senza rete.

**Provider cloud (solo se lo configuri tu).** Se in *Impostazioni › AI*
inserisci una chiave API, le tue domande vengono inviate al provider scelto:

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

Le chiavi API sono conservate nel portachiavi del sistema, se ce n'è uno
attivo; altrimenti in un file leggibile solo da te,
`~/.config/zeta/chiavi.json` (permessi 600, cartella 700), come fanno ssh e
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

*Ultimo aggiornamento: con ZETA RAYS OS 1.7.*
