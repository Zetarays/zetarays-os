# Changelog

## 1.7 — 6 October 2026

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
- Printers: a new Settings › Printers page finds Wi-Fi, wired and USB
  printers on its own, adds them with one click (driverless IPP Everywhere,
  or the right driver for HP, Epson and Brother), prints a test page and
  can add a printer by its IP address.
- File manager: "Paste here as administrator" and "Open as administrator"
  for system folders such as /opt (asks for the password).
- One application registry for the whole system: the app menu, the Dock,
  search, the desktop and ZETA show the same apps with the same name and
  icon, from APT, Flatpak, AppImage or /opt.
- Right-click on an app (menu or search): open, open file location, add to
  the desktop or the Dock, information (source, version, package or Flatpak
  ID, executable, .desktop file, folder, architecture), remove from the menu,
  uninstall. System apps (ZETA, Files, Terminal, Settings...) are protected.
- Flatpak with Flathub ready; AppImages put in Applicazioni or Scaricati join
  the menu by themselves, with name and icon read without running them.
- Double-click a .deb or a .flatpakref to install it: what will be added,
  password, result, "Open" and "Add to Dock". Uninstalling never removes
  system components and cleans the desktop and Dock links.
- Change the icon of any app (right-click › Change icon…): the new icon is
  used everywhere, menu, Dock, search, desktop, Ctrl+Tab, and can be reset.
  Apps removed from outside (Synaptic, terminal) lose their Dock and desktop
  links by themselves; Dock icons follow app updates.
- Connect to a server: shared folders of Windows PCs, Macs and NAS (SMB),
  SSH (SFTP), FTP, WebDAV, NFS and older Macs (AFP), local or remote.
  Servers on the local network are found by themselves; favourites also
  appear in the file manager; passwords can be remembered in the keyring.

### Fixed
- Kernel panic in virtual machines with little memory (VMware Fusion, 768 MB):
  the boot archive (initramfs) went from 115–134 MB to 46–64 MB.
- The bottom bar could appear two or three times.
- Window title bars missing after a Debian library update.
- Wi-Fi said "wrong password" for a correct password (Vodafone Station).
- The first Firefox launch without internet showed an error page.
- Programs opened in a tiny window (file manager 640x480): main windows
  now open at a comfortable size, dialogs keep their own.
- Desktop: "Change icon" did nothing (both from the menu and from
  Properties).
- Desktop: links to programs in /opt (e.g. Blender, made with "Send to ›
  Desktop") did not start and had no icon.
- Network printers could not be added without a driver: ".local" names
  were not resolved.
- The clock could be two hours off (VMware Fusion, or next to Windows): the
  time is now synchronised from the internet, and from the host in VMware.
- The "3D acceleration not available" screen could open squeezed in a corner.
- Blender (official build) could open in a tiny window: Hyprland dropped the
  "start maximized" request made before the window appeared. Fixed in our
  Hyprland build, for every program that asks for it.
- Search: your own files could be missing from the results, pushed out by
  system files (/usr/bin, /usr/libexec...). Now your files come first, even
  ones created a second ago, each with the icon of its type; outside your
  home only external disks, /opt and /etc are shown.
- Search: one file with a non-UTF-8 name (old zip archives, Windows disks)
  stopped the content index for good; such files are now skipped.
- The search index timer of new users pointed to a file that did not exist.
