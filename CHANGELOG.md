# Changelog

## 2.0 — 7 October 2026

Images: `zetarays-2.0-{amd64,arm64}.{iso,ova}` on <https://zetarays.org>.

### Highlights of 2.0
- **Windows always within reach**: a window moved off the screen by its
  program, larger than the screen, or left outside after a display was
  unplugged or changed comes back with its title bar and buttons inside the
  usable area (above the bar), inside Hyprland itself, without fighting a
  window you are dragging and without loops when a program refuses a size.
  SUPER + SHIFT + W brings every window back. Root cause of the X11 case:
  Hyprland computes a move or resize as a difference from the window's
  reported size but applies it to its own layout box, which a program that
  resized itself had left behind (a first resize could even give negative
  sizes). Menus of the bar (Dock, Mail, minimized windows) now open on the
  display under the pointer and always inside it.
- **Settings > Displays**: resolution (native marked), refresh rate, scale
  (only values Hyprland accepts and that leave a usable desktop),
  orientation, brightness of a laptop panel, a drag-and-drop map, join,
  mirror or a single display, main display, Identify, details. Apply checks
  the real state and asks to keep the change, reverting by itself after 15
  seconds; settings are remembered per display (make, model, serial). The
  bar and the wallpaper follow a display that moved (Hyprland left them at
  the old position).
- **Lock screen plain black** on every display, also when waking from sleep:
  sleep now waits until the lock is on screen; no wallpaper and no logo on
  the lock and login screens.
- **Account picture**: a plain circle in one of the four accent colors
  (blue, red, green, white), by default the accent color and following it;
  one palette for Settings, the picture and voice commands ("red" was a
  different red when spoken).
- **Text editor without flicker**: a white or black page no longer forces
  the whole editor into the other theme (the window was drawn half light,
  half dark and switched between the two); only the text colors change.
  Changing it no longer reloads the whole desktop.
- **Settings fit small screens**: the sidebar scrolls (the window used to
  need 704 px of height and its title bar could end up off the screen).
- **Boot menu redesigned** (USB stick on BIOS and UEFI, and the installed
  system), one style everywhere: black, the ZETA RAYS mark, entries in a
  column at a normal size, the chosen one marked by a subtle band with a
  thin blue bar instead of a bright box. GRUB now runs at the screen's own
  resolution on real computers (1920x1080 or the closest; it used to fall
  back to a stretched mode with oversized, blurry text) and at 1280x800 in
  virtual machines; the BIOS menu moves from 640x480 to 1024x768. The
  "safe graphics" entry starts exactly like the normal one.
- **Separate Network and Sound menus** in the bar: the network icon opens
  only network items (Wi-Fi switch and networks, Ethernet, Internet status,
  VPN, Network Settings), the sound icon only sound items (volume, output
  devices, microphone and input devices, Sound Settings). The clock and the
  battery open the Control Center (quick toggles, brightness, battery).
- **"Blender (missing)" fixed at the root**: moving a "Send to Desktop" link
  no longer creates a broken copy (the drag handed over the link's target
  instead of the link); program entries copied, pasted or dropped from
  /opt or Downloads are rewritten with full paths; launchers left broken by
  earlier copies repair themselves; programs unpacked in /opt with a
  desktop entry (Blender from blender.org) appear in the app menu by
  themselves, named with their version when the packaged one is also
  installed, and always start the right copy.
- **Blender from blender.org opens at the right size**: from the menu, the
  Desktop and the Dock it starts like the packaged Blender (X11), which
  sizes its interface from the real screen DPI. Started directly from its
  folder it runs on Wayland, where its window was born at 320x240: the
  window rule did not expect the "LTS" in "(Unsaved) - Blender 5.2.2 LTS".
  Verified with the real Blender 5.2.2 LTS.
- **Account**: Settings > Account with your name and a round picture (a
  .jpg or .png photo, or a circle in an accent color), shown in the account
  menu, on the lock screen and at login.
- **SSH from the internet that stays on**: the choice is synchronized into
  the firewall set (accesso_remoto = { 22 }) after every start and every
  firewall reload; zeta-ssh diagnose checks the whole chain line by line and
  warns about other firewalls (iptables).
- **Boot menu a little smaller and finer**: Roboto 16 px entries, 13 px
  hints, a smaller mark.
- **Lock screen guard**: a lock program that died but was not yet reaped
  (zombie) no longer counts as running, so the lock comes back by itself;
  desktop portals started too early are restarted at login.
- **Disk encryption prompt you can see**: with an encrypted disk the boot
  screen shows a password field with a lock and one dot per character (the
  prompt used to be invisible on a black screen).
- **Show / hide password** on the login screen (eye icon).
- **Desktop icons arranged your way**: Home and Trash move like every other
  icon; right-click › View › Align to Grid (on) or free placement anywhere;
  icons arranged from the left (like Windows) or from the right (like
  macOS); small, medium or large icons; Clean Up Icons snaps them to the
  nearest cells keeping your layout. A shorter desktop menu that always fits
  on screen.
- **Programs dropped on the Desktop become shortcuts**: dragging an AppImage
  (or a menu entry) from the file manager creates its Desktop icon instead of
  copying a gigabyte-sized file; New › App Shortcut… lists every app,
  AppImages included. AppImages show their own icon in the file manager.
- **No Debian look anywhere**: the Synaptic welcome window and Debian logo,
  the blue fallback colours of the boot menu, the kernel line at text
  logins, leftovers of Debian's installer and the generic file manager
  sidebar icons are replaced by ZETA RAYS ones; Debian's artwork packages
  can no longer be installed by accident.
- **AI up to date**: Ollama 0.40.0; Claude Haiku 5.5, Gemini 3.8 Flash,
  GPT-6 Luna, DeepSeek Flash, Qwen 3.8 Flash and gpt-oss on Groq as fast
  defaults (verified on 7 October 2026). Requests adapt by themselves to
  each model (OpenAI's reasoning models used to refuse every request), and
  a model that disappears is replaced automatically. The local model uses
  less memory (8-bit context cache) and no longer waits for the network at
  boot.
- **Faster and lighter**: Python precompiled (every ZETA app starts sooner),
  a faster live image (zstd), no maintenance jobs filling the RAM of the
  live session, protection against freezes when memory runs out (MGLRU), no
  icon rebuilding at every login (one second less), lighter window effects,
  and Firefox without telemetry, Pocket or sponsored content.
- **A natural voice for ZETA**: Piper neural text-to-speech, entirely on the
  computer (Paola in Italian, Lessac in English, high quality); espeak-ng
  stays only for the other languages. Speech recognition (Vosk, Italian and
  English) now ships inside the image instead of being downloaded during
  the build (a network hiccup could leave an image without voice).
- **Font library** (Settings › Fonts): every font shown in its own typeface,
  search, a sample text you can change, Add Fonts… (or drop font files on
  the page) and removal of the fonts you added (to the Trash).
- **Several keyboards** (Settings › Language & Region › Keyboards): add up to
  four layouts (Italian, English US, English UK...), choose the default,
  switch with Alt+Shift or with the new indicator in the bar (IT, US, GB),
  applied at once without logging out.
- App launcher: only whole rows are shown, with an arrow to the next page
  when there are more apps (the last row used to be cut in half).
- Search says "No results for ..." instead of repeating the hint.
- `zeta --help` prints the usage; `zeta --status` columns aligned.
- Faster everything: live-build's own clean-up removed all precompiled
  Python and the icon caches from the image; both are rebuilt at the end of
  the build now (every Python program and GTK app starts sooner).
- No Debian wording in the ZETA RAYS apps ("System package (APT)", "not a
  valid .deb package"...).
- Installer: the steps in the sidebar follow the chosen language (they
  stayed in English), lists and menus use the same large Roboto text as the
  rest, and the installation screen is translated.
- Blender (also the version from blender.org) opens its main window large.

### New
- **English by default, your language everywhere.** The USB stick and the
  live session start in English with a US keyboard. The installer sets the
  language, keyboard and time zone of the installed system, and Settings ›
  Language & Region changes them later: language, regional formats (dates,
  numbers, currency), keyboard layout (optionally together with US English,
  Alt+Shift switches) and, for Chinese, Japanese and Korean, the input method
  (Fcitx 5: Mozc, Pinyin, Chewing, Hangul; Ctrl+Space). 35 languages are ready
  without the internet, with fonts for every script, Firefox and text
  recognition (OCR) in each of them, and Thunderbird in all but Bengali,
  Hindi and Persian (Debian has no translation). The ZETA RAYS apps are
  translated into English and Italian; with other languages they stay in
  English rather than mixing languages.
- **Where is it?** `zeta-app find NAME` and ZETA ("where is Blender?", "which
  command launches Firefox?", "which package provides git?", "find my
  AppImages") list every installation of a program (APT, Flatpak, AppImage,
  /opt...), its launch command, executable, desktop entry, package, version,
  whether a command is in your PATH, and related system services. With
  several installations of the same app ZETA asks which one to open ("open
  Blender Flatpak").
- AppImages live in ~/Applications (Downloads and the Desktop work too).
- AppArmor profiles are loaded, as on a standard Debian installation
  (Security now shows app isolation as active).
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
- Flatpak with Flathub ready; AppImages put in Applications or Downloads join
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
- **AppImage icons duplicated on the Desktop.** An AppImage was identified by
  its file path: moving, renaming or updating the file made it a "new" app,
  broke its Desktop shortcut and put a second icon next to it. Apps are now
  identified by the desktop entry they ship; the menu entry, the Desktop
  shortcut and the Dock follow the file, and an AppImage file on the Desktop
  shows its app name and icon instead of a generic one.
- An AppImage whose file name contains "%" (e.g. "App%20Name") never appeared
  in the menu.
- The desktop keyboard was always Italian, whatever the installer set.
- Wi-Fi on/off, firewall, volume and printer states were read from the text
  of system tools in the system language: in Italian some were always wrong
  ("abilitato" is not "enabled"). They are now read in a language-independent
  way.
- A broken Desktop shortcut showed a technical file name; it now shows the
  app name marked "(missing)".
- Settings › Language & Region, the AI page and other screens no longer
  depend on the text of buttons to know their state.
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
