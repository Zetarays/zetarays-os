-- SPDX-License-Identifier: GPL-3.0-or-later
-- Runs the real hyprland.lua against a fake "hl" API (no Hyprland needed) and
-- drives the window guard through its timers and events: it catches runtime
-- errors (a misspelled field, a nil call) that a syntax check cannot see.
--
--   lua5.5 tools/tests/test-hyprland-config.lua CONFIG_DIR GUARD_FILE
--
-- CONFIG_DIR is etc/skel/.config/hypr; GUARD_FILE is
-- usr/lib/zeta/hypr/window_guard.lua (hyprland.lua loads it from
-- /usr/lib/zeta/hypr: dofile and io.open are redirected here).

local CONFIG_DIR = arg[1] or "live-build/config/includes.chroot/etc/skel/.config/hypr"
local GUARD_FILE = arg[2] or "live-build/config/includes.chroot/usr/lib/zeta/hypr/window_guard.lua"
local WITH_BARS = (arg[3] or "bars") == "bars"

local passed, failed = 0, 0
local function check(name, cond, detail)
    if cond then passed = passed + 1
    else failed = failed + 1; print("FAIL " .. name .. (detail and (": " .. detail) or "")) end
end

-- redirect the absolute system paths to the source tree
local real_open, real_dofile = io.open, dofile
local RUNTIME = os.tmpname()
os.remove(RUNTIME)
os.execute("mkdir -p " .. RUNTIME)
local function redirect(p)
    if p == "/usr/lib/zeta/hypr/window_guard.lua" then return GUARD_FILE end
    if p == "/usr/lib/zeta/hypr/hyprbars.so" then return WITH_BARS and GUARD_FILE or "/nonexistent" end
    return p
end
io.open = function(p, m) return real_open(redirect(p), m) end
dofile = function(p) return real_dofile(redirect(p)) end
local real_getenv = os.getenv
os.getenv = function(k)
    if k == "XDG_RUNTIME_DIR" then return RUNTIME end
    if k == "HOME" then return "/nonexistent-home" end
    return real_getenv(k)
end
package.path = CONFIG_DIR .. "/?.lua;" .. package.path

-------------------------------------------------------------------- fake world
local monitors = {
    { id = 1, name = "Virtual-1", focused = true, x = 0, y = 0, width = 1920, height = 1080,
      scale = 1, transform = 0, is_mirror = false },
}
local layers = { { namespace = "waybar", x = 12, y = 1008, w = 1896, h = 60, mapped = true, monitor = 1 } }
local wins = {}
local function add_window(t)
    local w = {
        address = t.address, mapped = true, floating = true, fullscreen = t.fullscreen or 0,
        xwayland = t.xwayland or false, title = t.title or "test", class = t.class or "test",
        at = { x = t.x, y = t.y }, size = { x = t.w, y = t.h },
        workspace = { id = 1, name = "1", special = t.special or false },
        monitor = monitors[1],
    }
    wins[#wins + 1] = w
    return w
end

local handlers, timers, binds, notes, dispatched = {}, {}, {}, {}, {}

local function descriptor(name)
    return function(args) return { dsp = name, args = args or {} } end
end
local dsp = setmetatable({}, { __index = function(t, k)
    local sub = setmetatable({}, { __index = function(t2, k2)
        local f = descriptor(k .. "." .. k2); rawset(t2, k2, f); return f end,
        __call = function(_, args) return { dsp = k, args = args or {} } end })
    rawset(t, k, sub)
    return sub
end })

local plugin = {}
hl = {
    dsp = dsp,
    plugin = setmetatable({ load = function() end }, { __index = function(_, k)
        if k == "hyprbars" and WITH_BARS then return plugin.bars end
        return nil end }),
    notification = { create = function(n) notes[#notes + 1] = n.text end },
    config = function() end, monitor = function() end, env = function() end,
    curve = function() end, animation = function() end, gesture = function() end,
    layer_rule = function() end, window_rule = function() end, workspace_rule = function() end,
    exec_cmd = function() end, define_submap = function(_, fn) fn() end,
    bind = function(keys, fn, opts) binds[#binds + 1] = { keys = keys, fn = fn, opts = opts or {} } end,
    on = function(ev, fn) handlers[ev] = handlers[ev] or {}; table.insert(handlers[ev], fn) end,
    timer = function(fn, o) timers[#timers + 1] = { fn = fn, repeating = o.type == "repeat", timeout = o.timeout } end,
    get_windows = function() return wins end,
    get_monitors = function() return monitors end,
    get_layers = function(q)
        local out = {}
        for _, l in ipairs(layers) do if not q or not q.monitor or q.monitor.id == l.monitor then out[#out + 1] = l end end
        return out
    end,
    get_active_window = function() return nil end,
    get_cursor_pos = function() return { x = 5000, y = 5000 } end,
    dispatch = function(d)
        dispatched[#dispatched + 1] = d
        local a = d.args
        local w = a.window
        if type(w) == "table" and w.at then
            if d.dsp == "window.move" and a.x then w.at = { x = a.x, y = a.y } end
            if d.dsp == "window.resize" and a.x then w.size = { x = a.x, y = a.y } end
            if d.dsp == "window.fullscreen" and a.action == "unset" then w.fullscreen = 0 end
        end
    end,
}
plugin.bars = { add_button = function() end }

local function fire(ev, ...)
    for _, fn in ipairs(handlers[ev] or {}) do fn(...) end
end
local function run_oneshots()
    local keep = {}
    local list = timers
    timers = {}
    for _, t in ipairs(list) do
        if t.repeating then keep[#keep + 1] = t else t.fn() end
    end
    for _, t in ipairs(timers) do keep[#keep + 1] = t end
    timers = keep
end
local function tick()
    for _, t in ipairs(timers) do if t.repeating then t.fn() end end
end

-------------------------------------------------------------------- load
local ok, err = pcall(real_dofile, CONFIG_DIR .. "/hyprland.lua")
check("hyprland.lua runs", ok, tostring(err))
if not ok then print(string.format("hyprland config: %d passed, %d failed", passed, failed)); os.exit(1) end

check("guard ready", zeta_window_guard_ready == true)
check("no error notification", #notes == 0, table.concat(notes, " | "))
local f = real_open(RUNTIME .. "/zeta-title-bars")
check("title bar flag written", f ~= nil)
if f then check("title bar flag value", f:read("l") == (WITH_BARS and "1" or "0")); f:close() end
local BAR = WITH_BARS and 32 or 0

-- keyboard exits
local want = { "close", "minimize", "maximize", "fullscreen", "windows", "recover",
               "force-pick", "force-active", "emergency", "drag", "resize" }
local have = {}
for _, b in ipairs(binds) do
    local d = b.opts.description
    if d and d:match("^zeta%-exit:") then have[d:sub(11)] = b end
end
for _, name in ipairs(want) do check("bind " .. name, have[name] ~= nil) end

-------------------------------------------------------------------- the guard at work
-- the selftest's window: off screen and huge
local w1 = add_window { address = "0x1", x = -400, y = -300, w = 2600, h = 1800 }
tick(); tick()
check("gentle pass: huge window shrunk", w1.size.x == 1904 and w1.size.y == 1008 - BAR - 16,
      w1.size.x .. "x" .. w1.size.y)
check("gentle pass: title bar inside", w1.at.y - BAR >= 0 and w1.at.x >= 0, w1.at.x .. "," .. w1.at.y)

-- window.open: strict at 300/1200 ms
local w2 = add_window { address = "0x2", x = 3000, y = 2000, w = 400, h = 300 }
fire("window.open", w2)
run_oneshots()
check("window.open: dialog inside", w2.at.x == 1520 and w2.at.y == 708, w2.at.x .. "," .. w2.at.y)

-- untitled X11 menu: never touched
local menu = add_window { address = "0x3", x = -50, y = 900, w = 150, h = 400, xwayland = true, title = "" }
tick(); tick()
check("menu untouched", menu.at.x == -50)

-- monitor removed: the window's monitor is gone
local w4 = add_window { address = "0x4", x = 2500, y = 300, w = 800, h = 600 }
w4.monitor = nil
fire("monitor.removed", {})
run_oneshots()
check("monitor removed: window back", w4.at.x == 1120, w4.at.x .. "," .. w4.at.y)

-- scale change to 2: logical 960x540, bar moves to y=468
monitors[1].scale = 2
layers[1].y, layers[1].w = 468, 936
fire("monitor.layout_changed")
run_oneshots()
for _, w in ipairs({ w1, w2, w4 }) do
    check("scale change: " .. w.address .. " fits",
          w.at.x >= 0 and w.at.y - BAR >= 0 and w.at.x + w.size.x <= 960 and w.at.y + w.size.y <= 468,
          string.format("%d,%d %dx%d", w.at.x, w.at.y, w.size.x, w.size.y))
end

-- restored from the hidden workspace at its old place
local w5 = add_window { address = "0x5", x = 1500, y = 900, w = 300, h = 200 }
fire("window.move_to_workspace", w5, w5.workspace)
run_oneshots()
check("restored window reachable", w5.at.x + 96 <= 960 and w5.at.y <= 468, w5.at.x .. "," .. w5.at.y)

-- Super+Shift+W: full screen left, then back inside
local w6 = add_window { address = "0x6", x = 0, y = 0, w = 960, h = 540, fullscreen = 2 }
have["recover"].fn()
check("recover: full screen left", w6.fullscreen == 0)
run_oneshots()
check("recover: inside after leaving full screen", w6.at.y - BAR >= 0 and w6.at.y + w6.size.y <= 468)

-- a monitor still being set up (no mode yet) is ignored
monitors[2] = { id = 2, name = "HDMI-A-1", focused = false, x = 960, y = 0, width = 0, height = 0,
                scale = 1, transform = 0, is_mirror = false }
fire("monitor.added", monitors[2])
run_oneshots(); tick(); tick()
check("monitor without a mode: windows keep their size", w1.size.x == 944, w1.size.x .. "x" .. w1.size.y)
monitors[2] = nil

-- a minimized window is never touched
local w7 = add_window { address = "0x7", x = -9000, y = -9000, w = 300, h = 200, special = true }
tick(); tick(); zeta_recover(); run_oneshots()
check("minimized untouched", w7.at.x == -9000)
-- errors inside the guard are caught and shown as a notification
check("no runtime errors", #notes == 0, table.concat(notes, " | "))

os.execute("rm -rf " .. RUNTIME)
print(string.format("hyprland config (%s): %d passed, %d failed", WITH_BARS and "title bars" or "no title bars", passed, failed))
os.exit(failed == 0 and 0 or 1)
