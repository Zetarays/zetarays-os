# ZETA RAYS terminology glossary

<!-- i18n-data-file: this glossary quotes Italian terms on purpose -->

One set of words for the operating system (English interface and its Italian
translation in `po/it.po`), the website (`site-zetarays/index.html`, English
and Italian), the README and the release notes. When a word appears in the
interface, documentation and the website must use the same word.

The source code uses the English term only: commands, files, modules and
settings keys are named after the English column (for example the
*Scrivania* is `zeta-desktop` and `desktop.json`, *Impostazioni* is
`zeta-settings`). The last column gives the name used in the source where
there is one.

## Rules

- **click** stays *click* in Italian too. Write "fai click", "fai click con il
  tasto destro", "doppio click", "un click". Never "clic", "clicca",
  "clicchi" or "clic destro".
- **right-click** (English, hyphenated as a verb and a noun) becomes "fai click
  con il tasto destro" (instruction) or "con il tasto destro" (description).
- **Support** stays *Support* in Italian for the project support link, button
  and heading ("Support ZETA RAYS", "Support the Project"). Do not use
  "Dona", "Donazioni" or "Donate". Use **Contribute** only for code,
  translations and bug reports.
- The project is written **ZETA RAYS** (operating system: **ZETA RAYS OS**);
  the assistant is **ZETA**, the agent **ZETA Core**.
- Menu paths use the single right-pointing angle quotation mark with spaces:
  `Settings › Displays`, `Impostazioni › Schermi`.
- American English spelling: color, center, license (noun and verb).
- No em dashes in website copy.

## Terms

| English (interface) | Italian (interface and site) | Notes | Source name |
|---|---|---|---|
| click / double-click | click / doppio click | see rules |  |
| right-click | fai click con il tasto destro | instruction form |  |
| Desktop | Scrivania | the desktop surface and the `Desktop` folder | `zeta-desktop` |
| Settings | Impostazioni | app name | `zeta-settings`, `org.zetarays.Settings` |
| Appearance | Aspetto | Settings page | `zeta-appearance` |
| Displays | Schermi | Settings page | `zeta-displays`, `system/displays.py` |
| Lock Screen | Schermata di blocco | Settings page |  |
| Account | Account | Settings page |  |
| accent color | colore d'accento | |  |
| wallpaper | sfondo | | `zeta-wallpaper`, `system/wallpapers.py` |
| Dock | Dock | | `zeta-dock` |
| bar | barra | the bottom system bar | `zeta-bar` |
| Control Center | Centro di controllo | | `zeta-control-center` |
| workspace | spazio di lavoro | | `zeta-workspaces` |
| minimize / maximize | riduci a icona / ingrandisci | | `zeta-minimize` |
| title bar | barra del titolo | |  |
| file manager | gestore file | Thunar |  |
| Text Editor | Editor di testo | GNOME Text Editor |  |
| Folder Color | Colore della cartella | right-click submenu | `zeta-folder-color`, `system/folder_colors.py` |
| Default (folder color) | Predefinito | |  |
| Trash / Empty Trash | Cestino / Svuota il cestino | |  |
| Main Display | Schermo principale | |  |
| Mirror | Duplica | display mode |  |
| Join Displays | Schermi uniti | display mode |  |
| Identify Displays | Identifica gli schermi | |  |
| Keep Changes / Revert | Mantieni / Torna indietro | display confirmation |  |
| Monitor (ZETA RAYS Monitor) | Monitor | app name | `zeta-monitor` |
| failed / attention / not applicable | errore / attenzione / non applicabile | Monitor service states |  |
| Download | Scarica | website |  |
| Support | Support | website, see rules |  |
| Security | Sicurezza | app and website section | `zeta-security` |
| live session | sessione dal vivo | system started from the USB stick |  |
