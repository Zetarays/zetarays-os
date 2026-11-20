# ZETA RAYS OS: Architecture

ZETA RAYS OS is an operating system with its own identity. Under the hood it
relies on proven Linux components (Debian 13 "trixie", Hyprland), but the user
experience is entirely ZETA RAYS: no reference to the base distribution
appears at boot, login, on the desktop, in the terminal, in Settings or in the
documentation.

## Pillars

**AI, Security, Control.** Three native subsystems: ZETA RAYS Intelligence
(ZETA, the local AI assistant), ZETA RAYS Security (the security center)
and a consent layer that keeps the user in charge of every sensitive action.

## Project layout

```
ZETA RAYS/
├── live-build/        configuration used to build the ISO
│   └── config/includes.chroot/
│       ├── usr/lib/zeta/           ZETA RAYS subsystems
│       │   ├── intelligence/       ZETA RAYS Intelligence (AI)
│       │   │   ├── agent/         understanding, actions, verification
│       │   │   └── providers/      Ollama (the local model, 127.0.0.1 only)
│       │   ├── system/             apps registry, network, audio, printers...
│       │   ├── ui/                 shared GTK4 pages and menus
│       │   ├── security/           ZETA RAYS Security (audit)
│       │   ├── monitor/ search/ core/
│       │   └── i18n.py             translations (gettext, domain "zetarays")
│       ├── usr/local/bin/          commands: zeta, zeta-core, zeta-security,
│       │                           zeta-settings, zeta-app, zeta-launcher...
│       ├── usr/share/zeta/         brand, shell, languages, documentation
│       └── etc/skel/.config/       default user configuration
├── po/                translations (it.po: English source text -> Italian)
├── tools/             asset generators, build and test scripts
├── brand/             ZETA RAYS logo and symbol (SVG)
├── docs/              this documentation
└── build.sh           builds the ISO
```

## Interface

| Part | Component | Role |
|---|---|---|
| Windows | Hyprland (Wayland) | window manager, effects, animations |
| Bar and Dock | Waybar | bottom bar with the Dock and status |
| Launcher | ZETA RAYS app (GTK4) | full-screen app search and launch |
| Login | SDDM (ZETA RAYS theme) | login screen |
| Boot | Plymouth (ZETA RAYS theme) | animated logo at startup |
| Settings | ZETA RAYS app (GTK4/Adwaita) | appearance, network, printers, keyboard and mouse, date and time, accessibility, storage, backup, AI, language, system (pages built on first view; `zeta-settings --help` lists them) |
| Assistant | ZETA RAYS Intelligence | system assistant (text and voice) |
| ZETA | GTK4 + Cairo | AI interface with the particle sphere |
| Title bars | hyprbars (compiled at build time) | close, minimize, maximize on every window |
| Minimized windows | `zeta-windows` | list of open and minimized windows |
| Snap layouts | `zeta-snap` + `window_snap.lua` | halves, thirds, quarters, centered, maximize, restore |
| Quick Look | `zeta-quicklook` | instant preview of a file (Space in Files and on the Desktop) |
| Desktop | `zeta-desktop` | files, folders and icons on the wallpaper |
| Search | `zeta-search` | apps, actions, file names and content (OCR included) |
| Appearance | `zeta-appearance` + `zeta-accent` | light/dark theme, text, icons, pointer, scale |
| Apps | `zeta-app` | single app registry: menu, Dock, Desktop, icons, install, uninstall, "where is" |
| Screenshots | `zeta-screenshot` | area, window, screen, screen recording (wf-recorder), annotations (swappy), text (OCR) |
| Clipboard and emoji | `zeta-clipboard` | clipboard history (cliphist, passwords never saved) and emoji picker |
| Notifications | mako + `zeta-dnd` | Do Not Disturb (critical notifications still appear) and recent notifications |

## Languages

The image starts in English (`en_US.UTF-8`, US keyboard). The UI text in the
code is English; `po/it.po` holds the Italian translation, compiled at build
time into `/usr/share/locale/it/LC_MESSAGES/zetarays.mo` (the build stops if a
string has no translation). The installer (Calamares) writes the chosen
language, keyboard and time zone into the installed system. Settings >
Language & Region (`ui/language_page.py`, with the privileged helper
`/usr/libexec/zeta-language`) changes language, regional formats, keyboard
layout and the Fcitx 5 input method; the supported languages are listed in
`/usr/share/zeta/languages.json`. With a language other than English or Italian,
the ZETA RAYS apps stay in English.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| `Super` or `Super + Space` | App launcher |
| `Super + S` | Search (apps, actions, files, content) |
| `Super + W` | Open and minimized windows |
| `Super + H` | Minimize the active window |
| `Super + M` | Maximize / restore the active window |
| `Super + Shift + Left` / `Right` | Snap the active window to the left / right half (a tiled window moves in the layout) |
| `Super + Shift + Up` / `Down` | Maximize / restore the active window (back to its place before the snap) |
| `Super + Z` | Snap layouts: halves, thirds, quarters, centered; click a zone |
| `Space` (Files, Desktop) | Quick Look of the selected file: Space or Esc closes, Enter opens |
| `Super + Q` | Close the active window |
| `Super + F` | Full screen |
| `Super + V` | Clipboard history: click or Enter pastes, Delete removes an entry |
| `Super + .` or `Super + Ctrl + Space` | Emoji (a click inserts the emoji) |
| `Super + Shift + V` | Floating / tiled window |
| `Super + Enter` | Terminal |
| `Super + E` | File manager |
| `Super + B` | Browser |
| `Super + I` | Settings |
| `Super + T` | Light / dark theme |
| `Super + Shift + T` | Text from an area of the screen (OCR), copied to the clipboard |
| `Super + Shift + S` | Screenshot of an area, saved to Pictures/Screenshots and copied to the clipboard |
| `Print` | Screenshot toolbar: area, window, full screen, screen recording, timer, options |
| `Shift + Print` / `Alt + Print` | Screenshot of the full screen / of the active window |
| `Super + Shift + R` | Start a screen recording (click a screen or drag an area); press again to stop |
| `Ctrl + Tab` | App switcher (`Ctrl + Q` inside it closes the chosen app) |
| `Super + Shift + W` | Every window back inside the screen, title bar and buttons within reach; full screen windows leave full screen (also a button in the Windows list) |
| `Super + drag` / `Super + right-drag` | Move / resize a window, grabbing it anywhere (also one larger than the screen) |
| `Ctrl + Alt + Esc` | Force quit: crosshair, click the frozen window (background = full list, including programs without a window) |
| `Ctrl + Shift + Esc` | Emergency: closes the active window at once, without any interface |
| `Ctrl + Alt + Delete` | Emergency panel |
| `Super + A` | Control Center |
| `Super + L` | Lock the screen |
| `Super + Esc` or `Super + Shift + E` | Power menu |
| `Super + 1…3` | Switch workspace (`Super + Shift + 1…3` moves the window) |
| `Super + plus` / `Super + minus` | Zoom in / out around the pointer (`Super + 0` back to normal size) |
| `Super + Alt + S` | Screen reader (Orca) on or off |

Desktop icons are used with the mouse: double-click to open, right-click to
rename, move to the Trash, create folders and documents, and change the icon
of a shortcut ("Change Icon…", also from Properties). The chosen image is
copied to `~/.local/share/zeta/icons`, so it stays in place even if the
original is moved or deleted. The desktop deliberately does not take keyboard
focus: a full-screen surface holding the focus would stop you from typing in
any other window. The one exception: right after a click on an icon, while
the pointer stays on the Desktop, Space opens Quick Look and Esc clears the
selection; moving the pointer onto a window or activating one gives the
keys back at once.

## Hiding the base system

Debranding happens in three places:

1. **Build hook** (`0100-zeta-branding`): rewrites `os-release`, `issue`,
   `motd`, the system logo, and the boot and login themes.
2. **Boot menu** (`bootloaders/`): ZETA RAYS logo and English entries.
3. **`.disk/info`** (`9000-zeta-disk`): the boot media identifies itself as
   ZETA RAYS OS.

See [BRANDING.md](BRANDING.md) for the full list of rewritten places.
