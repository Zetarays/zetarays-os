# ZETA RAYS OS

**Free · minimal · secure · intelligent.**
A free operating system based on Debian 13 (trixie): a clean black desktop
(Hyprland), security and pentesting tools, and **ZETA**, a local AI assistant
that understands you and operates the computer for you, with no account and
no internet connection required.

- Website: <https://zetarays.org>
- Downloads (ISO and VirtualBox OVA, amd64 and arm64): <https://zetarays.org/#download>
- User guide: [`docs/README-2.0.txt.in`](docs/README-2.0.txt.in) (the `README.txt` shipped next to the images)
- Release notes: [`CHANGELOG.md`](CHANGELOG.md)

> This repository contains the **source** used to build ZETA RAYS OS, not the
> images themselves (about 4 GB each, too large for GitHub). Every release
> lists the SHA-256 checksums of the official images.

## Supported architectures

| Architecture | Images | Tested on |
|---|---|---|
| amd64 (x86-64) | ISO (UEFI and BIOS), OVA | QEMU (emulated) and real PCs |
| arm64 (AArch64) | ISO (UEFI), OVA | VirtualBox 7.2 on Apple Silicon, QEMU |

## System requirements

|  | Minimum | Recommended |
|---|---|---|
| Processor | 64-bit (x86-64 or ARM64) | 4 cores or more |
| Memory | 4 GB | 8 GB (16 GB keeps the AI model loaded) |
| Disk | 15 GB free | 20 GB free or more |
| Firmware | UEFI or BIOS (amd64) | UEFI with Secure Boot |

## Main features

- Hyprland desktop with title bars, a dock, a Control Center and a desktop
  with free or grid icon placement. Windows always keep their title bar
  within reach (SUPER + SHIFT + W brings every window back).
- **Settings**, including **Displays** (resolution, refresh rate, scale,
  rotation, arrangement, mirroring, main display, with automatic revert)
  and per-display memory.
- **Folder colors**: right-click a folder › Folder Color (red, white, green,
  blue, purple, default), on the desktop and in the file manager.
- **ZETA**, a local AI (Ollama with Llama 3.2) that acts on the system, with
  confirmations for destructive actions and no unrestricted root access;
  optional online providers with your own key.
- Security center, real-time Monitor, nftables firewall on by default, SSH
  with root login disabled.
- English interface with a complete Italian translation (gettext, `po/`) and
  35 selectable languages.

## Repository layout

| Area | Where |
|---|---|
| ZETA (local AI, agent, online providers) | `live-build/config/includes.chroot/usr/lib/zeta/intelligence/` |
| Desktop apps: bar, launcher, Control Center, Settings, search, Monitor | `includes.chroot/usr/local/bin/zeta-*`, `usr/lib/zeta/ui/`, `usr/lib/zeta/monitor/` |
| System logic (displays, folder colors, network, power, apps) | `includes.chroot/usr/lib/zeta/system/` |
| Hyprland configuration (window guard, rules, shortcuts) | `includes.chroot/etc/skel/.config/hypr/` |
| Firewall (nftables), SSH | `includes.chroot/etc/nftables.conf`, `usr/local/bin/zeta-ssh` |
| Installer (Calamares) and boot menus | `includes.chroot/etc/calamares/`, `live-build/config/bootloaders/` |
| Package list | `live-build/config/package-lists/` |
| Build-time customization (hooks) | `live-build/config/hooks/normal/` |
| Build scripts, OVA, checks | `build.sh`, `tools/` |
| Translations | `po/` |
| Documentation | `docs/` |

The source is entirely in English: command and file names (for example
`zeta-desktop`, `zeta-settings`, `system/displays.py`), identifiers, comments
and developer messages. Italian appears only as translation data (`po/it.po`,
`*.it.md`, `Name[it]=` entries, Italian voice and text command patterns).
Earlier builds used some Italian command and file names; the settings of a
user coming from one of them are converted automatically at the first login
(files under `~/.config`, shortcuts, Dock, desktop entries), see
[`CHANGELOG.md`](CHANGELOG.md).

## Building

See [`docs/BUILD.md`](docs/BUILD.md). In short, on a machine with Docker:

```bash
./build.sh arm64      # or amd64
```

The build downloads what is too large for this repository (the AI model, the
Ollama runtime, the voices, LocalSend) and checks every file against a pinned
checksum. It stops by itself if a translation is missing, a key component did
not install, or the boot archive is too large.

### Dependencies

- Build host: Docker (on a Mac: Colima), about 40 GB of free disk space,
  VirtualBox (`VBoxManage`) for the OVA images.
- Image: Debian 13 packages listed in `live-build/config/package-lists/`,
  Hyprland 0.55.2 from the official Debian backports (rebuilt with an upstream
  fix, see `tools/build-hyprland-zeta.sh`), and the pinned downloads listed in
  `docs/BUILD.md`.

## Checks and tests

| Check | Command |
|---|---|
| Shell and Python syntax, firewall syntax, secrets (CI) | `.github/workflows/checks.yml` |
| Every UI string has an Italian translation | `python3 tools/i18n.py check` |
| No Italian prose in code comments and developer docs | `python3 tools/check-italian.py` |
| A comment translation did not change code | `python3 tools/check-translation-safety.py OLD NEW` |
| `pkill -f`/`pgrep -f` patterns cannot hit another program | `python3 tools/check-process-names.py` |
| Website source, before a release (the site is a separate repository) | `python3 tools/check-site.py PATH/index.html` |
| Built-in tests on a running system (68+) | `zeta-selftest` (inside ZETA RAYS) |

## Troubleshooting

The user guide has a full troubleshooting section
([`docs/README-2.0.txt.in`](docs/README-2.0.txt.in), section 9). The most
useful command on an affected computer is:

```bash
sudo zeta-diagnostics
```

It collects the state of the desktop, network, firewall and services without
passwords. ZETA RAYS Monitor › Services shows each service as running,
completed, stopped, not applicable, needing attention (a periodic job that
failed) or failed.

## Reporting a problem

Open an [issue](../../issues/new/choose) and attach the output of
`sudo zeta-diagnostics`. Security issues: see [`SECURITY.md`](SECURITY.md) and
do not open a public issue. Contributions: see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

- Code and configuration: **GPL-3.0-or-later** ([`COPYING`](COPYING)).
- ZETA RAYS name, logo and wallpapers: **not** under the GPL, see
  [`LICENSE-ARTWORK.md`](LICENSE-ARTWORK.md).
- Third-party software keeps its own license (Debian packages, Hyprland,
  Ollama, the Llama 3.2 model, LocalSend, fonts): see `docs/` and the legal
  notes inside the system (`/usr/share/zeta/legal/`).
