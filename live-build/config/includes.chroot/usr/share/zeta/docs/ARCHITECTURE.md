# ZETA RAYS OS — Architettura

ZETA RAYS OS è un sistema operativo con identità propria. Internamente si appoggia a
componenti Linux collaudati, ma l'esperienza utente è interamente ZETA RAYS: nessun
riferimento alla distribuzione di base compare in avvio, accesso, desktop,
terminale, impostazioni o documentazione.

## Pilastri

**AI · Sicurezza · Controllo.** Tre sottosistemi nativi: ZETA RAYS Intelligence
(assistente multi-provider), ZETA RAYS Security (centro di sicurezza) e un livello di
permessi che tiene l'utente sempre al comando delle azioni sensibili.

## Struttura del progetto

```
ZETA RAYS/
├── live-build/        configurazione per costruire l'ISO
│   └── config/includes.chroot/
│       ├── usr/lib/zeta/           sottosistemi ZETA RAYS
│       │   ├── intelligence/       ZETA RAYS Intelligence (AI)
│       │   │   └── providers/      Claude, Gemini, OpenAI, DeepSeek, Qwen, Ollama
│       │   └── security/           ZETA RAYS Security (audit)
│       ├── usr/local/bin/          comandi: zeta, zeta-core, zeta-sicurezza,
│       │                           zeta-impostazioni, zeta-accent, zeta-launcher...
│       ├── usr/share/zeta/         marchio, shell, stato, documentazione
│       └── etc/skel/.config/       configurazione predefinita dell'utente
├── tools/             generatori di asset e script di prova/costruzione
├── brand/             logo e simbolo ZETA RAYS (SVG)
├── docs/              questa documentazione
└── build.sh           costruisce l'ISO
```

## Interfaccia

| Parte | Componente | Ruolo |
|---|---|---|
| Finestre | Hyprland (Wayland) | gestore finestre, effetti, animazioni |
| Barra e dock | Waybar | barra in basso con dock e stato |
| Launcher | app ZETA RAYS (GTK4) | ricerca e avvio app a tutto schermo |
| Accesso | SDDM (tema ZETA RAYS) | schermata di login |
| Avvio | Plymouth (tema ZETA RAYS) | logo animato all'accensione |
| Impostazioni | app ZETA RAYS (GTK4/Adwaita) | aspetto, AI, sicurezza, sistema |
| Assistente | ZETA RAYS Intelligence | assistente di sistema (testo e voce) |
| ZETA | GTK4 + Cairo | interfaccia AI a particelle |
| Barre del titolo | hyprbars (compilato in build) | chiudi · riduci · ingrandisci su ogni finestra |
| Finestre ridotte | `zeta-finestre` | elenco finestre aperte e ridotte a icona |
| Scrivania | `zeta-scrivania` | file, cartelle e icone sullo sfondo |
| Ricerca | `zeta-cerca` | app, azioni, nomi di file e contenuto (OCR compreso) |
| Aspetto | `zeta-aspetto` + `zeta-accent` | tema chiaro/scuro, testo, icone, cursore, scala |

## Scorciatoie da tastiera

| Tasti | Azione |
|---|---|
| `Super` | Launcher delle applicazioni |
| `Super + S` | Ricerca (app, azioni, file, contenuto) |
| `Super + W` | Finestre aperte e ridotte a icona |
| `Super + H` | Riduci a icona la finestra attiva |
| `Super + M` | Ingrandisci / ripristina la finestra attiva |
| `Super + Q` | Chiudi la finestra attiva |
| `Super + F` | Schermo intero |
| `Super + V` | Finestra fluttuante / affiancata |
| `Super + Invio` | Terminale |
| `Super + E` | Gestore file |
| `Super + I` | Impostazioni |
| `Super + T` | Tema chiaro / scuro |
| `Super + Maiusc + T` | Testo da una zona dello schermo (OCR), copiato negli appunti |
| `Ctrl + Alt + Esc` | Uscita forzata: mirino, si clicca la finestra bloccata (sfondo = elenco completo, anche senza finestra) |
| `Ctrl + Maiusc + Esc` | Emergenza: chiude subito la finestra attiva, senza interfaccia |
| `Super + A` | Centro di controllo |
| `Super + L` | Blocca lo schermo |
| `Super + Esc` | Menu di energia |
| `Super + 1…3` | Cambia scrivania |

Sulla scrivania le icone si usano con il mouse: doppio clic per aprire, tasto
destro per rinominare, cestinare, creare cartelle e documenti, e per cambiare
l'icona di un collegamento («Cambia icona…», anche dalle Proprietà): l'immagine
scelta viene copiata in `~/.local/share/zeta/icone`, così resta al suo posto
anche se l'originale viene spostato o cancellato. Non usa la
tastiera di proposito: una superficie a tutto schermo che tenesse il fuoco
impedirebbe di scrivere in qualsiasi altra finestra.

## Astrazione della base

Il debranding avviene in tre punti:

1. **Hook di costruzione** (`0100-zeta-branding`): riscrive `os-release`,
   `issue`, `motd`, il prompt della shell, il logo di sistema e il tema di avvio.
2. **Menu di avvio** (`bootloaders/`): logo ZETA RAYS e voci in italiano.
3. **`.disk/info`** (`9000-zeta-disk`): il supporto si presenta come ZETA RAYS OS.

Vedi [BRANDING.md](BRANDING.md) per l'elenco completo dei punti riscritti.
