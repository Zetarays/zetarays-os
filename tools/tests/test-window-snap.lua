-- SPDX-License-Identifier: GPL-3.0-or-later
-- Unit tests for the ZETA RAYS snap layouts (usr/lib/zeta/hypr/window_snap.lua),
-- outside Hyprland: a fake adapter records what would be dispatched.
--
--   lua5.5 tools/tests/test-window-snap.lua [path/to/window_snap.lua]
--
-- Hyprland 0.55 embeds Lua 5.5; the tests also run on 5.4.

local path = arg[1] or "live-build/config/includes.chroot/usr/lib/zeta/hypr/window_snap.lua"
local S = dofile(path)

local passed, failed = 0, 0
local function check(name, cond, detail)
    if cond then
        passed = passed + 1
    else
        failed = failed + 1
        print("FAIL " .. name .. (detail and (": " .. detail) or ""))
    end
end
local function eq(name, got, want)
    check(name, got == want, "got " .. tostring(got) .. ", want " .. tostring(want))
end
local function rect_s(r) return string.format("%d,%d %dx%d", r.x, r.y, r.w, r.h) end

-- 1920x1080 with the bar at the bottom: usable area 0..1920 x 0..1008
local A = { id = 1, x0 = 0, y0 = 0, x1 = 1920, y1 = 1008 }
local BAR = 32
local G = S.GAP

---------------------------------------------------------------- names
do
    for _, n in ipairs({ "left", "right", "top", "bottom", "top-left", "top-right", "bottom-left",
                         "bottom-right", "left-third", "center-third", "right-third",
                         "left-two-thirds", "right-two-thirds", "center", "maximize", "restore" }) do
        check("valid " .. n, S.valid(n))
    end
    check("invalid name", not S.valid("left; os.exit()"))
    eq("names listed", #S.NAMES, 16)
end

---------------------------------------------------------------- geometry
do
    local l = S.zone_rect("left", A, BAR)
    local r = S.zone_rect("right", A, BAR)
    eq("left x", l.x, G)
    eq("left title bar at the top gap", l.y - BAR, G)
    eq("left bottom above the bar", l.y + l.h, 1008 - G)
    eq("right edge", r.x + r.w, 1920 - G)
    eq("halves: one gap between them", r.x - (l.x + l.w), G)
    eq("halves same width", l.w, r.w)

    -- thirds: 1/3 + 2/3 fill the width with one gap between
    local t1 = S.zone_rect("left-third", A, BAR)
    local t2 = S.zone_rect("right-two-thirds", A, BAR)
    eq("1/3 + 2/3 gap", t2.x - (t1.x + t1.w), G)
    eq("2/3 right edge", t2.x + t2.w, 1920 - G)
    check("2/3 is about twice 1/3", math.abs(t2.w - 2 * t1.w) <= 2 * G, t1.w .. " / " .. t2.w)
    local c3 = S.zone_rect("center-third", A, BAR)
    local r3 = S.zone_rect("right-third", A, BAR)
    eq("three columns: gap 1", c3.x - (t1.x + t1.w), G)
    eq("three columns: gap 2", r3.x - (c3.x + c3.w), G)

    -- quarters: the lower row starts below the upper one, title bar included
    local tl = S.zone_rect("top-left", A, BAR)
    local bl = S.zone_rect("bottom-left", A, BAR)
    local br = S.zone_rect("bottom-right", A, BAR)
    eq("quarters: vertical gap (title bar above the lower one)", (bl.y - BAR) - (tl.y + tl.h), G)
    eq("bottom-right corner", br.x + br.w, 1920 - G)
    eq("bottom-right bottom", br.y + br.h, 1008 - G)

    -- every zone inside the usable area, title bar included, at integer pixels
    for name in pairs(S.ZONES) do
        local z = S.zone_rect(name, A, BAR)
        check("inside " .. name, z.x >= A.x0 and z.y - BAR >= A.y0 and z.x + z.w <= A.x1
              and z.y + z.h <= A.y1 and z.w > 0 and z.h > 0, rect_s(z))
        check("integers " .. name, math.type(z.x) == "integer" and math.type(z.w) == "integer"
              and math.type(z.y) == "integer" and math.type(z.h) == "integer", rect_s(z))
    end

    -- without title bars the zone starts right at the gap
    eq("no title bars: y", S.zone_rect("left", A, 0).y, G)

    -- second monitor on the right, top bar, scale 1.5 (logical 1280x720 minus 48)
    local A2 = { id = 2, x0 = 1920, y0 = 48, x1 = 3200, y1 = 720 }
    local r2 = S.zone_rect("right", A2, BAR)
    eq("monitor 2 right edge", r2.x + r2.w, 3200 - G)
    eq("monitor 2 under the top bar", r2.y - BAR, 48 + G)

    -- centered keeps the size, shrinks only when it does not fit
    local c = S.center_rect({ w = 800, h = 600 }, A, BAR)
    eq("center keeps width", c.w, 800)
    eq("center x", c.x, 560)
    eq("center y", c.y, BAR + (1008 - BAR - 600) // 2)
    local big = S.center_rect({ w = 3000, h = 2000 }, A, BAR)
    check("center shrinks a huge window", big.w == 1920 - 2 * G and big.h == 1008 - BAR - 2 * G, rect_s(big))
    local fresh = S.center_rect({ w = 0, h = 0 }, A, BAR, true)
    check("center of a tiled window gets a size", fresh.w > 800 and fresh.h > 500, rect_s(fresh))
end

---------------------------------------------------------------- the snapper
local wins, log, timers = {}, {}, {}
local active
local function add(t)
    local w = { address = t.address, x = t.x, y = t.y, w = t.w, h = t.h, mapped = true,
                floating = t.floating ~= false, fullscreen = t.fullscreen or 0,
                has_workspace = true, special = t.special or false, monitor = 1,
                min_w = t.min_w, min_h = t.min_h }
    wins[t.address] = w
    return w
end
local function snap_of(w)
    local s = {}
    for k, v in pairs(w) do s[k] = v end
    s.ref = w
    return s
end
local adapter = {
    window = function(addr)
        local w = wins[addr or active]
        return w and snap_of(w) or nil
    end,
    area = function() return A end,
    resize = function(s, W, H)
        local w = s.ref
        w.w, w.h = math.max(W, w.min_w or 0), math.max(H, w.min_h or 0)
        log[#log + 1] = "resize " .. s.address
        return w.w, w.h
    end,
    move = function(s, X, Y)
        s.ref.x, s.ref.y = X, Y
        log[#log + 1] = "move " .. s.address
        return X, Y
    end,
    fullscreen = function(s, mode, action)
        log[#log + 1] = "fullscreen " .. mode .. " " .. action
        if action == "unset" then s.ref.fullscreen = 0
        else s.ref.fullscreen = (mode == "maximized") and 1 or 2 end
    end,
    float = function(s, on)
        log[#log + 1] = "float " .. tostring(on)
        s.ref.floating = on
        if on then s.ref.x, s.ref.y, s.ref.w, s.ref.h = 100, 100, 640, 480 end
    end,
    move_dir = function(s, dir) log[#log + 1] = "move_dir " .. dir end,
    later = function(_ms, fn) timers[#timers + 1] = fn end,
    guarded = {},
}
adapter.guard = function(addr) adapter.guarded[#adapter.guarded + 1] = addr end
local function run_timers()
    for _ = 1, 5 do
        local list = timers
        timers = {}
        if #list == 0 then return end
        for _, fn in ipairs(list) do fn() end
    end
end

local snapper = S.new(adapter, BAR)

do
    local w = add { address = "0xa", x = 300, y = 200, w = 900, h = 600 }
    active = "0xa"
    check("snap left", snapper.snap("left"))
    local want = S.zone_rect("left", A, BAR)
    check("left half applied", w.x == want.x and w.y == want.y and w.w == want.w and w.h == want.h,
          rect_s(w))
    run_timers()
    eq("guard checked the snapped window", adapter.guarded[1], "0xa")

    check("snap right", snapper.snap("right"))
    want = S.zone_rect("right", A, BAR)
    eq("right half applied", w.x, want.x)
    check("restore", snapper.snap("restore"))
    check("restore: back to the place before the FIRST snap",
          w.x == 300 and w.y == 200 and w.w == 900 and w.h == 600, rect_s(w))
    check("restore twice does nothing", not snapper.snap("restore"))

    -- snapped, then moved by hand: restore leaves it where the user put it
    snapper.snap("left")
    run_timers()
    w.x, w.y = 700, 300
    check("moved by hand: restore declines", not snapper.snap("restore"))
    eq("moved by hand: stays", w.x, 700)

    -- snapped, moved by hand, snapped again: restore goes to the hand-made place
    snapper.snap("left"); run_timers()
    w.x, w.y = 640, 260
    snapper.snap("right"); run_timers()
    snapper.snap("restore")
    check("restore after a hand move: the newer place", w.x == 640 and w.y == 260, rect_s(w))
end

do
    -- maximize / restore
    log = {}
    local w = add { address = "0xb", x = 100, y = 100, w = 600, h = 400 }
    active = "0xb"
    snapper.snap("maximize")
    eq("maximize dispatched", log[1], "fullscreen maximized set")
    eq("maximized", w.fullscreen, 1)
    log = {}
    snapper.snap("maximize")
    eq("maximize twice: nothing", #log, 0)
    snapper.snap("restore")
    eq("restore unmaximizes", log[1], "fullscreen maximized unset")
    -- a maximized window snapped to a half leaves maximized first
    snapper.snap("maximize")
    log = {}
    snapper.snap("left")
    eq("snap from maximized: unset first", log[1], "fullscreen maximized unset")
    run_timers()
    eq("snap from maximized: then placed", w.x, S.zone_rect("left", A, BAR).x)
    -- full screen (2) leaves full screen, not maximized
    w.fullscreen = 2
    log = {}
    snapper.snap("restore")
    eq("restore from full screen", log[1], "fullscreen fullscreen unset")
end

do
    -- tiled windows: the halves move in the layout, precise zones float it
    log = {}
    local w = add { address = "0xc", x = 0, y = 0, w = 960, h = 1000, floating = false }
    active = "0xc"
    snapper.snap("left")
    eq("tiled + left: layout move", log[1], "move_dir l")
    eq("tiled + left: stays tiled", w.floating, false)
    log = {}
    snapper.snap("top-right")
    eq("tiled + quarter: floats", log[1], "float true")
    run_timers()
    local want = S.zone_rect("top-right", A, BAR)
    check("tiled + quarter: placed", w.x == want.x and w.y == want.y, rect_s(w))
    log = {}
    snapper.snap("restore")
    eq("restore: back into the tiled layout", log[1], "float false")
end

do
    -- a program that refuses a smaller size: the guard is asked to check it,
    -- and restore still works from where it ended up
    local w = add { address = "0xd", x = 50, y = 80, w = 1200, h = 700, min_w = 1100, min_h = 650 }
    active = "0xd"
    snapper.snap("left-third")
    eq("minimum size kept", w.w, 1100)
    run_timers()
    check("restore after a refused size", snapper.snap("restore"))
    check("restored", w.x == 50 and w.y == 80, rect_s(w))
end

do
    -- minimized (special workspace) and missing windows are left alone
    add { address = "0xe", x = 0, y = 0, w = 300, h = 200, special = true }
    check("minimized: no snap", not snapper.snap("left", "0xe"))
    check("missing window: no snap", not snapper.snap("left", "0xnothing"))
    check("unknown zone: no snap", not snapper.snap("diagonal", "0xa"))
    -- closed windows are forgotten
    snapper.snap("left", "0xa")
    check("remembered before closing", snapper.saved["0xa"] ~= nil)
    wins["0xa"] = nil
    snapper.snap("left", "0xd")
    check("closed window forgotten", snapper.saved["0xa"] == nil)
end

print(string.format("window snap: %d passed, %d failed", passed, failed))
os.exit(failed == 0 and 0 or 1)
