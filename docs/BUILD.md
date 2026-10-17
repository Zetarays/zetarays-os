# Building the ZETA RAYS OS images

## Requirements

- Docker (on a Mac: Colima, `colima start --memory 16 --cpu 8`).
- About 40 GB of free disk space.
- For the OVA: VirtualBox (`VBoxManage`).
- Network: the first build downloads the Debian packages and the large files
  listed below; Flathub must be reachable.

On an Apple Silicon Mac the amd64 image is built under emulation (`build.sh`
switches Colima from Rosetta to QEMU for the build and back afterwards). It
needs free memory on the Mac itself: shut down test virtual machines before an
amd64 build. Giving Colima more than about 16 GB makes things worse, not
better.

## Version

The release version (e.g. `2.1`) is written in ONE place: the `VERSION` file
at the top of the repository. To make a new release, change that file and add
its section at the top of `CHANGELOG.md`; nothing else holds the number.

How it reaches every place that shows it:

- **Build scripts** (`build.sh`, `tools/build-all.sh`, `tools/make-ova.sh`,
  the `tools/vm-*.sh`/`tools/vbox-*.sh` helpers, `tools/gen-readme.py`,
  `tools/gen-release-notes.py`, `tools/sync-site.sh`) read `VERSION` directly:
  image names `zetarays-<VERSION>-<arch>.{iso,ova}`, the OVA name and product
  version, the delivery folder `~/Desktop/ZETA RAYS <VERSION>`.
- **live-build**: `build.sh` passes it to the container as `ZETA_VERSION`
  (`auto/config` uses it for the ISO volume label and image name) and writes
  it into the image as `/usr/share/zeta/version` before `lb build` (removed
  from the source tree again when the build ends). Hooks run inside the
  chroot and cannot see the repository, so they read that file.
- **Hook 0100** writes it into `/etc/os-release` (`VERSION_ID`, `VERSION`,
  `PRETTY_NAME`), `/etc/issue`, `/etc/issue.net` and `/etc/motd`, and fills
  the `@VERSION@` placeholders of the installer branding
  (`etc/calamares/branding/zeta/branding.desc`) and of the installed GRUB
  theme. The GRUB theme of the installation media
  (`bootloaders/grub-pc/live-theme/theme.txt`) is filled in by `build.sh`
  inside the container. Hook 0600 (license documents) reads
  `/etc/os-release`; hook 9000 (`.disk/info`) reads `ZETA_VERSION` or the
  version file.
- **The running system** never hard-codes it: Settings > About, ZETA's
  system information, the terminal greeting, fastfetch, `zeta system`,
  `zeta-diagnostics` and the HTTP User-Agent (`system/release.py`) read
  `/etc/os-release`.
- **The website** (`site-zetarays/index.html`) is static: its download links
  and version text are updated by hand for each release.

`python3 tools/check-version.py` (also run by CI) fails if a stale version is
left anywhere (image names, `releases/X.Y` links, "ZETA RAYS X.Y", "OS X.Y")
outside the history sections of `CHANGELOG.md`; the build stops if hook 0100
did not write the version from `VERSION` into the image.

## Commands

```bash
./build.sh arm64          # arm64 ISO -> out/zetarays-<VERSION>-arm64.iso
./build.sh amd64          # amd64 ISO -> out/zetarays-<VERSION>-amd64.iso
ZETA_ARCH=arm64 tools/make-ova.sh    # OVA from the ISO just built
tools/build-all.sh        # all four images, in order, stopping at the first error
```

`tools/build-all.sh` always starts from scratch and copies the four images
to the delivery folder (`~/Desktop/ZETA RAYS <VERSION>`, or `$ZETA_DELIVERY_DIR`)
only if all of them were built. `tools/gen-readme.py` writes the README.txt of
that folder from `docs/README.txt.in`, filling in the version, sizes,
checksums and the kernel version.

## What the build downloads (and checks)

These files are not in the repository because they are too large or generated:

| File | Source | Check |
|---|---|---|
| AI model qwen3:4b-instruct (2.5 GB) | official Ollama registry (`tools/download-ai-model.sh`) | SHA-256 from the manifest kept in the repository |
| Ollama runtime 0.40.0 | GitHub, official Ollama releases | installed and started in the image |
| Natural voice: Piper 2023.11.14-2, voices Paola (it) and Lessac (en) | GitHub and Hugging Face (`tools/download-voice.sh`) | SHA-256 pinned in the script |
| Speech recognition: Vosk models (it, en) and Python packages | alphacephei.com and PyPI (`tools/download-voice.sh`) | SHA-256 pinned for the models; the build installs without network |
| LocalSend (ZETA Share) | official LocalSend releases | SHA-256 pinned in `build.sh` |
| libhyprutils-dev 0.13.1 | snapshot.debian.org | SHA-1 pinned in `build.sh` |
| Hyprland 0.55.2 with fix #15416 | `tools/build-hyprland-zeta.sh` (compiled once) | `+zeta1` version checked during the build |

The Firefox start page is generated from the website
(`tools/gen-firefox-start-page.py`, after `tools/site-free-font.py` replaces
the website's font with the free Syne font). See [start-page.md](start-page.md).

## Automatic checks during the build

The build stops by itself if:

- a UI string has no Italian translation (`tools/i18n.py check`); the `.mo`
  catalogs are then compiled fresh from `po/*.po`;
- the Firefox start page or its policy is missing;
- the title bars (hyprbars) did not compile, or Hyprland is not the patched
  version;
- the boot archive (initramfs) is larger than 80 MB;
- some package is left to upgrade;
- the installer logo, Secure Boot support, the AI runtime or the AI model is
  missing;
- `VERSION` is missing, or the version was not written into the image;
- LocalSend or Flathub is missing;
- a language offered in Settings > Language & Region did not compile.

If Python crashes while configuring packages (this happens at random under
amd64 emulation), `build.sh` resumes the configuration by itself, up to three
times.

## After the build

```bash
cd out && shasum -a 256 zetarays-$(cat ../VERSION)-*.iso zetarays-$(cat ../VERSION)-*.ova
```
