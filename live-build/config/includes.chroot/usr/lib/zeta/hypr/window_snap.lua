-- SPDX-License-Identifier: GPL-3.0-or-later
-- ZETA RAYS: snap layouts, the part that decides.
--
-- Halves, thirds, quarters, centered, maximize and restore, like the snap
-- layouts of Windows 11 and the tiling of macOS Sequoia. hyprland.lua loads
-- this file and connects it to Hyprland through a small adapter (the same
-- pattern as window_guard.lua): everything here is plain Lua with no hl.*
-- call, so it is unit-tested outside Hyprland
-- (tools/tests/test-window-snap.lua).
--
-- Coordinates are Hyprland's logical layout coordinates. A window is a
-- snapshot { address, x, y, w, h, floating, fullscreen, special,
-- has_workspace, mapped }; an area is the usable part of a monitor (monitor
-- minus the ZETA RAYS bar) { x0, y0, x1, y1 }, the very same one the window
-- guard keeps every window inside. The title bar (hyprbars, "bar" pixels
-- high) is drawn ABOVE the window position: a zone holds title bar + window.

local M = {}

M.GAP    = 8      -- space between a snapped window and the screen edge or its neighbour
M.SETTLE = 60     -- ms to wait after leaving maximized / floating a window
M.CHECK  = 150    -- ms after a snap: the window guard checks the result

-- zone name -> { left, top, width, height } as fractions of the usable area
M.ZONES = {
    ["left"]             = { 0,   0,   1/2, 1   },
    ["right"]            = { 1/2, 0,   1/2, 1   },
    ["top"]              = { 0,   0,   1,   1/2 },
    ["bottom"]           = { 0,   1/2, 1,   1/2 },
    ["top-left"]         = { 0,   0,   1/2, 1/2 },
    ["top-right"]        = { 1/2, 0,   1/2, 1/2 },
    ["bottom-left"]      = { 0,   1/2, 1/2, 1/2 },
    ["bottom-right"]     = { 1/2, 1/2, 1/2, 1/2 },
    ["left-third"]       = { 0,   0,   1/3, 1   },
    ["center-third"]     = { 1/3, 0,   1/3, 1   },
    ["right-third"]      = { 2/3, 0,   1/3, 1   },
    ["left-two-thirds"]  = { 0,   0,   2/3, 1   },
    ["right-two-thirds"] = { 1/3, 0,   2/3, 1   },
}

-- every name accepted by zeta_snap() and "zeta-snap NAME"
M.NAMES = { "center", "maximize", "restore" }
for name in pairs(M.ZONES) do M.NAMES[#M.NAMES + 1] = name end
table.sort(M.NAMES)

function M.valid(name)
    if M.ZONES[name] then return true end
    return name == "center" or name == "maximize" or name == "restore"
end

-- A tiled window (Super + V) is not given a free position by the keyboard
-- halves: in the dwindle layout it moves to the next place in that
-- direction, which is what the arrows mean in a tiled layout.
M.DIRECTIONS = { left = "l", right = "r", top = "u", bottom = "d" }

local function round(v)
    return math.floor(v + 0.5)
end

-- Rectangle of the window (position below its title bar, and size) that
-- fills the zone, with the gaps. Gaps are full at the screen edges and
-- half on the inner sides, so two neighbouring zones are GAP apart.
function M.zone_rect(name, a, bar)
    local z = M.ZONES[name]
    if not z or not a then return nil end
    bar = bar or 0
    local aw, ah = a.x1 - a.x0, a.y1 - a.y0
    local g, h = M.GAP, M.GAP / 2
    local function span(lo, hi, origin, len)
        local p0 = origin + lo * len + (lo < 0.001 and g or h)
        local p1 = origin + hi * len - (hi > 0.999 and g or h)
        return round(p0), round(p1)
    end
    local x0, x1 = span(z[1], z[1] + z[3], a.x0, aw)
    local y0, y1 = span(z[2], z[2] + z[4], a.y0, ah)
    return { x = x0, y = y0 + bar, w = x1 - x0, h = y1 - y0 - bar }
end

-- Centered: the window keeps its size (shrunk only when it does not fit),
-- as "Center" on macOS. A window that was tiled has no size of its own
-- yet: it gets a comfortable one.
function M.center_rect(w, a, bar, fresh)
    if not a then return nil end
    bar = bar or 0
    local aw, ah = a.x1 - a.x0, a.y1 - a.y0
    local W, H = w.w, w.h
    if fresh then W, H = round(aw * 0.6), round((ah - bar) * 0.7) end
    W = math.min(W, math.floor(aw - 2 * M.GAP))
    H = math.min(H, math.floor(ah - bar - 2 * M.GAP))
    return { x = a.x0 + round((aw - W) / 2), y = a.y0 + bar + round((ah - bar - H) / 2), w = W, h = H }
end

-- Full screen state: 0 none, 1 maximized, 2 full screen, 3 both.
local function fs_mode(fs)
    if (fs & 2) ~= 0 then return "fullscreen" end
    return "maximized"
end

local function same(w, r)
    return r ~= nil and math.abs(w.x - r.x) <= 2 and math.abs(w.y - r.y) <= 2
        and math.abs(w.w - r.w) <= 2 and math.abs(w.h - r.h) <= 2
end
M.same = same

-------------------------------------------------------------------------
-- The snapper: remembers where a window was before its first snap, so
-- "restore" (Super + Shift + Down) puts it back.
--
-- adapter = {
--   window(addr)            snapshot with .ref (nil addr: the active window), or nil
--   area(snap)              usable area of the window's monitor, or nil
--   resize(snap, W, H)      ask Hyprland for that size, return the new w, h
--   move(snap, X, Y)        ask Hyprland for that position, return the new x, y
--   fullscreen(snap, mode, action)   mode "maximized"/"fullscreen", action "set"/"unset"
--   float(snap, on)         make the window floating (true) or tiled (false)
--   move_dir(snap, dir)     move a tiled window in the layout ("l", "r", "u", "d")
--   later(ms, fn)           run fn after ms milliseconds
--   guard(addr)             window guard, strict check of that window (may be nil)
--   allow_size(snap, W, H)  lift the window's maximum size to W x H (may be nil)
-- }
-------------------------------------------------------------------------

function M.new(adapter, bar)
    local s = {
        ad = adapter, bar = bar or 0,
        saved = {},    -- address -> geometry before the first snap ({ tiled = true } if it was tiled)
        placed = {},   -- address -> geometry the last snap gave it
    }

    local function geometry(w)
        return { x = w.x, y = w.y, w = w.w, h = w.h }
    end

    -- still exactly where the last snap put it (not moved by hand since)
    function s.is_snapped(w)
        return same(w, s.placed[w.address])
    end

    local function prune()
        for addr in pairs(s.saved) do
            if not s.ad.window(addr) then s.saved[addr], s.placed[addr] = nil, nil end
        end
    end

    -- Hyprland computes moves and resizes from the window's current size,
    -- which an X11 program may have changed by itself: repeat until the
    -- result is the one asked for (same as the window guard).
    local function place(w, r)
        if r.w ~= w.w or r.h ~= w.h then
            -- the general "never larger than 92% x 84% of the screen" rule
            -- (hyprland.lua) must not cut a half or a third short
            if s.ad.allow_size then s.ad.allow_size(w, r.w, r.h) end
            for _ = 1, 3 do
                local rw, rh = s.ad.resize(w, r.w, r.h)
                if rw == r.w and rh == r.h then break end
            end
        end
        for _ = 1, 3 do
            local rx, ry = s.ad.move(w, r.x, r.y)
            if rx == r.x and ry == r.y then break end
        end
    end

    -- after a snap: a program that refused the size (its minimum is
    -- larger) is put back inside the screen by the guard; what it ends up
    -- with counts as "snapped", so restore still works
    local function settle(addr)
        s.ad.later(M.CHECK, function()
            if s.ad.guard then s.ad.guard(addr) end
            local w = s.ad.window(addr)
            if w and s.placed[addr] then s.placed[addr] = geometry(w) end
        end)
    end

    local function to_zone(w, name, was_tiled)
        local a = s.ad.area(w)
        if not a then return false end
        local r
        if name == "center" then
            r = M.center_rect(w, a, s.bar, was_tiled)
        else
            r = M.zone_rect(name, a, s.bar)
        end
        if not r then return false end
        if was_tiled then
            s.saved[w.address] = { tiled = true }
        elseif not s.saved[w.address] or not s.is_snapped(w) then
            -- the first snap, or the window was moved by hand since the last
            -- one: this is the place restore goes back to
            s.saved[w.address] = geometry(w)
        end
        place(w, r)
        s.placed[w.address] = r
        settle(w.address)
        return true
    end

    -- name: a zone, "center", "maximize" or "restore"; addr: a window
    -- address (nil: the active window). Returns true when something was done.
    function s.snap(name, addr)
        if not M.valid(name) then return false end
        local w = s.ad.window(addr)
        if not w or not w.mapped or not w.has_workspace or w.special then return false end
        local fs = math.floor(w.fullscreen or 0)
        prune()

        if name == "maximize" then
            if fs ~= 0 then return true end            -- already filling the screen
            s.ad.fullscreen(w, "maximized", "set")
            return true
        end

        if name == "restore" then
            if fs ~= 0 then
                s.ad.fullscreen(w, fs_mode(fs), "unset")
                return true
            end
            local old = s.saved[w.address]
            if not old then return false end
            local was_snapped = s.is_snapped(w)
            s.saved[w.address], s.placed[w.address] = nil, nil
            if old.tiled then
                -- it left the tiled layout for the snap: it goes back there
                if w.floating then s.ad.float(w, false) end
                return true
            end
            -- moved or resized by hand after the snap: that is where it stays
            if not w.floating or not was_snapped then return false end
            place(w, old)
            settle(w.address)
            return true
        end

        local address = w.address
        local function go()
            local cur = s.ad.window(address)
            if not cur then return end
            if not cur.floating then
                local dir = M.DIRECTIONS[name]
                if dir then
                    s.ad.move_dir(cur, dir)
                    return
                end
                -- a precise zone (thirds, quarters, centered) needs a free
                -- window: it leaves the tiled layout first
                s.ad.float(cur, true)
                s.ad.later(M.SETTLE, function()
                    local f = s.ad.window(address)
                    if f and f.floating then to_zone(f, name, true) end
                end)
                return
            end
            to_zone(cur, name, false)
        end
        if fs ~= 0 then
            -- maximized or full screen: back to a normal window first
            s.ad.fullscreen(w, fs_mode(fs), "unset")
            s.ad.later(M.SETTLE, go)
        else
            go()
        end
        return true
    end

    return s
end

return M
