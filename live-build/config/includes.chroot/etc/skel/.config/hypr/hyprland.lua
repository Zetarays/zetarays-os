-- SPDX-License-Identifier: GPL-3.0-or-later
-- ZETA RAYS — Hyprland configuration (0.55, Lua format)

-- Accent color: the zeta_colors.lua file is written by zeta-accent
local ok, colors = pcall(require, "zeta_colors")
if not ok or type(colors) ~= "table" then
    colors = { accent = "rgb(3A8DFF)" }
end

-- Virtual machine (VirtualBox, QEMU...): zeta-desktop-session writes zeta_vm.lua.
-- In VMs the hardware cursor is often invisible, so we use the software one.
-- When pcall fails it returns the error message in place of the value: it
-- must be reduced to a real boolean, otherwise an error string would count
-- as "I am in a VM" and throw off the effects below.
local vm_ok, vm_val = pcall(require, "zeta_vm")
local is_vm = (vm_ok and vm_val == true)
if is_vm then
    -- in VMs the hardware cursor is often invisible
    hl.config({ cursor = { no_hardware_cursors = true } })
end

-------------------
---- MONITORS ----
-------------------

-- Scale computed at startup by zeta-display-scale (real DPI from the EDID).
-- Hyprland's "auto" scale gets it wrong without an EDID (in VMs it picks 2x).
local mon_ok, mon = pcall(require, "zeta_monitor")
local monitor_scale = (mon_ok and type(mon) == "table" and mon.scale) or 1

hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = monitor_scale,
})

-- Settings › Displays: resolution, refresh rate, scale, rotation, position,
-- mirroring and primary display, remembered per display (make, model, serial
-- number). Rules for a specific display take precedence over the general one
-- above, which remains for displays that were never configured.
-- The file exists only after the first "Keep" in Settings: Hyprland reports a
-- require of a module that does not exist as a configuration error (red box)
-- even inside pcall, so we check for the file first.
local disp_file = io.open(os.getenv("HOME") .. "/.config/hypr/zeta_displays.lua", "r")
local disp_ok, apply_displays = false, nil
if disp_file then
    disp_file:close()
    disp_ok, apply_displays = pcall(require, "zeta_displays")
end
if disp_ok and type(apply_displays) == "function" then
    local ok_s, err_s = pcall(apply_displays)
    if not ok_s then hl.notification.create({ text = "zeta_displays: " .. tostring(err_s), timeout = 5000 }) end
    -- at startup the displays are connected after the configuration is read:
    -- mirroring, which needs the connector name, is reapplied when they appear
    hl.on("monitor.added", function() pcall(apply_displays) end)
end

-------------------
---- STARTUP ----
-------------------

hl.on("hyprland.start", function()
    hl.exec_cmd("zeta-session")
end)

-- Pointer size chosen in Settings > Appearance (zeta-appearance)
-- Keyboard layout of the system (installer, Settings > Language & Region):
-- zeta-desktop-session writes zeta_keyboard.lua from /etc/default/keyboard.
local kb_ok, kb = pcall(require, "zeta_keyboard")
if not kb_ok or type(kb) ~= "table" then kb = {} end
local asp_ok, asp = pcall(require, "zeta_appearance")
local cursor_size = (asp_ok and type(asp) == "table" and asp.cursor) or 24
local light_theme = asp_ok and type(asp) == "table" and asp.theme == "light"
-- Effects chosen in Settings › Appearance. Turning them off makes the desktop
-- more responsive on slow machines; the defaults stay the ZETA RAYS ones.
local asp_t = (asp_ok and type(asp) == "table") and asp or {}
local animations   = asp_t.animations ~= false
local transparency = asp_t.transparency ~= false
local corners      = tonumber(asp_t.corners) or 14

hl.env("XCURSOR_SIZE", tostring(cursor_size))
hl.env("HYPRCURSOR_SIZE", tostring(cursor_size))
hl.env("QT_QPA_PLATFORM", "wayland;xcb")

-------------------
---- APPEARANCE ----
-------------------

hl.config({
    general = {
        gaps_in     = 6,
        gaps_out    = 12,
        border_size = 1,
        col = {
            active_border   = colors.accent,
            inactive_border = light_theme and "rgba(00000018)" or "rgba(ffffff14)",
        },
        resize_on_border = true,
        layout = "dwindle",
    },

    decoration = {
        rounding       = corners,
        rounding_power = 2,
        active_opacity   = 1.0,
        inactive_opacity = 1.0,

        -- The cost of the effects adapts to the machine. Blur and shadows are
        -- the compositor's heaviest operation: "passes = 3" redoes the
        -- computation three times over the whole blurred area. On a real
        -- computer with a GPU you do not notice it; inside a virtual machine,
        -- where everything is drawn by the CPU, it is the main reason the
        -- desktop felt slow. In VMs the same glass look is kept, but with a
        -- single pass and a small radius: it costs about an eighth.
        shadow = {
            enabled      = transparency and not is_vm,
            range        = 40,
            render_power = 3,
            color        = 0xaa000000,
        },

        blur = {
            enabled  = transparency,
            size     = is_vm and 4 or 10,
            -- two passes: looks almost the same as three, a third less work
            passes   = is_vm and 1 or 2,
            vibrancy = 0.17,
            -- do not re-blur what is already behind an opaque window
            new_optimizations = true,
            xray              = true,
        },
    },

    animations = {
        enabled = animations,
    },

    dwindle = {
        preserve_split = true,
    },

    misc = {
        force_default_wallpaper = 0,
        disable_hyprland_logo   = true,
        disable_splash_rendering = true,
        background_color        = light_theme and 0xfff6f6f8 or 0xff000000,
        -- if the lock screen exits, a new one can take over the session
        allow_session_lock_restore = true,
        -- display standby: keyboard or mouse wake it up
        key_press_enables_dpms   = true,
        mouse_move_enables_dpms  = true,
    },

    input = {
        kb_layout    = kb.layout or "us",
        kb_variant   = kb.variant or "",
        kb_options   = kb.options or "",
        follow_mouse = 1,
        touchpad = {
            natural_scroll = true,
        },
    },
})

-- Animations: smooth and quick
hl.curve("zeta",   { type = "bezier", points = { {0.2, 0.9}, {0.1, 1} } })
hl.curve("linear", { type = "bezier", points = { {0, 0},     {1, 1}   } })
hl.curve("soft",   { type = "spring", mass = 1, stiffness = 80, dampening = 16 })

hl.animation({ leaf = "global",     enabled = true, speed = 8,   bezier = "zeta" })
hl.animation({ leaf = "border",     enabled = true, speed = 5,   bezier = "zeta" })
hl.animation({ leaf = "windowsIn",  enabled = true, speed = 4,   spring = "soft",   style = "popin 90%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 1.5, bezier = "linear", style = "popin 90%" })
-- Moves and resizes made by ZETA (the window guard bringing a window back,
-- small main windows enlarged when they open) are instant: animated, the
-- old content was shown stretched for a few frames and then redrawn at the
-- new size, which looked like the window was trembling (frames captured on
-- 17 October 2026). Dragging with the mouse is never animated anyway.
hl.animation({ leaf = "windowsMove", enabled = false })
hl.animation({ leaf = "fade",       enabled = true, speed = 3,   bezier = "zeta" })
hl.animation({ leaf = "layersIn",   enabled = true, speed = 3,   bezier = "zeta",   style = "fade" })
hl.animation({ leaf = "layersOut",  enabled = true, speed = 1.5, bezier = "linear", style = "fade" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 3,   bezier = "zeta",   style = "slide" })

hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

-------------------
---- TITLE BARS ----
-------------------

-- Hyprland draws no decorations: without this plugin no window would have
-- close / minimize / maximize. The plugin is compiled at build time against
-- this very Hyprland version (hook 0400).
-- On first startup the plugin is not loaded yet when the configuration is
-- read: zeta-session runs a "hyprctl reload" that completes the cycle.
local BARS = "/usr/lib/zeta/hypr/hyprbars.so"
local bars_file = io.open(BARS, "r")
if bars_file then
    bars_file:close()
    hl.plugin.load(BARS)
end

if hl.plugin.hyprbars then
    hl.config({
        plugin = {
            hyprbars = {
                enabled                    = true,
                bar_height                 = 32,
                -- the title bar follows the theme chosen in Settings
                bar_color                  = light_theme and "rgba(F2F2F4F2)" or "rgba(1C1C1EF2)",
                col                        = { text = light_theme and "rgb(1C1C1E)" or "rgb(EDEDEA)" },
                bar_text_size              = 11,
                bar_text_font              = "Roboto",
                bar_text_align             = "center",
                bar_buttons_alignment      = "left",
                bar_padding                = 12,
                bar_button_padding         = 8,
                bar_part_of_window         = true,
                bar_precedence_over_border = true,
                -- the bar is 95% opaque: the blur behind it was not visible,
                -- but it was computed for every window on every frame
                bar_blur                   = false,
                icon_on_hover              = true,
                on_double_click            = [[hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = "maximized" })']],
            },
        },
    })

    -- Order from the left: close, minimize, maximize.
    hl.plugin.hyprbars.add_button({
        bg_color = "rgb(FF5F57)", fg_color = "rgba(00000099)", size = 13, icon = "×",
        action = [[hyprctl dispatch 'hl.dsp.window.close()']],
    })
    hl.plugin.hyprbars.add_button({
        bg_color = "rgb(FEBC2E)", fg_color = "rgba(00000099)", size = 13, icon = "–",
        action = "zeta-windows minimize",
    })
    hl.plugin.hyprbars.add_button({
        bg_color = "rgb(28C840)", fg_color = "rgba(00000099)", size = 13, icon = "+",
        action = [[hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = "maximized" })']],
    })
end

-------------------
---- RULES ----
-------------------

-- Bar, launcher and notifications with the glass effect
hl.layer_rule({ name = "zeta-bar-blur",      match = { namespace = "^waybar$" },        blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-launcher-blur", match = { namespace = "^zeta-launcher$" }, blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-search-blur",   match = { namespace = "^zeta-search$" },    blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-notify-blur",   match = { namespace = "^notifications$" }, blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-control-blur",  match = { namespace = "^zeta-control$" },  blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-power-blur",    match = { namespace = "^zeta-power-menu$" },  blur = true, ignore_alpha = 0.1 })
hl.layer_rule({ name = "zeta-switcher-blur", match = { namespace = "^zeta-switcher$" }, blur = true, ignore_alpha = 0.1 })
-- the snapshot of the window being minimized must appear instantly, on top
-- of the real window: with a fade a jump would be visible (zeta-minimize)
hl.layer_rule({ name = "zeta-minimize-instant", match = { namespace = "^zeta-minimize$" }, no_anim = true })

-- Floating, centered windows, as on macOS (Super + V to tile them), never
-- larger than the screen: on small screens nothing ends up under the bar.
hl.window_rule({ name = "zeta-float-all", match = { class = ".*" }, float = true, center = true,
                 max_size = "(monitor_w*0.92) (monitor_h*0.84)" })
-- Mail: on first launch Thunderbird does not request a size and the main
-- window opened tiny (250x300). Only main windows (title "... - Mozilla
-- Thunderbird"), not dialogs; afterwards it remembers the size by itself.
hl.window_rule({ name = "zeta-mail-size",
                 match = { class = "^thunderbird$", title = ".*Mozilla Thunderbird$" },
                 size = "(monitor_w*0.8) (monitor_h*0.78)" })
-- Firefox: same thing on first launch (small window, the ZETA RAYS start page
-- was only half visible). Only main windows.
hl.window_rule({ name = "zeta-browser-size",
                 match = { class = "^firefox-esr$", title = ".*Mozilla Firefox$" },
                 size = "(monitor_w*0.8) (monitor_h*0.78)" })
-- Blender: the main window is always large, like the system package's one.
-- Versions downloaded from blender.org (5.x) open on Wayland under another
-- name (org.blender.Blender) with a small default size; the system one goes
-- through X11 as "Blender". Only the main window ("Blender", "Blender
-- [file]", "file - Blender 5.2", and also "(Unsaved) - Blender 5.2.2 LTS":
-- without the "LTS" suffix the rule did not fire and 5.2.2 started on
-- Wayland opened at 320x240): Preferences, Render and the file dialogs keep
-- their own size.
hl.window_rule({ name = "zeta-blender-size",
                 match = { class = "^([Bb]lender|org\\.blender\\.Blender)$",
                           title = "^(Blender|Blender\\*?( \\[.*\\])?|.* - Blender( [0-9.]+)?( [A-Za-z][A-Za-z ]*)?)$" },
                 size = "(monitor_w*0.92) (monitor_h*0.84)" })
-- the compose window, by its title in English or Italian (the Italian words
-- are language data: thunderbird_compose_titles in i18n-data/hyprland.json,
-- a list of plain words read without a JSON library)
local function zeta_i18n_words(key)
    local words = {}
    local f = io.open("/usr/share/zeta/i18n-data/hyprland.json", "r")
    if not f then return words end
    local text = f:read("*a") or ""
    f:close()
    local list = text:match('"' .. key .. '"%s*:%s*%[(.-)%]')
    for word in (list or ""):gmatch('"([^"]*)"') do
        words[#words + 1] = word
    end
    return words
end
local compose_titles = zeta_i18n_words("thunderbird_compose_titles")
compose_titles[#compose_titles + 1] = "Compose"
compose_titles[#compose_titles + 1] = "Write"
hl.window_rule({ name = "zeta-mail-compose",
                 match = { class = "^thunderbird$", title = "^(" .. table.concat(compose_titles, "|") .. "): .*" },
                 size = "(monitor_w*0.62) (monitor_h*0.72)" })

-- Main windows that open small. Here every window is floating, and a program
-- with no saved size opens at its factory minimum size (Thunar 640x480, the
-- text editor 700x520): on a large screen it looked like a "collapsed" window
-- to be enlarged by hand.
-- Only main windows are enlarged: a program's first window, or a new one
-- with the same title ending ("... - Thunar"). Dialogs (Preferences, Copy
-- files, Authenticate, Properties) stay as they are, and so does a program
-- that already remembers a large size.
local ZETA_DO_NOT_ENLARGE = { "^zenity$", "^yad$", "^kdialog$", "^polkit", "^pinentry",
    "portal", "^gcr%-prompter$", "^zeta%-", "^org%.zetarays%.", "^nm%-", "^blueman" }

local function zeta_title_suffix(t)
    return (t or ""):match(" [-—] ([^-—]+)$")
end

local function zeta_is_main_window(w)
    local suffix = zeta_title_suffix(w.title)
    local others = 0
    for _, a in ipairs(hl.get_windows()) do
        if a.address ~= w.address and a.class == w.class and a.mapped then
            others = others + 1
            if suffix and zeta_title_suffix(a.title) == suffix then return true end
        end
    end
    return others == 0
end

-------------------
---- WINDOWS ALWAYS REACHABLE ----
-------------------

-- No window may end up where it cannot be closed, minimized, moved or
-- reached. An X11 program can move itself after opening (even to negative
-- coordinates) or ask for a size larger than the screen; unplugging a
-- monitor or changing resolution or scale can leave a window outside; a
-- dialog can place itself off screen. Here, in the compositor itself (no
-- second window manager), every floating window keeps its title bar and
-- buttons (on the left) inside the usable area: the screen minus the
-- ZETA RAYS bar. The decisions live in /usr/lib/zeta/hypr/window_guard.lua
-- (plain Lua, unit-tested outside Hyprland); here they are connected to
-- Hyprland's timers, events and dispatchers.
-- The title bar (hyprbars) sits ABOVE the window position.
local ZG_BAR = hl.plugin.hyprbars and 32 or 0

-- Tell the rest of the desktop whether title bars (and their buttons) are
-- there: without them the bar always shows the Windows button
-- (zeta-windows button / count), so every window can still be closed or minimized
-- with the mouse.
do
    local rt = os.getenv("XDG_RUNTIME_DIR")
    local f = rt and io.open(rt .. "/zeta-title-bars", "w")
    if f then
        f:write(ZG_BAR > 0 and "1\n" or "0\n")
        f:close()
    end
end

local ZG_LIB_FILE = "/usr/lib/zeta/hypr/window_guard.lua"
local zg_lib, zg_error = nil, "missing"
do
    -- checked first: a missing file must not become a configuration error
    local f = io.open(ZG_LIB_FILE, "r")
    if f then
        f:close()
        local ok, lib = pcall(dofile, ZG_LIB_FILE)
        if ok and type(lib) == "table" then zg_lib = lib else zg_error = tostring(lib) end
    end
end

-- Snapshot of a Hyprland window as plain values (each field read once).
local function zeta_snapshot(w)
    local at, size, ws, m = w.at, w.size, w.workspace, w.monitor
    return {
        ref = w, address = w.address,
        x = at.x, y = at.y, w = size.x, h = size.y,
        mapped = w.mapped, floating = w.floating, fullscreen = w.fullscreen,
        xwayland = w.xwayland, title = w.title, class = w.class,
        has_workspace = ws ~= nil, special = ws ~= nil and ws.special or false,
        monitor = m and m.id or nil,
    }
end

-- Usable area of every monitor, in logical coordinates (like windows).
local function zeta_areas()
    local out = {}
    for _, m in ipairs(hl.get_monitors()) do
        if not m.is_mirror then
            local ls = {}
            local ok, layers = pcall(hl.get_layers, { monitor = m })
            if ok and type(layers) == "table" then
                for _, l in ipairs(layers) do
                    ls[#ls + 1] = { namespace = l.namespace, x = l.x, y = l.y,
                                    w = l.w, h = l.h, mapped = l.mapped }
                end
            end
            out[#out + 1] = zg_lib.usable_area({ id = m.id, focused = m.focused,
                x = m.x, y = m.y, width = m.width, height = m.height,
                scale = m.scale, transform = m.transform }, ls)    -- nil: skipped
        end
    end
    return out
end

local zg_guard
if zg_lib then
    zg_guard = zg_lib.new({
        windows = function()
            local out = {}
            for _, w in ipairs(hl.get_windows()) do out[#out + 1] = zeta_snapshot(w) end
            return out
        end,
        areas = zeta_areas,
        active = function()
            local w = hl.get_active_window()
            return w and w.address or nil
        end,
        cursor = function()
            local ok, c = pcall(hl.get_cursor_pos)
            return ok and c or nil
        end,
        resize = function(s, W, H)
            hl.dispatch(hl.dsp.window.resize({ x = W, y = H, window = s.ref }))
            local size = s.ref.size
            return size.x, size.y
        end,
        move = function(s, X, Y)
            hl.dispatch(hl.dsp.window.move({ x = X, y = Y, window = s.ref }))
            local at = s.ref.at
            return at.x, at.y
        end,
        unfullscreen = function(s)
            hl.dispatch(hl.dsp.window.fullscreen({ mode = "fullscreen", action = "unset", window = s.ref }))
        end,
        later = function(ms, fn)
            hl.timer(fn, { timeout = ms, type = "oneshot" })
        end,
    }, ZG_BAR)
    -- an unexpected error must not repeat every 1.5 seconds: shown once
    local reported = false
    for _, name in ipairs({ "check_all", "check_one", "recover", "reset" }) do
        local fn = zg_guard[name]
        zg_guard[name] = function(...)
            local ok, res = pcall(fn, ...)
            if not ok and not reported then
                reported = true
                hl.notification.create({ text = "window_guard: " .. tostring(res), timeout = 8000 })
            end
            return ok and res or false
        end
    end
end

-- Usable area of one monitor (used below to enlarge small main windows).
local function zeta_area(m)
    if not zg_lib then
        local sc = (m.scale and m.scale > 0) and m.scale or 1
        return { x0 = m.x, y0 = m.y, x1 = m.x + m.width / sc, y1 = m.y + m.height / sc }
    end
    for _, a in ipairs(zeta_areas()) do
        if a.id == m.id then return a end
    end
    return zeta_areas()[1]
end

-- Manual recovery (Super + Shift + W, "zeta-windows recover", the Windows
-- list, Settings › Displays): full screen windows leave full screen, then
-- every window goes back inside its screen, even those left alone.
function zeta_recover()
    if zg_guard then zg_guard.recover() end
end
-- checked by zeta-selftest (hyprctl eval)
zeta_window_guard_ready = zg_guard ~= nil
if not zg_guard then
    hl.notification.create({ text = "window_guard: " .. zg_error, timeout = 8000 })
end

if zg_guard then
    -- periodic gentle pass: title bar and buttons reachable
    hl.timer(function() zg_guard.check_all("gentle") end, { timeout = 1500, type = "repeat" })
    -- display added, removed, disabled, new resolution or scale: everything
    -- back inside (twice: Hyprland moves the workspaces of a removed
    -- monitor a moment later)
    for _, ev in ipairs({ "monitor.added", "monitor.removed", "monitor.layout_changed" }) do
        hl.on(ev, function()
            for _, t in ipairs({ 600, 2000 }) do
                hl.timer(function() zg_guard.reset(); zg_guard.check_all("strict") end,
                         { timeout = t, type = "oneshot" })
            end
        end)
    end
    -- a window coming back from a hidden workspace (restored after being
    -- minimized, possibly on a display that is gone) or moved to another
    -- workspace: reachable at once
    hl.on("window.move_to_workspace", function(w, ws)
        if not w or (ws and ws.special) then return end
        local addr = w.address
        hl.timer(function() zg_guard.check_one(addr, "now") end, { timeout = 200, type = "oneshot" })
    end)
    hl.on("workspace.move_to_monitor", function()
        hl.timer(function() zg_guard.check_all("now") end, { timeout = 300, type = "oneshot" })
    end)
end

hl.on("window.open", function(w)
    -- Blender on Wayland draws a smaller interface at fractional scales: a
    -- Blender just started on Wayland (downloaded from blender.org and run
    -- directly, for example) is reopened through X11, like ZETA's launchers
    -- do (/usr/libexec/zeta-blender-x11 explains the details)
    if not w.xwayland and (w.class == "blender" or w.class == "Blender"
                           or w.class == "org.blender.Blender") then
        local pid = tonumber(w.pid)
        local first = true                 -- the program's first window
        for _, a in ipairs(hl.get_windows()) do
            if a.address ~= w.address and tonumber(a.pid) == pid then first = false end
        end
        if pid and pid > 1 and first then
            hl.exec_cmd("/usr/libexec/zeta-blender-x11 " .. math.floor(pid))
            return
        end
    end
    -- an X11 program often moves itself right after opening
    local addr = w.address
    if zg_guard then
        for _, t in ipairs({ 300, 1200 }) do
            hl.timer(function() zg_guard.check_one(addr, "strict") end, { timeout = t, type = "oneshot" })
        end
    end

    if not w.floating or w.fullscreen ~= 0 or w.class == "" then return end
    for _, p in ipairs(ZETA_DO_NOT_ENLARGE) do
        if w.class:find(p) then return end
    end
    local m = w.monitor
    if not m then return end
    local a = zeta_area(m)
    if not a then return end
    local mw, mh = a.x1 - a.x0, a.y1 - a.y0
    local W, H = w.size.x, w.size.y
    if W * H >= mw * mh * 0.42 then return end           -- already large
    if W < 560 or H < 380 then return end                -- dialog size
    if not zeta_is_main_window(w) then return end
    local nw, nh = math.floor(mw * 0.72), math.floor(mh * 0.76)
    -- same center as before (the "center" rule had already centered it),
    -- inside the usable area, with the title bar below the edge
    local nx = math.max(a.x0, math.min(w.at.x - (nw - W) // 2, a.x1 - nw))
    local ny = math.max(a.y0 + ZG_BAR, math.min(w.at.y - (nh - H) // 2, a.y1 - nh))
    hl.dispatch(hl.dsp.window.resize({ x = nw, y = nh, window = w }))
    hl.dispatch(hl.dsp.window.move({ x = nx, y = ny, window = w }))
end)

hl.window_rule({
    name  = "fix-xwayland-drags",
    match = { class = "^$", title = "^$", xwayland = true, float = true, fullscreen = false, pin = false },
    no_focus = true,
})

-------------------
---- SHORTCUTS ----
-------------------

local mod = "SUPER"

hl.bind(mod .. " + SUPER_L",     hl.dsp.exec_cmd("zeta-panel launcher"), { release = true })
hl.bind(mod .. " + SPACE",       hl.dsp.exec_cmd("zeta-panel launcher"))
hl.bind(mod .. " + S",           hl.dsp.exec_cmd("zeta-panel search"))
-- the apps chosen in Settings › Default Apps
hl.bind(mod .. " + RETURN",      hl.dsp.exec_cmd("zeta-default-app terminal"))
hl.bind(mod .. " + E",           hl.dsp.exec_cmd("zeta-default-app file"))
hl.bind(mod .. " + B",           hl.dsp.exec_cmd("zeta-default-app browser"))
hl.bind(mod .. " + I",           hl.dsp.exec_cmd("zeta-settings"))
hl.bind(mod .. " + T",           hl.dsp.exec_cmd("zeta-appearance toggle-theme"))
-- The ways out of any window state work from the keyboard too, also when a
-- window covers the bar or has no title bar: close, minimize, maximize,
-- full screen, Windows list, bring back (Super + Shift + W), force quit.
-- The "zeta-exit:" descriptions are checked by zeta-selftest and the same
-- list is shown in the Windows list (zeta-windows).
hl.bind(mod .. " + Q",           hl.dsp.window.close(), { description = "zeta-exit:close" })
hl.bind(mod .. " + F",           hl.dsp.window.fullscreen(), { description = "zeta-exit:fullscreen" })
hl.bind(mod .. " + V",           hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + SHIFT + S",   hl.dsp.exec_cmd("sh -c 'grim -g \"$(slurp)\" - | wl-copy'"))
-- Text from an area of the screen (OCR, done locally), like Windows' Text
-- Extractor: select an area, the text ends up in the clipboard.
hl.bind(mod .. " + SHIFT + T",   hl.dsp.exec_cmd("zeta-text-capture"))
hl.bind(mod .. " + SHIFT + E",   hl.dsp.exec_cmd("zeta-panel power"))
hl.bind(mod .. " + ESCAPE",      hl.dsp.exec_cmd("zeta-panel power"))
hl.bind(mod .. " + L",           hl.dsp.exec_cmd("hyprlock"))
hl.bind(mod .. " + A",           hl.dsp.exec_cmd("zeta-panel control"))
hl.bind(mod .. " + W",           hl.dsp.exec_cmd("zeta-windows"), { description = "zeta-exit:windows" })
-- every window back inside the screen, with its buttons within reach
hl.bind(mod .. " + SHIFT + W",   function() zeta_recover() end, { description = "zeta-exit:recover" })
-- Force quit, like Cmd+Alt+Esc on macOS and Ctrl+Shift+Esc on Windows:
-- it is needed when a program stops responding, so it goes through neither
-- the frozen program nor its menu.
-- Ctrl+Alt+Esc: crosshair, click the frozen window (background = full list).
-- Ctrl+Shift+Esc: emergency, closes the active window immediately, with no
-- interface: it works even when a panel struggles to open.
-- NOT Ctrl+Alt+Shift+Esc: with systemd 257 that is logind's "Secure
-- Attention Key", which opens a new login screen (tested: you end up at the
-- login with the session still open behind it).
hl.bind("CTRL + ALT + ESCAPE", hl.dsp.exec_cmd("zeta-windows pick"), { description = "zeta-exit:force-pick" })
hl.bind("CTRL + SHIFT + ESCAPE", hl.dsp.exec_cmd("zeta-windows active"), { description = "zeta-exit:force-active" })
-- Ctrl+Alt+Del: emergency panel (task manager, frozen program, terminal,
-- desktop restore, lock, log out, restart, shut down). Hyprland handles it:
-- a frozen app cannot block it. NOT while the screen is locked: the panel
-- can open a terminal, and the lock must be respected.
hl.bind("CTRL + ALT + Delete", hl.dsp.exec_cmd("zeta-emergency"), { description = "zeta-exit:emergency" })
hl.bind(mod .. " + H",           hl.dsp.exec_cmd("zeta-windows minimize"), { description = "zeta-exit:minimize" })

-- App switcher, like Cmd+Tab on macOS but with Ctrl (works on any keyboard).
-- Ctrl+Tab opens the switcher and enters the "zeta-switcher" submap: there
-- Tab and Shift+Tab cycle, releasing Ctrl brings the chosen app to the
-- front, Esc cancels, Ctrl+Q closes the chosen app. Outside the submap no
-- other key changes. To switch tabs inside apps (Firefox, terminal, editor)
-- Ctrl+PgDn / Ctrl+PgUp still work.
hl.bind("CTRL + TAB", function()
    hl.dispatch(hl.dsp.exec_cmd("zeta-switcher open"))
    hl.dispatch(hl.dsp.submap("zeta-switcher"))
end)
hl.bind("CTRL + SHIFT + TAB", function()
    hl.dispatch(hl.dsp.exec_cmd("zeta-switcher open_back"))
    hl.dispatch(hl.dsp.submap("zeta-switcher"))
end)
hl.define_submap("zeta-switcher", function()
    hl.bind("CTRL + TAB",         hl.dsp.exec_cmd("zeta-switcher next"),     { repeating = true })
    hl.bind("CTRL + SHIFT + TAB", hl.dsp.exec_cmd("zeta-switcher back"),     { repeating = true })
    hl.bind("CTRL + Q",           hl.dsp.exec_cmd("zeta-switcher close"))
    for _, key in ipairs({ "ESCAPE", "CTRL + ESCAPE", "CTRL + SHIFT + ESCAPE" }) do
        hl.bind(key, function()
            hl.dispatch(hl.dsp.exec_cmd("zeta-switcher cancel"))
            hl.dispatch(hl.dsp.submap("reset"))
        end)
    end
    -- releasing Ctrl (left or right): switch to the chosen app
    for _, key in ipairs({ "Control_L", "Control_R" }) do
        hl.bind(key, function()
            hl.dispatch(hl.dsp.exec_cmd("zeta-switcher activate"))
            hl.dispatch(hl.dsp.submap("reset"))
        end, { release = true, ignore_mods = true, transparent = true })
    end
end)
hl.bind(mod .. " + M",           hl.dsp.window.fullscreen({ mode = "maximized" }), { description = "zeta-exit:maximize" })

hl.bind(mod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mod .. " + down",  hl.dsp.focus({ direction = "down" }))

for i = 1, 3 do
    hl.bind(mod .. " + " .. i,         hl.dsp.focus({ workspace = i }))
    hl.bind(mod .. " + SHIFT + " .. i, hl.dsp.window.move({ workspace = i }))
end

hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true, description = "zeta-exit:drag" })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true, description = "zeta-exit:resize" })

hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd("zeta-volume up"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd("zeta-volume down"),     { locked = true, repeating = true })
hl.bind("XF86AudioMute",         hl.dsp.exec_cmd("zeta-volume mute"),     { locked = true })
hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd("brightnessctl set 5%+"),                          { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl set 5%-"),                          { locked = true, repeating = true })
