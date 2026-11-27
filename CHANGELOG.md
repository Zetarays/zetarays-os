# Changelog

## 3.5 — 2026-11-27

Upgrade from 3.0 without reinstalling: `zetarays-3.5-upgrade-{amd64,arm64}.run`.

### Added
- **ZETA WATCH: real-time security monitoring.** A light system service
  (`/usr/libexec/zeta-watch`, limited to 120 MB and 15% of a CPU) reads:
  - the journal: failed and successful SSH logins, wrong passwords at login,
    lock screen and administrator prompts, root sessions, refused sudo, new
    users, administrator rights given, passwords changed;
  - auditd: writes to the files of accounts, sudoers, PAM, SSH, autostart
    places and `/etc/ld.so.preload` (rules in
    `/etc/audit/rules.d/50-zeta-watch.rules`; changes made by apt and the
    account tools are not reported);
  - every minute: new open ports, the firewall rules, newly enabled
    services, programs running from temporary folders or deleted files,
    outgoing connections to unusual ports;
  - weekly: rkhunter, plus what the daily chkrootkit found that its
    reference run did not.
  Repeated events within ten minutes become one alert with a count. An
  address that fails the SSH password 5 times in 10 minutes is blocked for
  an hour (an nftables set): never this computer, never an address with an
  SSH session open, never the local network unless chosen. Alerts appear as
  notifications in every administrator's session, optionally read aloud,
  from the chosen level up. Settings › ZETA WATCH has every switch (turning
  a protection off says what is lost), the blocked addresses, a test alert,
  the history, and optional Suricata (installed on first use, recommended
  with 16 GB). The rules are tested with real log lines
  (`tools/tests/test_watch_rules.py`).
- **Settings › Users.** Add users (standard or administrator), change full
  name and password, give or remove administrator rights, rename or remove
  an account (keeping or deleting its files), and see who is logged in.
  `/usr/libexec/zeta-users` refuses removing the last administrator or your
  own account, never renames or removes a logged-in user, and never moves or
  deletes a home folder that holds protected data or another mounted disk.
  Every password field has the eye button.
- **Settings › Firewall & SSH.** The firewall on or off (with a warning),
  what it lets in, the SSH server (port 22) on or off, local network only or
  also from the internet, its status and a step-by-step check.
- **Settings › Startup Applications.** Programs that start at login
  (`~/.config/autostart`, started by `/usr/libexec/zeta-autostart`): add
  from the installed apps, turn off, remove.
- **Voices.** Italian: Sara, Nicola (new, male), Serena, Paola. English:
  Heart (new default, American), Michael (new, American, male), George
  (new, British, male), Lessac (the light voice used when memory is short).
  The new voices are Kokoro voices already inside the voice file of the
  system: nothing more to download, and an upgraded 3.0 gets them too. Every
  Kokoro voice is tested at build. Settings › AI › Voice: "ZETA speaks"
  Always, or Only when I ask (a speaker button under each reply).
- **ZETA looks things up in the documentation.** For a technical question
  about Linux ("what does systemctl mask do", "why does apt say permission
  denied") ZETA reads the manual page of the command from this computer
  (offline), and the ArchWiki page of the topic when web lookups are on,
  and shows them as sources under the answer.
- **Settings › AI › What ZETA did**: the history of the actions ZETA ran,
  with their result (passwords are never written there).
- **Three new 4K wallpapers**: Circuit core (the wallpaper of 3.5),
  Fortress and Watch, in Settings › Appearance, on the website and on the
  screenshots page; ZETA finds them by name ("set the fortress wallpaper").
  Circuit core is the desktop of anyone who never chose a wallpaper (and
  what "Reset" brings back) and the background of the login screen,
  darkened so the name and the password field stay readable. The lock
  screen stays black.
- **Settings › Desktop & Icons.** Icon size (32 to 96 px, or the Dock's),
  spacing, grid on or off, which side new icons fill and in which order,
  single or double click, names on or off with their size, lines, bold,
  color and contrast (soft shadow or a band behind the text), Sort By, an
  "Arrange icons now" button and Reset to default. Every change shows at
  once, without restarting the desktop. The right-click View menu writes
  the same file (`~/.config/zeta/desktop-look.json`).
- **Settings › Windows & Multitasking.** Programs reopen with the size and
  position they had when last closed, on the same display
  (`usr/lib/zeta/hypr/window_memory.lua`, unit-tested); "Forget saved
  positions"; focus follows the pointer on or off; "Bring every window
  back now"; the window shortcuts at a glance.
- **Protected data in the upgrade.** The upgrade records the folders listed
  in `/etc/zeta/protected-paths` before changing anything (names, sizes,
  dates, permissions, owners, a fingerprint of each file) and checks them
  afterwards, also after a rollback; it stops if a listed folder that is
  present cannot be read completely, and goes on when it is absent (a NAS
  that is off). It never writes under /home, /root, /srv, /mnt or /media:
  both the bundle builder and the upgrade stop if a planned file is there,
  and `rollback.sh` skips such paths. `sudo zeta-upgrade-verify` checks the
  folders again later.
- **Settings the upgrade must not change.** `/etc/zeta/upgrade-keep` (one
  path or folder under /etc per line, empty by default) lists system
  settings files to leave as they are; the new version is saved next to
  them as `.dpkg-dist` and the dry run lists them. Files the user changed
  are kept anyway.
- **The upgrade no longer reloads the firewall while the computer runs.**
  Its file starts with `flush ruleset`, so a reload also wiped the rules
  that Docker, a media server or a VPN had added, and a restart turned on
  a firewall the user had turned off. The new rules apply at the restart
  the upgrade asks for.

### Fixed
- Desktop icons lost their places. At startup the layout was computed on a
  guessed 1280x800 screen before the real size was known, and an icon whose
  saved cell did not fit was moved and its saved place overwritten; so did
  a smaller resolution or scale, a larger icon size (which also rearranged
  everything), and a file missing for a moment. Now nothing is placed until
  the real size is known, a cell that does not fit is only shown nearby
  (the saved place comes back with the old resolution), a renamed file
  keeps its place, and places of missing files are kept for 30 days.
- The desktop's right-click "Display Settings…" opened the Lock Screen page.
- Found by an independent security review of the new code, before release:
  - ZETA WATCH trusted the sender name of journal lines (any user could write
    a line "from sshd" with logger) and an SSH user name could carry a fake
    "from ADDRESS": either could get an arbitrary address blocked, this
    computer included. Lines of sshd, sudo, su, the account tools and the
    kernel now count only when the journal says they come from root (or the
    kernel), the address is the last one of the line, only literal IP
    addresses are blocked (never loopback, unspecified, multicast, reserved
    or link-local; the LAN only when chosen), and the block rule sits after
    "this computer" in the firewall.
  - Refused SSH keys no longer count as failed passwords (ssh tries every
    key of the agent), and a successful login forgets that address's
    failures.
  - ZETA WATCH saw package installs as finished while apt ran (the lock was
    opened for writing on a read-only system view), its counters had no
    limit, and a failing part could stop watching while the service stayed
    "active": now it restarts.
  - Users: a kept home folder of a removed account is renamed and closed, so
    a later account with the same number cannot own its files; "remove the
    files" acts only on /home/NAME; no account named like a group; when
    logind cannot be asked, rename and remove refuse.
  - Upgrade: a resumed run keeps the first run's record of the protected
    folders, a folder gone from a still-mounted disk is a loss (a NAS
    unmounted is "not reachable"), links are followed by the guard and by
    rollback.sh, and reading a file can no longer hang on a pipe.
- **The OVA imports in VMware.** It was made for VirtualBox only (OVF 2.0,
  which VMware's importer rejects). It is now OVF 1.0 with VMware's own
  additions (`tools/ova-vmware-compat.py`): hardware version, Debian 12
  64-bit guest, EFI, VMXNET3 network on arm64, 3D acceleration on, the
  VirtualBox sound card optional. VirtualBox imports it as before. Tested in
  VMware Fusion: import, start, desktop, network, self-test. On a Mac with
  Apple silicon, VMware's importer knows no Arm guest types: after import,
  set Settings › General › OS to "Debian 12.x 64-bit Arm" (or install from
  the ISO, which works as it is).
- The page shown without 3D acceleration also says how to turn it on in
  VMware.
- On a network that hands out no address (a cable without a DHCP server,
  a Wi-Fi not in range yet) the boot waited 60 seconds for the network and
  left a failed unit (NetworkManager-wait-online); it now waits 30 seconds
  and a timeout is not an error.
- Every ZETA WATCH desktop alert left a finished notify-send process behind
  (a zombie, reported by the self-test); terminals opened from Settings
  (Suricata install, SSH diagnosis and the other pages) stayed behind the
  same way until Settings was closed. Both are now reaped.
- The privacy text (in Settings) now describes ZETA WATCH
  (everything stays on the computer; only ClamAV signatures and, if turned
  on, the Suricata rules are downloaded), the ArchWiki lookup for technical
  questions and the history of what ZETA did.
- ClamAV: the always-running signature updater and the one-time update at
  boot started together and the second failed (a failed unit after every
  boot); the always-running one is off (18 MB of memory), Debian's timer
  updates the signatures at idle priority, and the live session no longer
  downloads 100 MB of signatures into memory.

## 3.0 — 2026-11-20

Images: `zetarays-3.0-{amd64,arm64}.{iso,ova}` on <https://zetarays.org>.
Upgrade from 2.5 without reinstalling: `zetarays-3.0-upgrade-{amd64,arm64}.run`.

### Highlights of 3.0
- **Upgrade in place from 2.5.** One file per architecture
  (`sudo bash zetarays-3.0-upgrade-ARCH.run`, or a double-click in Files):
  it checks the system, saves every file it replaces in
  `/var/backups/zeta-rays-2.5-DATE/` with a `rollback.sh`, installs the new
  packages and the pending Debian updates, then the ZETA RAYS files. Files,
  apps and settings stay; settings files changed by hand are kept (the new
  version goes next to them). `--dry-run` shows everything first. From 3.0 the
  ZETA RAYS updates have their own signed package source (docs/UPDATES.md),
  active only while it answers, so it never makes Software Update fail.
- **Screenshots and screen recording.** Print opens a toolbar (area, window,
  full screen, record an area or the screen, pick a color, timer, pointer,
  sound); Shift+Print captures the screen, Alt+Print the active window,
  Super+Shift+S an area, Super+Shift+R starts and stops a recording. Every
  capture is saved in Pictures/Screenshots and copied; its notification
  opens Edit (arrows, text, blur), Copy Text (OCR), Open Folder and Delete.
- **Clipboard history and emoji** like Windows: Super+V lists the last 100
  copies (text and images, passwords from password managers are never
  saved) and pastes the one you pick; Super+. inserts emoji with search.
- **Night Light** (Settings › Displays and the Control Center): warmer colors
  from sunset to sunrise (computed offline from the time zone), always, or
  at custom times, with a temperature slider.
- **Control Center quick settings**: Night Light, Do Not Disturb, Power Mode,
  Screenshot, Record and Clipboard. Do Not Disturb keeps critical
  notifications and shows a bell in the bar; the notification history is one
  click away.
- **Snap layouts**: Super+Shift+Left/Right for halves, Up to maximize, Down to
  restore; Super+Z opens the layouts (halves, thirds, quarters, centered).
- **Quick Look**: Space previews the selected file in Files and on the
  desktop (images, PDF, text, video, folders).
- **New Settings pages**: Power & Battery (power mode, battery health, screen
  off/lock/suspend times, power button), Keyboard & Mouse, Date & Time,
  Accessibility (screen reader, larger text, high contrast, zoom with
  Super+plus/minus, reduce motion), Storage (what uses the space, cleanup)
  and Backup (personal files with Déjà Dup, system snapshots with Timeshift,
  optionally before every system update). The sidebar is grouped and pages
  are built only when opened, so Settings opens faster.
- **ZETA reads the screen and your files**: "what's on my screen?",
  "translate what I'm looking at", and "Ask ZETA to Summarize" on a text,
  PDF or office file in Files (also `zeta summarize FILE`). All local.
- **New AI model for 8 GB and mini PCs: Granite 4.2 3B** (faster first
  word, all commands right, better Italian than Granite 4.0 Micro, which keeps
  working on upgraded systems until the new one is downloaded). Qwen3 4B
  Instruct stays for 16 GB, Granite 4.1 8B for large computers. Ollama 0.40.16.
- **Purple** joins the accent colors (and the account picture colors), with a
  purple logo wallpaper; new **Rays** wallpaper.

### Fixed
- arm64 installs could not install kernel updates: the Raspberry Pi firmware
  package's boot step failed on every computer that is not a Raspberry Pi.
  It is no longer in the image, and the upgrade removes it.
- ZETA's "open the packages settings" opened the default page.
- The panels follow every accent color: switches, check boxes, the focused
  search field and selected text kept the GTK blue. After switching between
  dark and light, a panel already in memory redraws its icons (the delete
  buttons in the clipboard history were invisible on the light card).

### Performance and cleanup
- The unattended-upgrades shutdown guard runs only while automatic updates
  are on; earlyoom never stops the lock screen, the login helper or audio, and
  stops a heavy browser tab before the whole browser.
- Two data-center firmware packages (about 200 MB) removed from the image.
- Dead code, unused icons and data removed (about 225 lines of Python,
  9 files); a `performance` self-test group reports memory, processes and
  services.

## 2.5 — 2026-10-25

Images: `zetarays-2.5-{amd64,arm64}.{iso,ova}` on <https://zetarays.org>.

### Highlights of 2.5
- **Local AI only.** ZETA answers only with models that run on the computer.
  The connections to online AI services, their API keys and the "ask an
  online service instead" offer are gone. The model
  server only answers on 127.0.0.1, requests to it never go through a proxy,
  and Ollama's own cloud features are switched off (`OLLAMA_NO_CLOUD=1`):
  its "-cloud" models are refused.
- **The model that suits the computer.** A profile per machine (8 GB, 16 GB,
  Intel N100/N150 low-power) with its list of models; Settings › AI shows the
  choice and offers the recommended model when it is missing (download only
  on click, after checking disk space and memory). When memory is short a
  smaller installed model answers that question, and ZETA says so.
  The image now includes two models: **Granite 4.0 Micro** (IBM, hybrid,
  2.4 GB in memory, the fastest writer of the two: used on N100 mini PCs and
  8 GB computers) and **Qwen3 4B Instruct** (the most natural Italian: used
  with 16 GB). **Granite 4.1 8B** is recommended on computers with 24 GB and
  8 threads. Chosen from 11 models compared on the same prompts (docs/AI.md).
- **A real memory.** Conversation, long-term memories ("remember that…",
  "forget…", "what do you know about me?") and reference material in one
  private SQLite file with full-text search (under a millisecond). Only the
  memories that match a question are sent with it. Settings › AI › Memory
  lists, deletes, exports and clears them, and sets how long the
  conversation is kept (30 days by default). `zeta --learn FILE` adds your
  own documents. The 2.1 history is moved in automatically.
- **Current facts without guessing.** A verified local reference (who is the
  President of the United States, Italy's President and Prime Minister, the
  Pope, each with the date it was checked) answers at once and offline;
  other current questions are looked up on Wikipedia when the search is on;
  otherwise ZETA says it cannot verify.
- **Text and voice together, by default.** The answer is read aloud while it
  is written, starting with the first sentence, in a female voice that
  matches the language of the question (Sara for Italian, Lessac for
  English). Pause, stop and "read again" under the input field; volume in
  Settings › AI › Voice. A voice turned off in 2.1 stays off.
- **Ollama 0.40.11** and every Debian package updated to the latest version.

### Fixed
- Installing from the live desktop ("Try ZETA RAYS OS", then "Install") could
  fail near the end with a package that could not be installed: with the
  network up, Debian's boot loader step installed GRUB from the internet,
  which did not fit the image. The step now uses only the installation
  medium, so the installation is the same with or without a network.
- "What is a CPU?" was answered with the current CPU usage instead of an
  explanation.
- The boot menu of the USB stick loaded no terminal font: one line of its
  configuration was not valid GRUB syntax. The build now checks every boot
  menu file with `grub-script-check`.

### Also in 2.5
- Copies of ZETA's own note that some models write back ("[Today: …]") are
  removed from answers and never read aloud.
- `zeta-diagnostics` reports the memory store (sizes only) and who can reach
  the model, instead of API keys.
- The image build checks every shipped model and its license; models are no
  longer downloaded during the build.
- The image build resumes correctly after a crash inside one of its steps
  (seen with the emulated amd64 build): the files a step installs from are
  put back before it runs again.
- The web lookup identifies itself with the release from `/etc/os-release`.
- New tests in `zeta-selftest ai`: local-only rules, memory store, memory
  commands, model profiles, smaller-model fallback, local reference, voice
  streaming.

## 2.1 — 2026-10-18

Images: `zetarays-2.1-{amd64,arm64}.{iso,ova}` on <https://zetarays.org>.

### Highlights of 2.1
- **Fast local answers on small computers.** The local model now reads only
  the new text of each question: the fixed part of the prompt never changes,
  the clock and the sources travel with the question, the conversation is
  shortened in blocks and sized to the speed of the computer, and the fixed
  part is prepared when the model is loaded. Measured on a virtual machine
  slowed to the speed of an Intel N100: first words in 1.2 to 3 seconds
  (a question with a Wikipedia lookup: about 6 seconds), where a few
  questions into a conversation it used to take 30 to over 60 seconds.
- **A smarter local AI.** ZETA now runs Qwen3 4B Instruct (2507, Apache-2.0)
  instead of Llama 3.2 1B. In our benchmark (commands, Italian and English
  answers, use of sources, conversation memory) it understood 10 of 10
  commands against 3 of 10, remembers what was said earlier in the
  conversation and answers in correct Italian. It needs about 3.7 GB of
  memory while loaded: on 8 GB computers it is loaded when you ask and
  released after a few minutes; with 16 GB it stays ready.
- **Current facts, honestly.** ZETA knows today's date and time and says when
  its knowledge may be out of date instead of presenting old facts as current.
  "Search the web for current information" (Settings › AI, on by default)
  looks questions about current facts up on Wikipedia and shows the sources
  under the answer. Only the question is sent; with the search off ZETA says
  it cannot verify instead of giving an old name as current.
- **ZETA never switches service on its own.** If the local model is not
  available, nothing is sent to an online service: ZETA says so and offers it.
  Stop really stops the answer; every request has time limits; one failed
  request no longer blocks the next; the conversation kept in memory is
  bounded. Errors from online services say what happened (invalid key, no
  credit, too many requests with the waiting time, model not available).
- **Software Update** in Settings: check, see what changes and how much to
  download, install with progress, cancel, restart when needed, last update.
  Built on PackageKit with the administrator password asked by PolicyKit;
  waits when another program is installing, checks disk space, repairs an
  interrupted installation. Security updates install automatically on new
  installations (Debian-Security only, switch in the same page).
- **ZETA RAYS Monitor stays calm when the system is healthy.** Four levels
  (system OK, note, attention, error), red only for real errors. Each failed
  service is explained in plain words, with its log, "Try Again" and
  "Dismiss"; services for hardware the computer does not have, jobs that
  failed once and will run again, and failures already recovered are no
  longer reported as errors.
- **Windows can never get lost.** The window guard now also brings back
  windows left on an unplugged display, untitled windows and dialogs placed
  off screen, programs that keep moving themselves out, full-screen windows
  (SUPER + SHIFT + W) and windows bigger than the screen; it never pulls a
  window you are dragging. Minimized windows are found again after a crash,
  and without title bars a "Windows" button in the bar lists every window.
- **Files like on other systems.** Thunar has view buttons (icons, detailed
  list, compact list), zoom, thumbnails and a remembered view per folder.
  "Open With" on the Desktop and in Thunar now lists AppImages and programs in
  /opt; drag a file onto an app icon on the Desktop to open it with that app,
  or onto a folder to move it inside.
- **New wallpaper: Goddess**, in Settings › Appearance and on the website.
- **A new Italian voice: Sara.** ZETA reads its answers in Italian with
  Sara (Kokoro-82M, Apache-2.0), clearer and more natural than before;
  Serena and Paola remain in Settings › AI › Voice, English keeps Lessac.
  The text is prepared for reading (numbers, times, dates, units, links and
  formatting), the first word is never cut, and the speed can be chosen.
  Sara needs about 300 MB while speaking; when memory is short, Serena reads.
- **Answers in your language.** Quick answers, confirmations and notes now
  follow the language you write in (Italian or English); Settings › AI ›
  Reply language can keep every answer in the system language.
- **Source code fully in English.** The words and phrases ZETA understands
  in Italian moved from the code to data files; the code, comments and
  documentation are in English.

### Fixed
- Windows flickered, pulsed or wobbled on real computers (seen on an Intel
  N100 mini PC). The causes found and removed: the opening animation really
  resized each window frame by frame from 90% to 100% (now windows only fade
  in and out, with no change of size or position); ZETA's own moves and
  resizes were animated (now instant, and a window one or two pixels off the
  edge is left alone); Hyprland's colour management, its experimental 16-bit
  buffer and the content type sent to the monitor were on, which changed how
  GTK apps draw and could make the monitor switch its picture mode (all off:
  plain sRGB, nothing is lost without HDR content). A desktop component that
  crashes right after starting no longer appears and disappears forever, and
  the bar is restarted only for a certain duplicate.
- Blender downloaded from blender.org and started directly drew a smaller
  interface at fractional display scales (a Blender limitation on Wayland);
  ZETA now reopens it through X11, as its own launchers already did.
- Virtual appliance (OVA): the backports package source was missing, so
  Hyprland and its libraries could not receive updates.
- The right-click menu of a minimized window in the bar did nothing.
- A launcher (.desktop file) copied onto the Desktop ran on double-click
  without asking; now an unknown launcher asks once before running.
- The text editor flickered after switching its page between white and black
  from its own menu; the choice now becomes the page color only.
- Search, launcher and power menu kept the theme of the login.
- Changing the theme could end the session (introduced while renaming the
  source in English, fixed before any release).
- "Open With" missed apps installed by the user; the desktop could not take a
  folder dragged from the file manager.
- The weekly health check notified about the same failed service every hour.
- Settings › AI claimed tool support for one online service that it did not use, which prevented streaming.

### Upgrades
- Ollama 0.40.3; Debian 13 packages updated at build time; new packages:
  PackageKit 1.3.1, unattended-upgrades, ONNX Runtime 1.21 (for Kokoro).

### Known limitations
- Dragging a file onto an icon of the Dock (Waybar) is not supported.
- Configuration files you changed by hand (for example hyprland.lua) are kept
  and do not get the 2.1 improvements; unchanged ones are updated at login.
- Web search uses Wikipedia: news, prices and weather often cannot be
  verified, and ZETA says so.
- VMware: the OVA is made for VirtualBox and VMware's importer rejects it
  (OVF 2.0 elements). Extract the disk from the OVA (it is a tar archive),
  attach it to a new VM (EFI, NVMe) or install from the ISO, which works in
  VMware Fusion as it is.
- With 768 MB of memory the system starts but stops at the
  login screen (the desktop needs more). 8 GB are recommended for the AI.
- The desktop needs 3D acceleration; without it ZETA RAYS says so and
  explains how to turn it on (the live USB stick opens the installer).
- GRUB prints three harmless "syntax error" lines on the serial console at
  boot (also in 2.0); the boot is not affected.
- Flicker of the whole screen on some monitors and graphics cards could not
  be reproduced in virtual machines: docs/FLICKER-TESTS.md explains how to
  find the cause on the affected computer.

## 2.0 — 7 October 2026

Images: `zetarays-2.0-{amd64,arm64}.{iso,ova}` on <https://zetarays.org>.

### Highlights of 2.0
- **ZETA RAYS Monitor reports services honestly**: running, completed,
  stopped, not applicable (skipped by its own condition, such as Bluetooth
  without an adapter), attention (a periodic job that failed) or failed;
  only a failed service turns the status red. Root cause of a recurring
  "failed service": the daily chkrootkit scan tried to mail its report to
  root, but no mail server is installed (`mail: not found`, exit 127); the
  report now goes to the journal and the first scan becomes the reference,
  so later scans report only real changes.
- **Folder colors**: right-click a folder › Folder Color (red, white, green,
  blue, purple, default), on the Desktop (the whole folder in color) and in
  the file manager (a colored dot); stored as file metadata, kept after a
  restart, nothing inside the folder changes.
- **English source**: every comment, docstring, developer message and
  developer document is in English (checked by `tools/check-italian.py` in
  CI); Italian stays only in the translations and in Italian data such as
  voice commands. Website and Italian translation use "click" consistently
  (see `docs/GLOSSARY.md`), and "Support" replaces "Donate".
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
  the firewall set (remote_access = { 22 }) after every start and every
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
- **AI up to date**: Ollama 0.40.3; current fast default models for the
  online services of that release (verified on 7 October 2026). Requests
  adapted by themselves to each model, and a model that disappeared was
  replaced automatically. The local model uses
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

### English-only source
The whole source is now in English: commands, helpers, services, file and
folder names, desktop entry IDs (`org.zetarays.Impostazioni` is now
`org.zetarays.Settings`), environment variables, identifiers, comments and
developer messages. Italian remains only as translation data (`po/it.po`,
`*.it.md`, `Name[it]=` entries, Italian voice and text command patterns).
There are no Italian aliases left: scripts that call the old names must use
the new ones.

Renamed commands:

<!-- i18n-data-begin: old Italian command names, quoted on purpose -->
| Old | New | Old | New |
|---|---|---|---|
| `vedi` | `zeta-view` | `zeta-prove` | `zeta-selftest` |
| `zeta-ai-precarica` | `zeta-ai-preload` | `zeta-regione-radio` | `zeta-radio-region` |
| `zeta-appimage-anteprima` | `zeta-appimage-thumbnail` | `zeta-riduci` | `zeta-minimize` |
| `zeta-aspetto` | `zeta-appearance` | `zeta-ripara-avvio` | `zeta-repair-boot` |
| `zeta-barra` | `zeta-bar` | `zeta-ripresa` | `zeta-recovery` |
| `zeta-benvenuto` | `zeta-welcome` | `zeta-salute` | `zeta-health` |
| `zeta-cerca` | `zeta-search` | `zeta-schermi` | `zeta-displays` |
| `zeta-controllo` | `zeta-control-center` | `zeta-scrivania` | `zeta-desktop` |
| `zeta-copia-amministratore` | `zeta-admin-copy` | `zeta-scrivania-apri` | `zeta-open-desktop-folder` |
| `zeta-diagnosi` | `zeta-diagnostics` | `zeta-selettore` | `zeta-switcher` |
| `zeta-emergenza` | `zeta-emergency` | `zeta-sfondo` | `zeta-wallpaper` |
| `zeta-energia` | `zeta-power-menu` | `zeta-sicurezza` | `zeta-security` |
| `zeta-finestre` | `zeta-windows` | `zeta-sistema` | `zeta-system` |
| `zeta-impostazioni` | `zeta-settings` | `zeta-sorgenti-apt` | `zeta-apt-sources` |
| `zeta-incolla-amministratore` | `zeta-admin-paste` | `zeta-spazi` | `zeta-workspaces` |
| `zeta-installa` | `zeta-install-system` | `zeta-ssh-installato` | `zeta-ssh-installed` |
| `zeta-installa-programma` | `zeta-install-program` | `zeta-ssh-sincronizza` | `zeta-ssh-sync` |
| `zeta-lingua` | `zeta-language` | `zeta-tastiera` | `zeta-keyboard` |
| `zeta-pacchetti` | `zeta-packages` | `zeta-terminale` | `zeta-terminal` |
| `zeta-pannello` | `zeta-panel` | `zeta-testo` | `zeta-text-capture` |
| `zeta-posta` | `zeta-mail` | `zeta-verifica-avvio` | `zeta-verify-boot` |
| `zeta-predefinita` | `zeta-default-app` | `zeta-vigila` | `zeta-watchdog` |
<!-- i18n-data-end -->

Subcommands and options follow the same rule (for example `zeta-ssh stato`
is now `zeta-ssh status`, `zeta-ssh diagnosi` is `zeta-ssh diagnose`).

User settings from an earlier version are converted automatically, once, at
the first login and before the desktop starts (`/usr/libexec/zeta-migrate-user`):
configuration files and keys under `~/.config` (for example `scrivania.json`
becomes `desktop.json`, `schermi.json` becomes `displays.json`), Hyprland
shortcuts, the Dock, desktop entries and file manager actions that referred to
the old names. Configuration files you never changed are replaced with the new
ones; a saved key for a custom AI service is re-encrypted under its new name. A
copy of every changed file is kept in `~/.local/state/zeta/migration-backup/`.
The network update script (`update-network-zeta-rays.sh`) writes the firewall
files with the new set names. Nothing has to be done by hand.

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
  services of the user's choice and automatic fallback to the local model
  without internet.
- Bar menus (logo, search, network, sound, power) open instantly.
- Remote access (SSH): on by default once installed, from the local network
  and from the internet (rate-limited, root never allowed); off in the live
  session and the OVAs. `zeta-ssh` with `status`, `config`, `diagnose`.
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
- **Panels kept the theme of the login.** Search, the app launcher and the
  power menu stay in memory to open instantly, and they kept the light or
  dark theme and the accent color they started with until the next login.
  They now reload their colors when they open, if the theme changed.
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
