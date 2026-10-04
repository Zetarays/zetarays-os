# ZETA RAYS Intelligence

Il livello AI di ZETA RAYS OS. Un'unica interfaccia per più provider, con azioni di
sistema controllate e memoria locale opzionale. Scritto in Python della libreria
standard: **nessuna dipendenza da installare** (le chiamate usano `urllib`).

## Provider

| Provider | Tipo | Endpoint |
|---|---|---|
| Claude (Anthropic) | cloud | `api.anthropic.com` — modello predefinito `claude-opus-5` |
| Gemini (Google) | cloud | `generativelanguage.googleapis.com` |
| OpenAI | cloud | `api.openai.com` |
| DeepSeek | cloud | `api.deepseek.com` |
| Qwen | cloud | DashScope (modalità compatibile OpenAI) |
| Ollama | locale | `127.0.0.1:11434` — rileva i modelli installati |

### Scelta automatica del provider

1. il provider scelto dall'utente, se pronto;
2. **Ollama**, se è in esecuzione con un modello locale (offline-first);
3. il primo provider cloud con una chiave configurata.

ZETA RAYS funziona quindi anche **senza Internet** se è presente un modello locale.

## Chiavi API

Le chiavi **non** sono mai nel codice né nei file di configurazione. Si salvano
nel portachiavi del sistema (Secret Service):

```bash
secret-tool store --label='ZETA RAYS claude' zeta-provider claude
```

oppure da **Impostazioni › AI**. La configurazione (modello, provider
predefinito) sta in `~/.config/zeta/intelligence.json`.

## Motore azioni (allowlist e permessi)

L'AI non esegue comandi shell arbitrari: può solo richiedere azioni definite,
ognuna con un livello di permesso.

| Livello | Ambito | Conferma |
|---|---|---|
| 0 | conversazione | no |
| 1 | lettura informazioni di sistema | no |
| 2 | azioni utente (aprire app, cercare file) | no |
| 3 | configurazione di sistema | **sì** |
| 4 | azioni amministrative/root | **sì** |

Le azioni di livello 3 e 4 restituiscono prima un'anteprima (comando, impatto,
permesso richiesto) e vengono eseguite solo dopo autorizzazione esplicita. Ogni
richiesta è registrata in `~/.local/share/zeta/actions.log`. I percorsi dei file
sono confinati alla cartella personale.

## Memoria

Locale per impostazione predefinita, in `~/.local/share/zeta/history.jsonl`.
Disattivabile; si può cancellare (`zeta --oblio`) o esportare. Nessun dato va nel
cloud se non come parte della richiesta al provider scelto.

## Uso

```bash
zeta                     conversazione interattiva
zeta "quanto spazio ho sul disco?"
zeta --provider claude   forza un provider
zeta --stato             stato dei provider
zeta --oblio             cancella la memoria
```

`zeta-core` apre l'interfaccia visiva a particelle.

## Sicurezza ed etica

L'AI distingue il lavoro di sicurezza autorizzato (difesa, test su sistemi
propri, ricerca, CTF) da attività potenzialmente dannose, che rifiuta. Non
attacca sistemi in autonomia e chiede sempre conferma per operazioni intrusive o
distruttive.
