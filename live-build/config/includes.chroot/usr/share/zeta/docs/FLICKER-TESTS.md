# Flicker tests on real hardware

Use this when windows flicker on a real computer (Mini PC, laptop). Run the
tests one at a time, write the result in the table at the end and send it
back with the diagnostics report. You don't need to change any system file.
Everything below is either temporary (gone after `hyprctl reload`, a log out
or a reboot) or a single file in your home folder that you delete afterwards.

## What is already set

Checked against the Hyprland 0.55.2 source code and written out in
hyprland.lua (so a future version cannot change them silently); `zeta-selftest
windows` checks that they are in force and that Hyprland reports no
configuration error:

| Setting | Value | Why it matters |
|---|---|---|
| `render:cm_enabled` (colour management) | off | GTK 4.18 apps otherwise draw through Hyprland's colour pipeline; no HDR content in ZETA RAYS |
| `render:use_fp16` | off | experimental 16-bit internal buffer |
| `render:send_content_type` | off | some monitors switch their own picture mode (brightness, colours) on it |
| `render:cm_auto_hdr` | off | never switch to HDR by itself |
| `misc:vrr` (variable refresh rate) | off | VRR makes some monitors flicker in brightness |
| `render:direct_scanout` | off | direct scanout can show one wrong frame when it switches on or off |
| `general:allow_tearing` | off | tearing on purpose, for games only |
| window animations | fade only | `popin` resized the window at every frame while it opened; moves by ZETA are instant |
| `debug:vfr` (draw only when something changes) | on | Hyprland's default |
| `cursor:no_hardware_cursors` | auto (hardware cursor, except NVIDIA with VRR or two GPUs) | in virtual machines: software cursor |
| GTK 4 renderer | OpenGL ("ngl") | GTK 4.18 tries Vulkan first, but the image has no Mesa Vulkan driver, so it falls back to OpenGL. Virtual machines use `cairo` (CPU) |
| GNOME Text Editor | forced light/dark mode removed | this was a confirmed source of flicker (2.0) |

Blur (2 passes, `xray`), shadows, animations and the title bar plugin
(hyprbars) are on. They are the first things to rule out (tests A1 to A4).

## 0. Before the tests

1. Open a terminal inside the desktop (`Super + Enter`) and run:

       sudo zeta-diagnostics

   It prints the path of the report (`~/zeta-diagnostics-DATE.txt`). Section
   7 "GRAPHICS" has what we need: graphics card and driver, Mesa, GTK and
   kernel versions, the displays as Hyprland sees them (resolution, refresh
   rate, scale, VRR, format), the Hyprland options above, Hyprland errors,
   and kernel messages about the display link, firmware and power saving
   (PSR). Run it right after you see the flicker, without rebooting: the
   kernel messages are those of the current boot.
2. Write down: the monitor model, how it is connected (HDMI, DisplayPort,
   USB-C, adapter), the refresh rate and scale shown in Settings › Displays.
3. If you can, record the flicker with a phone in slow motion. One frame of
   flicker is 7 to 17 ms: it is often only visible in slow motion.

## 1. Describe the flicker

These answers tell which layer is at fault, so they are the most useful part.

| Question | Answers |
|---|---|
| What flickers? | (a) the whole screen, bar and wallpaper included; (b) one window only; (c) its title bar only; (d) the mouse pointer; (e) a menu or tooltip; (f) the screen goes black for a second |
| Which apps? | ZETA RAYS apps (Settings, Monitor, launcher), Text Editor, Files (Thunar), Firefox, Thunderbird, terminal (foot), Blender or other X11 apps |
| When? | opening or closing a window, moving it, resizing it, opening a menu, scrolling, playing video, switching workspace, minimizing, waking the screen, with nothing happening |
| How often? | every time / every few minutes / rarely |
| What does it look like? | a black or white frame, an old frame of the same window, garbage, a stripe, brightness change |

Rule of thumb: (a) or (f) points at the display link, the kernel driver, the
monitor or VRR (section C). (b) points at the app or how Hyprland composes
it (sections A and B). (d) points at the hardware cursor (A4). A brightness
change on the whole screen is typically VRR or the monitor's own power saving.

## 2. Base tests (no changes)

Do each for about 30 seconds and note whether the flicker appears.

| ID | Action |
|---|---|
| T1 | Drag a window around by its title bar |
| T2 | Resize a window from the bottom right corner |
| T3 | Open and close Settings, Text Editor and Files five times each |
| T4 | Menus: right-click on the desktop, the Text Editor menu (three lines), Firefox menus; hover over buttons to show tooltips |
| T5 | Video: a 1080p video in Firefox, in a window and full screen; the same file in mpv |
| T6 | Workspaces: `Super + 1`, `Super + 2`, `Super + 3` quickly; three-finger swipe on a touchpad |
| T7 | Leave a Text Editor window open and touch nothing for 5 minutes |
| T8 | Minimize and restore (yellow button, `Super + H`, then from the bar); `Ctrl + Tab` |
| T9 | Lock and unlock (`Super + L`); switch the monitor off and on with its own power button |

Afterwards, repeat only the tests that showed flicker with each change below.

## A. Compositor (Hyprland): temporary changes

Type the commands in a terminal inside the desktop. Each one lasts until
`hyprctl reload` (or the next log out). Run `hyprctl reload` before moving
to the next test, so that only one thing changes at a time.

| ID | Change | Command |
|---|---|---|
| A1 | No blur and no shadows | Settings › Appearance › Effects › "Transparency and blur" off, or `hyprctl eval 'hl.config({ decoration = { blur = { enabled = false }, shadow = { enabled = false } } })'` |
| A2 | No blur "xray" only | `hyprctl eval 'hl.config({ decoration = { blur = { xray = false } } })'` |
| A3 | No animations | Settings › Appearance › Effects › "Animations" off, or `hyprctl eval 'hl.config({ animations = { enabled = false } })'` |
| A4 | Software mouse pointer | `hyprctl eval 'hl.config({ cursor = { no_hardware_cursors = 1 } })'` |
| A5 | Redraw the whole screen every frame (no damage tracking) | `hyprctl eval 'hl.config({ debug = { damage_tracking = 0 } })'` |
| A6 | Draw continuously (no variable frame rate) | `hyprctl eval 'hl.config({ debug = { vfr = false } })'` |
| A7 | New frame scheduling | `hyprctl eval 'hl.config({ render = { new_render_scheduling = true } })'` |
| A8 | No title bars | `hyprctl plugin unload /usr/lib/zeta/hypr/hyprbars.so` (the buttons come back with `hyprctl reload`) |

Check that a change took effect with `hyprctl getoption NAME`, for example
`hyprctl getoption decoration:blur:enabled` or `hyprctl getoption debug:vfr`.
`hyprctl monitors` must show `vrr: false`; if it says `true`, test
`hyprctl eval 'hl.config({ misc = { vrr = 0 } })'` first.
If `hyprctl eval` answers with an error, write the error in the report.

A5 and A6 use more GPU and power: they are only for the test.
If A5 or A6 removes the flicker, it is a redraw bug in Hyprland or in a
driver: tell us which one.

## B. Apps (GTK renderer, Firefox)

Start the app from the terminal with a variable in front. Close the app
first: a second window of an app that is already open does not start a new
process and ignores the variable.

1. Which renderer is in use (the line `Using renderer` or similar is printed
   in the terminal):

       GSK_DEBUG=renderer gnome-text-editor

   `GSK_RENDERER=help gnome-text-editor` lists the renderers this GTK knows.

| ID | Change | Command |
|---|---|---|
| B1 | GTK draws on the CPU | `GSK_RENDERER=cairo gnome-text-editor` |
| B2 | GTK with OpenGL, explicitly | `GSK_RENDERER=ngl gnome-text-editor` (if "ngl" is not listed: `gl`) |
| B3 | No fractional scaling inside GTK (only if the scale is 1.25, 1.5 or 1.6) | `GDK_DEBUG=gl-no-fractional gnome-text-editor` (only if `GDK_DEBUG=help gnome-text-editor` lists it) |
| B4 | No video offload (GTK apps that play video) | `GDK_DISABLE=offload APP` |
| B5 | Scale 1 | Settings › Displays (or Appearance) › scale 100 %, log out and in |
| B6 | Firefox through X11 instead of Wayland | `GDK_BACKEND=x11 firefox-esr` |
| B7 | Firefox without GPU compositing | `about:config` › `gfx.webrender.software` = true, restart Firefox (set it back afterwards) |

To try a GTK setting for the whole session (every app, the ZETA RAYS panels
included) write it to `~/.config/zeta/graphics.env` and log out and in:

    echo GSK_RENDERER=cairo > ~/.config/zeta/graphics.env

Only `GSK_RENDERER`, `GDK_DEBUG`, `GDK_DISABLE` and `GSK_DEBUG` are read,
one per line. Undo it with `rm ~/.config/zeta/graphics.env` and log out and
in. The diagnostics report shows the file when it is there.

If B1 removes the flicker and B2 does not, the GTK OpenGL renderer and the
graphics driver do not get along on this machine: we can set a different
default for that driver only.

## C. Display, kernel driver, monitor

First check which driver the report shows ("drivers in use": `i915` or
`xe` = Intel, `amdgpu` = AMD) and whether "kernel display messages" lists
`FIFO underrun`, `link training`, `flip_done timed out` or firmware errors.

**Monitor and cable** (no software change):

| ID | Change |
|---|---|
| C1 | In the monitor's own menu: Adaptive-Sync / FreeSync off, "dynamic contrast", "eco" and "overdrive" off |
| C2 | Settings › Displays: refresh rate 60 Hz |
| C3 | Another cable, another port (DisplayPort instead of HDMI, or the opposite), no adapter |

**Kernel options for one boot only.** At the boot menu select
"ZETA RAYS OS", press `e`, go to the end of the line that starts with
`linux`, add the option with a space before it, start with `Ctrl + X`
(or `F10`). The option is gone at the next boot. Check that it was applied:
the report's "graphics options on the kernel command line" lists it.

| ID | Driver | Option | What it turns off |
|---|---|---|---|
| C4 | Intel `i915` | `i915.enable_psr=0` | Panel Self Refresh (built-in laptop screens only) |
| C5 | Intel `i915` | `i915.enable_fbc=0` | framebuffer compression |
| C6 | Intel `xe` | `xe.enable_psr=0` | Panel Self Refresh |
| C7 | AMD `amdgpu` | `amdgpu.dcdebugmask=0x10` | Panel Self Refresh |
| C8 | AMD `amdgpu` | `amdgpu.dcdebugmask=0x40` | multi-plane overlay |
| C9 | AMD `amdgpu` (Ryzen with integrated graphics) | `amdgpu.sg_display=0` | display from system memory (known cause of white flashes) |

Only test an option for the driver you have. PSR exists only on built-in
laptop panels (eDP): on a Mini PC with an external monitor C4, C6 and C7
normally change nothing, and the report's "graphics driver settings"
section shows whether PSR is active.

## 3. Report the results

Send back:

1. the report from `sudo zeta-diagnostics` (taken right after the flicker);
2. the answers to section 1;
3. this table, filled in (only the rows you tried):

| Test | Setting | Flicker? (yes / no / less) | Notes |
|---|---|---|---|
| T… | none | | |
| A… | | | |
| B… | | | |
| C… | | | |

4. the slow-motion video, if you have one.

## For the developers: from result to fix

| Result | Fix |
|---|---|
| A1 or A2 removes it | lighter blur defaults on real hardware too, or `xray = false` |
| A4 removes it | `cursor.no_hardware_cursors = 1` for that GPU driver only (from zeta-desktop-session, like the VM case) |
| A5 or A6 removes it | report upstream with the report and video; meanwhile set the option for that driver only |
| A8 removes it | hyprbars issue: report upstream, check `bar_part_of_window` and `bar_precedence_over_border` |
| B1 removes it, B2 does not | GSK renderer default per driver in zeta-desktop-session (it already sets `cairo` in VMs) |
| B3 or B5 removes it | GTK fractional scaling: `GDK_DEBUG=gl-no-fractional` for the session, or prefer integer scales in zeta-display-scale |
| C1 to C3 remove it | monitor, cable or link: nothing to change in the system |
| C4 to C9 removes it | add the option permanently for that driver: a file `/etc/default/grub.d/zz-zeta-flicker.cfg` with `GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT OPTION"`, then `sudo update-grub` |
