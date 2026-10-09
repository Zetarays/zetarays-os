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

## Commands

```bash
./build.sh arm64          # arm64 ISO -> out/zetarays-2.0-arm64.iso
./build.sh amd64          # amd64 ISO -> out/zetarays-2.0-amd64.iso
ZETA_ARCH=arm64 tools/make-ova.sh    # OVA from the ISO just built
tools/build-all-2.0.sh    # all four images, in order, stopping at the first error
```

`tools/build-all-2.0.sh` always starts from scratch and copies the four images
to the delivery folder (`~/Desktop/ZETA RAYS 2.0`, or `$ZETA_CONSEGNA`) only if
all of them were built. `tools/genera-readme.py` writes the README.txt of that
folder from `docs/README-2.0.txt.in`, filling in sizes, checksums and the
kernel version.

## What the build downloads (and checks)

These files are not in the repository because they are too large or generated:

| File | Source | Check |
|---|---|---|
| AI model llama3.2:1b (1.3 GB) | official Ollama registry (`tools/scarica-modello-ai.sh`) | SHA-256 from the manifest kept in the repository |
| Ollama runtime 0.40.0 | GitHub, official Ollama releases | installed and started in the image |
| Natural voice: Piper 2023.11.14-2, voices Paola (it) and Lessac (en) | GitHub and Hugging Face (`tools/scarica-voce.sh`) | SHA-256 pinned in the script |
| Speech recognition: Vosk models (it, en) and Python packages | alphacephei.com and PyPI (`tools/scarica-voce.sh`) | SHA-256 pinned for the models; the build installs without network |
| LocalSend (ZETA Share) | official LocalSend releases | SHA-256 pinned in `build.sh` |
| libhyprutils-dev 0.13.1 | snapshot.debian.org | SHA-1 pinned in `build.sh` |
| Hyprland 0.55.2 with fix #15416 | `tools/build-hyprland-zeta.sh` (compiled once) | `+zeta1` version checked during the build |

The Firefox start page is generated from the website
(`tools/genera-pagina-firefox.py`, after `tools/sito-font-libero.py` replaces
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
- LocalSend or Flathub is missing;
- a language offered in Settings > Language & Region did not compile.

If Python crashes while configuring packages (this happens at random under
amd64 emulation), `build.sh` resumes the configuration by itself, up to three
times.

## After the build

```bash
cd out && shasum -a 256 zetarays-2.0-*.iso zetarays-2.0-*.ova
```
