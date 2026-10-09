# ZETA RAYS OS: Architecture

ZETA RAYS OS is an operating system with its own identity. Under the hood it
relies on proven Linux components (Debian 13 "trixie", Hyprland), but the user
experience is entirely ZETA RAYS: no reference to the base distribution
appears at boot, login, on the desktop, in the terminal, in Settings or in the
documentation.

## Pillars

**AI, Security, Control.** Three native subsystems: ZETA RAYS Intelligence
(ZETA, the multi-provider assistant), ZETA RAYS Security (the security center)
and a consent layer that keeps the user in charge of every sensitive action.

## Project layout

```
ZETA RAYS/
├── live-build/        configuration used to build the ISO
│   └── config/includes.chroot/
│       ├── usr/lib/zeta/           ZETA RAYS subsystems
│       │   ├── intelligence/       ZETA RAYS Intelligence (AI)
│       │   │   ├── agente/         understanding, actions, verification
│       │   │   └── providers/      Claude, Gemini, OpenAI-compatible, Ollama
│       │   ├── system/             apps registry, network, audio, printers...
│       │   ├── ui/                 shared GTK4 pages and menus
│       │   ├── security/           ZETA RAYS Security (audit)
│       │   ├── monitor/ search/ core/
│       │   └── i18n.py             translations (gettext, domain "zetarays")
│       ├── usr/local/bin/          commands: zeta, zeta-core, zeta-sicurezza,
│       │                           zeta-impostazioni, zeta-app, zeta-launcher...
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
| Settings | ZETA RAYS app (GTK4/Adwaita) | appearance, network, printers, AI, language, system |
| Assistant | ZETA RAYS Intelligence | system assistant (text and voice) |
| ZETA | GTK4 + Cairo | AI interface with the particle sphere |
| Title bars | hyprbars (compiled at build time) | close, minimize, maximize on every window |
| Minimized windows | `zeta-finestre` | list of open and minimized windows |
| Desktop | `zeta-scrivania` | files, folders and icons on the wallpaper |
| Search | `zeta-cerca` | apps, actions, file names and content (OCR included) |
| Appearance | `zeta-aspetto` + `zeta-accent` | light/dark theme, text, icons, pointer, scale |
| Apps | `zeta-app` | single app registry: menu, Dock, Desktop, icons, install, uninstall, "where is" |

## Languages

The image starts in English (`en_US.UTF-8`, US keyboard). The UI text in the
code is English; `po/it.po` holds the Italian translation, compiled at build
time into `/usr/share/locale/it/LC_MESSAGES/zetarays.mo` (the build stops if a
string has no translation). The installer (Calamares) writes the chosen
language, keyboard and time zone into the installed system. Settings >
Language & Region (`ui/pagina_lingua.py`, with the privileged helper
`/usr/libexec/zeta-lingua`) changes language, regional formats, keyboard
layout and the Fcitx 5 input method; the supported languages are listed in
`/usr/share/zeta/lingue.json`. With a language other than English or Italian,
the ZETA RAYS apps stay in English.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| `Super` or `Super + Space` | App launcher |
| `Super + S` | Search (apps, actions, files, content) |
| `Super + W` | Open and minimized windows |
| `Super + H` | Minimize the active window |
| `Super + M` | Maximize / restore the active window |
| `Super + Q` | Close the active window |
| `Super + F` | Full screen |
| `Super + V` | Floating / tiled window |
| `Super + Enter` | Terminal |
| `Super + E` | File manager |
| `Super + B` | Browser |
| `Super + I` | Settings |
| `Super + T` | Light / dark theme |
| `Super + Shift + T` | Text from an area of the screen (OCR), copied to the clipboard |
| `Super + Shift + S` | Screenshot of an area, copied to the clipboard |
| `Ctrl + Tab` | App switcher (`Ctrl + Q` inside it closes the chosen app) |
| `Ctrl + Alt + Esc` | Force quit: crosshair, click the frozen window (background = full list, including programs without a window) |
| `Ctrl + Shift + Esc` | Emergency: closes the active window at once, without any interface |
| `Ctrl + Alt + Delete` | Emergency panel |
| `Super + A` | Control Center |
| `Super + L` | Lock the screen |
| `Super + Esc` or `Super + Shift + E` | Power menu |
| `Super + 1…3` | Switch workspace (`Super + Shift + 1…3` moves the window) |

Desktop icons are used with the mouse: double-click to open, right-click to
rename, move to the Trash, create folders and documents, and change the icon
of a shortcut ("Change Icon…", also from Properties). The chosen image is
copied to `~/.local/share/zeta/icone`, so it stays in place even if the
original is moved or deleted. The desktop deliberately does not take keyboard
focus: a full-screen surface holding the focus would stop you from typing in
any other window.

## Hiding the base system

Debranding happens in three places:

1. **Build hook** (`0100-zeta-branding`): rewrites `os-release`, `issue`,
   `motd`, the system logo, and the boot and login themes.
2. **Boot menu** (`bootloaders/`): ZETA RAYS logo and English entries.
3. **`.disk/info`** (`9000-zeta-disk`): the boot media identifies itself as
   ZETA RAYS OS.

See [BRANDING.md](BRANDING.md) for the full list of rewritten places.
