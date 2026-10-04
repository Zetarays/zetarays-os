# ZETA RAYS OS — Debranding

Elenco dei punti in cui l'identità della distribuzione di base è sostituita con
ZETA RAYS OS. Eseguito dall'hook `0100-zeta-branding.hook.chroot` (nel sistema) e da
`9000-zeta-disk.hook.binary` (sul supporto).

## Riscritti

| Punto | Prima | Dopo |
|---|---|---|
| `/etc/os-release`, `/usr/lib/os-release` | Debian GNU/Linux 13 | ZETA RAYS OS 1.7 (ID=zeta) |
| `/etc/issue`, `/etc/issue.net` | Debian GNU/Linux | ZETA RAYS OS 1.7 |
| `/etc/motd` | testo Debian | ZETA RAYS OS · AI · Sicurezza · Controllo |
| Prompt della shell | `utente@host` generico | `utente@zeta` con benvenuto ZETA RAYS |
| `/usr/share/pixmaps/debian-logo.png` | logo Debian | simbolo ZETA RAYS |
| GRUB `GRUB_DISTRIBUTOR` | Debian | ZETA RAYS OS |
| Menu di avvio (GRUB/syslinux) | grafica Debian | logo ZETA RAYS, voci in italiano |
| Tema di avvio (Plymouth) | tema Debian | logo ZETA RAYS animato |
| Schermata di accesso (SDDM) | tema generico | tema ZETA RAYS |
| `.disk/info` del supporto | Debian GNU/Linux ... | ZETA RAYS OS 1.7 ... |
| Impostazioni › Informazioni | riga "Debian" | solo dati ZETA RAYS |

## Riferimenti interni lasciati (non visibili all'utente)

Alcuni nomi di pacchetti e tipi-file contengono "debian" per necessità tecnica
(es. il tipo `application/x-debian-package` per il supporto ai pacchetti). Questi
NON compaiono nell'interfaccia e non vanno rimossi: romperebbero dipendenze.
