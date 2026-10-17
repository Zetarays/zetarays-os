-- SPDX-License-Identifier: GPL-3.0-or-later
-- Unit tests for the ZETA RAYS window guard (usr/lib/zeta/hypr/window_guard.lua),
-- outside Hyprland: a fake adapter simulates monitors, the bar, windows and
-- misbehaving programs (X11 apps that move or resize themselves, minimum
-- sizes larger than the screen, a program that keeps moving back out).
--
--   lua5.5 tools/tests/test-window-guard.lua [path/to/window_guard.lua]
--
-- Hyprland 0.55 embeds Lua 5.5; the tests also run on 5.4.

local path = arg[1] or "live-build/config/includes.chroot/usr/lib/zeta/hypr/window_guard.lua"
local G = dofile(path)

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

-- 1920x1080 monitor with the bar at the bottom (60 px high, 12 px margin)
local MON1 = { id = 1, focused = true, x = 0, y = 0, width = 1920, height = 1080, scale = 1, transform = 0 }
local BAR1 = { { namespace = "waybar", x = 12, y = 1008, w = 1896, h = 60, mapped = true } }

---------------------------------------------------------------- areas
do
    local a = G.usable_area(MON1, BAR1)
    eq("area bottom bar y1", a.y1, 1008)
    eq("area bottom bar y0", a.y0, 0)
    local top = G.usable_area(MON1, { { namespace = "waybar", x = 12, y = 12, w = 1896, h = 60, mapped = true } })
    eq("area top bar y0", top.y0, 72)
    local hidpi = G.usable_area({ id = 2, x = 1920, y = 0, width = 3840, height = 2160, scale = 2, transform = 0 }, {})
    eq("area scale 2 width", hidpi.x1 - hidpi.x0, 1920)
    eq("area scale 2 height", hidpi.y1 - hidpi.y0, 1080)
    local rot = G.usable_area({ id = 3, x = 0, y = 0, width = 1920, height = 1080, scale = 1, transform = 1 }, {})
    eq("area rotated width", rot.x1, 1080)
    eq("area rotated height", rot.y1, 1920)
    local odd = G.usable_area(MON1, { { namespace = "waybar", x = 0, y = 300, w = 1920, h = 200, mapped = true } })
    check("area ignores a bar in the middle", odd.y0 == 0 and odd.y1 == 1080)
    local other = G.usable_area(MON1, { { namespace = "notifications", x = 0, y = 1000, w = 1920, h = 80 } })
    eq("area ignores other layers", other.y1, 1080)
    check("monitor without a mode is skipped",
          G.usable_area({ id = 9, x = 0, y = 0, width = 0, height = 0, scale = 1, transform = 0 }, {}) == nil)
end

local A1 = G.usable_area(MON1, BAR1)

local function win(t)
    local w = { address = t.address or "0x1", x = t.x, y = t.y, w = t.w, h = t.h,
                mapped = true, floating = true, fullscreen = t.fullscreen or 0,
                xwayland = t.xwayland or false, title = t.title or "test",
                has_workspace = true, special = t.special or false,
                monitor = t.monitor == nil and 1 or t.monitor }
    if t.monitor == false then w.monitor = nil end
    return w
end

---------------------------------------------------------------- kind
do
    check("kind normal", G.kind(win { x = 0, y = 0, w = 10, h = 10 }) == "window")
    check("kind minimized skipped", G.kind(win { x = 0, y = 0, w = 800, h = 600, special = true }) == nil)
    check("kind fullscreen skipped", G.kind(win { x = 0, y = 0, w = 800, h = 600, fullscreen = 2 }) == nil)
    check("kind maximized skipped", G.kind(win { x = 0, y = 0, w = 800, h = 600, fullscreen = 1 }) == nil)
    check("kind X11 menu skipped", G.kind(win { x = 0, y = 0, w = 180, h = 300, xwayland = true, title = "" }) == nil)
    check("kind X11 untitled big", G.kind(win { x = 0, y = 0, w = 640, h = 480, xwayland = true, title = "" }) == "untitled")
    local tiled = win { x = 0, y = 0, w = 800, h = 600 }
    tiled.floating = false
    check("kind tiled skipped", G.kind(tiled) == nil)
end

---------------------------------------------------------------- corrections
local function corr(w, mode, extra)
    local o = { mode = mode, bar = 32, areas = { A1 } }
    for k, v in pairs(extra or {}) do o[k] = v end
    return G.correction(w, (extra and extra.area) or A1, o)
end

do
    -- the selftest's program: moves to -400,-300 and grows to 2600x1800
    local c = corr(win { x = -400, y = -300, w = 2600, h = 1800 }, "gentle")
    check("offscreen+huge corrected", c ~= nil)
    eq("offscreen+huge w", c.w, 1904)
    eq("offscreen+huge h", c.h, 1008 - 32 - 16)
    eq("offscreen+huge x", c.x, 8)
    eq("offscreen+huge y", c.y, 32 + 8)

    c = corr(win { x = 1800, y = 900, w = 400, h = 300 }, "strict")
    check("strict inside", c and c.x == 1520 and c.y == 708 and c.w == 400 and c.h == 300)

    check("gentle: reachable stays", corr(win { x = 1700, y = 500, w = 800, h = 600 }, "gentle") == nil)
    c = corr(win { x = 1850, y = 500, w = 800, h = 600 }, "gentle")
    check("gentle: buttons off the right edge", c and c.x == 1760 and c.y == 500)
    c = corr(win { x = -300, y = 500, w = 800, h = 600 }, "gentle")
    check("gentle: buttons off the left edge", c and c.x == 0)

    c = corr(win { x = 300, y = 10, w = 800, h = 600 }, "gentle")
    check("title bar under the top edge", c and c.y == 32 and c.x == 300)
    check("title bar just above the bottom bar is fine",
          corr(win { x = 300, y = 1000, w = 800, h = 600 }, "gentle") == nil)
    c = corr(win { x = 300, y = 1020, w = 800, h = 600 }, "gentle")
    check("title bar under the bottom bar", c and c.y == 1008 - 48)
    c = corr(win { x = 300, y = 5000, w = 800, h = 600 }, "gentle")
    check("window far below", c and c.y == 960)

    -- a dialog that placed itself at 3000,2000
    c = corr(win { x = 3000, y = 2000, w = 400, h = 300 }, "strict")
    check("dialog off screen, strict", c and c.x == 1520 and c.y == 708)
    c = corr(win { x = 3000, y = 2000, w = 400, h = 300 }, "gentle")
    check("dialog off screen, gentle", c and c.x == 1760 and c.y == 960)

    -- without title bars (plugin not loaded)
    c = G.correction(win { x = 100, y = -10, w = 800, h = 600 }, A1, { mode = "gentle", bar = 0, areas = { A1 } })
    check("no title bars: top strip visible", c and c.y == 0)
    check("no title bars: y=0 is fine",
          G.correction(win { x = 100, y = 0, w = 800, h = 600 }, A1, { mode = "gentle", bar = 0, areas = { A1 } }) == nil)

    -- minimum size larger than the screen (the program refuses to shrink)
    local mn = { w = 2200, h = 1300 }
    c = corr(win { x = 300, y = 300, w = 2200, h = 1300 }, "strict", { minimum = mn })
    check("min size: buttons top left (strict)", c and c.x == 0 and c.y == 32 and c.w == 2200 and c.h == 1300)
    c = corr(win { x = 300, y = 300, w = 2200, h = 1300 }, "gentle", { minimum = mn })
    check("min size: pulled back to the pan range", c and c.x == 0 and c.y == 32)
    check("min size: scrolled up by the user is allowed",
          corr(win { x = -100, y = -200, w = 2200, h = 1300 }, "gentle", { minimum = mn }) == nil)
    c = corr(win { x = -400, y = -400, w = 2200, h = 1300 }, "gentle", { minimum = mn })
    check("min size: never past its far edge", c and c.x == 1920 - 2200 and c.y == 1008 - 1300)
    -- only too tall: horizontal rules unchanged
    c = corr(win { x = 1850, y = 32, w = 800, h = 1300 }, "gentle", { minimum = { w = 800, h = 1300 } })
    check("min size tall: buttons pulled back horizontally", c and c.x == 1760 and c.y == 32)

    -- untitled X11 windows: moved back only when entirely off screen
    c = corr(win { x = -2000, y = 100, w = 640, h = 480, xwayland = true, title = "" }, "gentle", { untitled = true })
    check("untitled off screen moved, not resized", c and c.x == 0 and c.w == 640 and c.h == 480)
    check("untitled partly visible untouched",
          corr(win { x = -300, y = 100, w = 640, h = 480, xwayland = true, title = "" }, "gentle", { untitled = true }) == nil)
end

---------------------------------------------------------------- several monitors
do
    local B = G.usable_area({ id = 2, x = 1920, y = 0, width = 3840, height = 2160, scale = 2, transform = 0 }, {})
    local areas = { A1, B }
    -- straddling two monitors with different scales: fine while reachable
    check("straddle reachable", G.correction(win { x = 1800, y = 300, w = 600, h = 400 }, A1,
          { mode = "gentle", bar = 32, areas = areas }) == nil)
    -- spanning both on purpose: not shrunk in the gentle pass
    check("span not shrunk", G.correction(win { x = 100, y = 300, w = 3000, h = 600 }, A1,
          { mode = "gentle", bar = 32, areas = areas }) == nil)
    -- strict (display change): back inside its own monitor
    local c = G.correction(win { x = 1800, y = 300, w = 600, h = 400 }, A1, { mode = "strict", bar = 32, areas = areas })
    check("straddle strict", c and c.x == 1320)
    -- monitor unplugged: Hyprland no longer knows it
    local w = win { x = 4000, y = 300, w = 600, h = 400, monitor = false }
    local a = G.area_for(w, { A1 }, 32)
    eq("unplugged: focused monitor", a.id, 1)
    w.monitor, w.x = 7, 3000
    a = G.area_for(w, areas, 32)
    eq("unknown id: overlap wins", a.id, 2)
end

---------------------------------------------------------------- the guard with a fake Hyprland
local function fake(opts)
    opts = opts or {}
    local F = { wins = {}, areas = opts.areas or { A1 }, active = nil, cursor = nil,
                moves = 0, resizes = 0, unfull = 0, timers = {} }
    function F.add(t)
        local w = win(t)
        w.min = t.min                      -- program's minimum size
        w.desync = t.desync                -- X11: first resize lands wrong
        w.fighter = t.fighter              -- moves back out after every move
        F.wins[#F.wins + 1] = w
        return w
    end
    F.adapter = {
        windows = function()
            local out = {}
            for _, w in ipairs(F.wins) do
                local s = {}
                for k, v in pairs(w) do s[k] = v end
                s.ref = w
                out[#out + 1] = s
            end
            return out
        end,
        areas = function() return F.areas end,
        active = function() return F.active end,
        cursor = function() return F.cursor end,
        resize = function(s, W, H)
            local w = s.ref
            F.resizes = F.resizes + 1
            if w.desync then
                w.desync = false
                w.w, w.h = 1, 1                 -- what Hyprland did on the first try
                return w.w, w.h
            end
            w.w, w.h = W, H
            if w.min then w.w, w.h = math.max(W, w.min.w), math.max(H, w.min.h) end
            return w.w, w.h
        end,
        move = function(s, X, Y)
            local w = s.ref
            F.moves = F.moves + 1
            w.x, w.y = X, Y
            return w.x, w.y
        end,
        unfullscreen = function(s)
            F.unfull = F.unfull + 1
            s.ref.fullscreen = 0
        end,
        later = function(ms, fn) F.timers[#F.timers + 1] = fn end,
    }
    function F.pass(g, mode)
        g.check_all(mode or "gentle")
        for _, w in ipairs(F.wins) do
            if w.fighter then w.x, w.y = -500, -500 end
        end
    end
    function F.run_timers()
        local t = F.timers
        F.timers = {}
        for _, fn in ipairs(t) do fn() end
    end
    return F
end

do
    -- gentle passes wait for a still window, then fix it once
    local F = fake()
    local w = F.add { x = -400, y = -300, w = 2600, h = 1800 }
    local g = G.new(F.adapter, 32)
    F.pass(g)
    eq("first pass only records", F.moves, 0)
    F.pass(g)
    check("second pass fixes", w.x == 8 and w.y == 40 and w.w == 1904 and w.h == 960,
          string.format("%d,%d %dx%d", w.x, w.y, w.w, w.h))
    local m = F.moves
    for _ = 1, 5 do F.pass(g) end
    eq("then left alone", F.moves, m)
end

do
    -- minimum size bigger than the screen: no endless resize loop
    local F = fake()
    local w = F.add { x = 300, y = 300, w = 2200, h = 1300, min = { w = 2200, h = 1300 } }
    local g = G.new(F.adapter, 32)
    for _ = 1, 10 do F.pass(g) end
    check("min size ends with buttons top left", w.x == 0 and w.y == 32,
          string.format("%d,%d", w.x, w.y))
    check("min size: resize asked once", F.resizes <= 3, "resizes " .. F.resizes)
    local m = F.moves
    -- the user scrolls it up to reach the bottom: allowed
    w.x, w.y = -100, -250
    for _ = 1, 5 do F.pass(g) end
    eq("min size: user scroll respected", F.moves, m)
    -- Super+Shift+W puts it back
    g.recover()
    check("min size: recover puts the title bar back", w.x == 0 and w.y == 32)
end

do
    -- X11 desync: the first resize lands at 1x1, the loop repeats
    local F = fake()
    local w = F.add { x = -400, y = -300, w = 2600, h = 1800, desync = true }
    local g = G.new(F.adapter, 32)
    F.pass(g); F.pass(g)
    check("desync: right size after the retry", w.w == 1904 and w.h == 960, w.w .. "x" .. w.h)
end

do
    -- a program that keeps moving back out: not chased in a tight loop
    local F = fake()
    F.add { x = -500, y = -500, w = 600, h = 400, fighter = true }
    local g = G.new(F.adapter, 32)
    for _ = 1, 60 do F.pass(g) end
    check("fighter: bounded corrections", F.moves >= G.MAX_FIXES and F.moves <= G.MAX_FIXES + 4,
          "moves " .. F.moves)
    local m = F.moves
    g.recover()
    check("fighter: recover still acts", F.moves > m)
end

do
    -- the user holds the window with the pointer: wait, then act anyway
    local F = fake()
    local w = F.add { address = "0xd", x = 300, y = 5, w = 800, h = 600 }
    F.active, F.cursor = "0xd", { x = 400, y = 20 }
    local g = G.new(F.adapter, 32)
    F.pass(g)                                   -- records
    for i = 1, G.MAX_DEFER do
        F.pass(g)
        eq("held: waits " .. i, F.moves, 0)
    end
    F.pass(g)
    check("held: corrected after waiting", w.y == 32)
    -- pointer elsewhere: immediate
    local F2 = fake()
    local w2 = F2.add { address = "0xe", x = 300, y = 5, w = 800, h = 600 }
    F2.active, F2.cursor = "0xe", { x = 1500, y = 900 }
    local g2 = G.new(F2.adapter, 32)
    F2.pass(g2); F2.pass(g2)
    check("not held: corrected at once", w2.y == 32)
end

do
    -- windows on a monitor that was unplugged, then a display change
    local F = fake()
    local w = F.add { x = 2500, y = 400, w = 800, h = 600, monitor = false }
    local g = G.new(F.adapter, 32)
    g.reset(); g.check_all("strict")
    check("unplugged monitor: window comes back", w.x == 1120 and w.y == 400, w.x .. "," .. w.y)
end

do
    -- scale change: 1920x1080 at scale 2 is 960x540, the bar now at y=468
    local small = G.usable_area({ id = 1, focused = true, x = 0, y = 0, width = 1920, height = 1080, scale = 2, transform = 0 },
                                { { namespace = "waybar", x = 12, y = 468, w = 936, h = 60, mapped = true } })
    local F = fake { areas = { small } }
    local w = F.add { x = 100, y = 100, w = 1200, h = 800 }
    local g = G.new(F.adapter, 32)
    g.check_all("strict")
    check("scale change: shrunk to fit", w.w == 944 and w.h == 468 - 32 - 16, w.w .. "x" .. w.h)
    check("scale change: inside", w.x == 8 and w.y >= 32 and w.y + w.h <= 468)
end

do
    -- minimized, full screen and maximized windows
    local F = fake()
    local hidden = F.add { address = "0xa", x = -5000, y = -5000, w = 800, h = 600, special = true }
    local full = F.add { address = "0xb", x = 0, y = 0, w = 1920, h = 1080, fullscreen = 2 }
    local maxi = F.add { address = "0xc", x = 12, y = 12, w = 1896, h = 984, fullscreen = 1 }
    local g = G.new(F.adapter, 32)
    for _ = 1, 3 do F.pass(g) end
    check("minimized untouched", hidden.x == -5000)
    eq("nothing moved", F.moves, 0)
    g.recover()
    eq("recover: full screen left", full.fullscreen, 0)
    eq("recover: maximized kept", maxi.fullscreen, 1)
    eq("recover: one unfullscreen", F.unfull, 1)
    check("recover: timer for the second pass", #F.timers == 1)
    F.run_timers()
end

do
    -- a window coming back from the hidden workspace at its old place
    local F = fake()
    local w = F.add { address = "0xf", x = 2500, y = 300, w = 800, h = 600 }
    local g = G.new(F.adapter, 32)
    check("check_one now", g.check_one("0xf", "now") == true)
    check("check_one now: reachable", w.x == 1760)
end

print(string.format("window guard: %d passed, %d failed", passed, failed))
os.exit(failed == 0 and 0 or 1)
