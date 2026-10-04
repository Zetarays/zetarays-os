# ZETA RAYS OS

**Free · minimal · secure · intelligent.**
A free operating system based on Debian 13 (trixie): a clean black desktop
(Hyprland), security and pentesting tools, and **ZETA**, a local AI assistant
that understands you and runs the computer for you, with no account and no
internet required.

- Website: <https://zetarays.org>
- Download (ISO and VirtualBox OVA, amd64 and arm64): <https://zetarays.org/#download>
- Full user guide: [`docs/README-1.7.txt.in`](docs/README-1.7.txt.in) (the `README.txt` shipped with the images)

> This repository contains the **source** used to build ZETA RAYS OS, not the
> images themselves (3.4–3.9 GB each, too large for GitHub). Every release
> lists the SHA-256 checksums of the official images.

## What is inside

| Area | Where |
|---|---|
| ZETA, the local AI (Ollama, llama3.2:1b) and online providers | `live-build/config/includes.chroot/usr/lib/zeta/intelligence/` |
| Desktop: bar, launcher, control centre, settings, search | `live-build/config/includes.chroot/usr/local/bin/zeta-*`, `usr/lib/zeta/ui/` |
| Firewall (nftables), SSH, network | `includes.chroot/etc/nftables.conf`, `usr/local/bin/zeta-ssh` |
| Installer (Calamares) and boot menus | `includes.chroot/etc/calamares/`, `live-build/config/bootloaders/` |
| Package list | `live-build/config/package-lists/` |
| Build-time customisation | `live-build/config/hooks/normal/` |
| Build scripts, OVA, tests | `build.sh`, `tools/` |
| Documentation | `docs/` |

## Build it yourself

See [`docs/BUILD.md`](docs/BUILD.md). In short, on a machine with Docker:

```bash
./build.sh arm64      # or amd64
```

The build downloads what is too large for this repository (the AI model, the
Ollama runtime, LocalSend) and checks every file against a pinned checksum.

## Report a problem

Open an [issue](../../issues/new/choose). Please attach the output of
`sudo zeta-diagnosi` from the affected computer. Security issues: see
[`SECURITY.md`](SECURITY.md), do not open a public issue.

## Licence

- Code and configuration: **GPL-3.0-or-later** ([`COPYING`](COPYING)).
- ZETA RAYS name, logo and wallpapers: **not** under the GPL, see
  [`LICENSE-ARTWORK.md`](LICENSE-ARTWORK.md).
- Third-party software keeps its own licence (Debian packages, Hyprland,
  Ollama, the llama3.2 model, LocalSend, fonts: see `docs/` and the
  in-system legal notes).

---

## In italiano

ZETA RAYS OS è un sistema operativo libero basato su Debian 13: scrivania nera
e pulita, strumenti di sicurezza e un'intelligenza artificiale locale, ZETA,
che funziona senza account e senza internet. Questo repository contiene i file
con cui si **costruisce** il sistema; le immagini da scaricare sono su
<https://zetarays.org>. Per costruirlo: [`docs/BUILD.md`](docs/BUILD.md). Per
segnalare un problema: apri una *issue* allegando l'uscita di
`sudo zeta-diagnosi`.
