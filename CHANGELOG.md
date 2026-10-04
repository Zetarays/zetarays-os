# Changelog

## 1.7 — 4 October 2026

Images: `zetarays-1.7-{amd64,arm64}.{iso,ova}` on <https://zetarays.org>.

### New
- **ZETA**, local AI assistant (Ollama, llama3.2:1b) with optional online
  providers (Claude, Gemini, OpenAI, Mistral, Perplexity, Qwen…), fast
  defaults and automatic fallback to the local model without internet.
- Bar menus (logo, search, network, sound, power) open instantly.
- Remote access (SSH): on by default once installed, from the local network
  and from the internet (rate-limited, root never allowed); off in the live
  session and the OVAs. `zeta-ssh` with `stato`, `config`, `diagnosi`.
- Firewall in three classes: LAN ONLY, REMOTE ENABLED, DISABLED.
- Firefox start page: zetarays.org online, a local copy of the site offline.
- The USB stick starts in English; the language is chosen in the installer.
- Eight 4K wallpapers.

### Fixed
- Kernel panic in virtual machines with little memory (VMware Fusion, 768 MB):
  the boot archive (initramfs) went from 115–134 MB to 46–64 MB.
- The bottom bar could appear two or three times.
- Window title bars missing after a Debian library update.
- Wi-Fi said "wrong password" for a correct password (Vodafone Station).
- The first Firefox launch without internet showed an error page.
