-- SPDX-License-Identifier: GPL-3.0-or-later
-- ZETA RAYS: the window guard, the part that decides.
--
-- No window may end up where the user can no longer close, minimize, move
-- or reach it. hyprland.lua loads this file and connects it to Hyprland
-- (timers, events, dispatchers) through a small adapter; everything here is
-- plain Lua with no hl.* call, so the very same code is unit-tested outside
-- Hyprland (tools/tests/test-window-guard.lua).
--
-- Coordinates are Hyprland's logical layout coordinates. A window is
-- described by a plain table (a "snapshot"):
--   { address, x, y, w, h, mapped, floating, fullscreen, xwayland, title,
--     has_workspace, special, monitor (id or nil) }
-- An area is the usable part of one monitor (monitor minus the bar):
--   { id, x0, y0, x1, y1, focused }
-- The title bar (hyprbars, "bar" pixels high) is drawn ABOVE the window
-- position, with the buttons (close, minimize, maximize) on the left.

local M = {}

M.MARGIN    = 8      -- space left around a window that was shrunk
M.VISIBLE   = 160    -- gentle pass: this much of the window stays on screen
M.BUTTONS   = 96     -- width of the title bar strip holding the buttons
M.GRIP      = 24     -- without title bars: top strip of the window kept visible
M.BOTTOM    = 48     -- gentle pass: this much of the window stays above the bottom
M.MAX_FIXES = 4      -- corrections in a row before backing off
M.MAX_DEFER = 4      -- passes a correction waits while the pointer holds the window
M.BACKOFF   = 20     -- at most one correction every BACKOFF passes after that
M.TOLERANCE = 2      -- pixels a window may stick out without being moved
M.MIN_W     = 200    -- untitled X11 windows smaller than this are menus and
M.MIN_H     = 120    -- tooltips: they place themselves and are never touched

local function clamp(v, lo, hi)
    -- when the range is empty (window larger than the area) the low end
    -- wins: that is where the title bar and its buttons are
    if v > hi then v = hi end
    if v < lo then v = lo end
    return v
end
M.clamp = clamp

-- Logical size of a monitor (pixels / scale, rotated when needed).
function M.logical_size(m)
    local sc = (m.scale and m.scale > 0) and m.scale or 1
    local w, h = m.width / sc, m.height / sc
    if (m.transform or 0) % 2 == 1 then w, h = h, w end
    return w, h
end

-- Usable area of a monitor: the monitor minus the ZETA RAYS bar (Waybar).
-- Hyprland does not expose the reserved area to Lua: it is derived from
-- the bar's layer surface. "layers" is a list of
-- { namespace, x, y, w, h, mapped }.
function M.usable_area(m, layers)
    local mw, mh = M.logical_size(m)
    -- a monitor being set up (no mode yet) is not a place for windows:
    -- shrinking windows to it would make them tiny
    if mw < 320 or mh < 240 then return nil end
    local a = { id = m.id, focused = m.focused,
                x0 = m.x, y0 = m.y, x1 = m.x + mw, y1 = m.y + mh }
    for _, l in ipairs(layers or {}) do
        if l.mapped ~= false and l.namespace == "waybar" and l.w >= mw * 0.5 and l.h < mh * 0.3 then
            if l.y + l.h >= a.y1 - 40 then
                a.y1 = math.min(a.y1, l.y)                   -- bar at the bottom
            elseif l.y <= a.y0 + 40 then
                a.y0 = math.max(a.y0, l.y + l.h)             -- bar at the top
            end
        end
    end
    -- a bar in an odd place must never leave a uselessly small area
    if a.y1 - a.y0 < mh * 0.5 then a.y0, a.y1 = m.y, m.y + mh end
    return a
end

local function overlap(r, a)
    local w = math.min(r.x1, a.x1) - math.max(r.x0, a.x0)
    local h = math.min(r.y1, a.y1) - math.max(r.y0, a.y0)
    if w <= 0 or h <= 0 then return 0 end
    return w * h
end
M.overlap = overlap

local function inside(r, a)
    return r.x0 >= a.x0 and r.y0 >= a.y0 and r.x1 <= a.x1 and r.y1 <= a.y1
end

-- Rectangle of the window as drawn, title bar included.
function M.outer(w, bar)
    return { x0 = w.x, y0 = w.y - bar, x1 = w.x + w.w, y1 = w.y + w.h }
end

-- What must stay reachable: the left part of the title bar, with the
-- buttons and a little room to grab it. Without title bars (plugin not
-- loaded) the top-left corner of the window, where Super + drag grabs it.
function M.handle(w, bar)
    local wid = math.min(w.w, M.BUTTONS)
    if bar > 0 then
        return { x0 = w.x, y0 = w.y - bar, x1 = w.x + wid, y1 = w.y }
    end
    return { x0 = w.x, y0 = w.y, x1 = w.x + wid, y1 = w.y + math.min(w.h, M.GRIP) }
end

-- True when the handle lies entirely inside the usable area of one
-- monitor (with several monitors a window may straddle them).
function M.reachable(w, areas, bar)
    local hd = M.handle(w, bar)
    for _, a in ipairs(areas) do
        if inside(hd, a) then return true end
    end
    return false
end

-- How many usable areas the window touches.
function M.areas_touched(w, areas, bar)
    local r, n = M.outer(w, bar), 0
    for _, a in ipairs(areas) do
        if overlap(r, a) > 0 then n = n + 1 end
    end
    return n
end

-- Which windows the guard looks after:
--   "window"   a floating window on a normal workspace
--   "untitled" an untitled X11 window large enough to be a real window
--              (only moved, never resized, and only when entirely off screen)
--   nil        everything else: minimized windows (special workspace),
--              full screen and maximized ones (Hyprland lays them out),
--              tiled ones, X11 menus and tooltips.
function M.kind(w)
    if not w.mapped or not w.has_workspace or w.special then return nil end
    if (w.fullscreen or 0) ~= 0 or not w.floating then return nil end
    if w.xwayland and (w.title or "") == "" then
        if w.w >= M.MIN_W and w.h >= M.MIN_H then return "untitled" end
        return nil
    end
    return "window"
end

-- The area a window belongs to: its monitor's; when Hyprland no longer
-- knows the monitor (unplugged, disabled) the one it overlaps most; when it
-- overlaps none, the focused one (or the first).
function M.area_for(w, areas, bar)
    if w.monitor ~= nil then
        for _, a in ipairs(areas) do
            if a.id == w.monitor then return a end
        end
    end
    local r, best, best_n = M.outer(w, bar or 0), nil, 0
    for _, a in ipairs(areas) do
        local n = overlap(r, a)
        if n > best_n then best, best_n = a, n end
    end
    if best then return best end
    for _, a in ipairs(areas) do
        if a.focused then return a end
    end
    return areas[1]
end

-- Where the window should be: nil when it is fine as it is, otherwise
-- { x, y, w, h }.
-- opts.mode:
--   "strict"  entirely inside the area (window just opened, display
--             change, manual recovery)
--   "gentle"  the handle (title bar buttons) must be reachable
-- opts.bar      title bar height (0 without hyprbars)
-- opts.minimum  { w, h } the program refused to get smaller than this
-- opts.untitled never resize, only bring back a window entirely off screen
-- opts.areas    all usable areas (a window may straddle two monitors)
function M.correction(w, a, opts)
    local bar = opts.bar or 0
    local areas = opts.areas or { a }
    local strict = opts.mode == "strict"
    local aw, ah = a.x1 - a.x0, a.y1 - a.y0
    local x, y, W, H = w.x, w.y, w.w, w.h
    local ymin = a.y0 + bar

    if opts.untitled then
        local r = M.outer(w, bar)
        for _, b in ipairs(areas) do
            if overlap(r, b) > 0 then return nil end
        end
        local nx = math.floor(clamp(x, a.x0, a.x1 - W))
        local ny = math.floor(clamp(y, ymin, a.y1 - H))
        return { x = nx, y = ny, w = W, h = H }
    end

    -- Too large for its screen: shrink it to the usable area. Not in the
    -- gentle pass when it deliberately spans several monitors, and never
    -- below the size the program refused to go under.
    local nW, nH = W, H
    local spans = (not strict) and M.areas_touched(w, areas, bar) > 1
    if not spans then
        if W > aw then nW = math.floor(aw - 2 * M.MARGIN) end
        if H + bar > ah then nH = math.floor(ah - bar - 2 * M.MARGIN) end
    end
    local mn = opts.minimum
    if mn then
        nW = math.max(nW, math.min(W, mn.w))
        nH = math.max(nH, math.min(H, mn.h))
    end
    -- larger than the area even at its minimum: it can be "scrolled" by
    -- dragging it (Super + drag) to reach its far side; the keyboard keeps
    -- close/minimize reachable and Super+Shift+W puts it back
    local pan_x = mn ~= nil and nW > aw
    local pan_y = mn ~= nil and nH + bar > ah

    local nx, ny
    if nW ~= W or nH ~= H then
        -- shrunk: centered; if still larger, title bar and buttons first
        nx = pan_x and a.x0 or a.x0 + (aw - nW) / 2
        ny = pan_y and ymin or ymin + (a.y1 - ymin - nH) / 2
    elseif strict then
        nx = clamp(x, a.x0, a.x1 - nW)
        ny = clamp(y, ymin, a.y1 - nH)
    else
        if not pan_x and not pan_y and M.reachable(w, areas, bar) then return nil end
        if pan_x then
            nx = clamp(x, a.x1 - nW, a.x0)
        else
            nx = clamp(x, a.x0, a.x1 - math.min(nW, M.VISIBLE))
        end
        if pan_y then
            ny = clamp(y, a.y1 - nH, ymin)
        else
            ny = clamp(y, ymin, a.y1 - math.min(nH, M.BOTTOM))
        end
    end
    nx, ny = math.floor(nx), math.floor(ny)
    if nx == x and ny == y and nW == W and nH == H then return nil end
    -- one or two pixels off (rounding at fractional scales): not worth a
    -- jump, the window is reachable anyway
    if nW == W and nH == H and math.abs(nx - x) <= M.TOLERANCE and math.abs(ny - y) <= M.TOLERANCE then
        return nil
    end
    return { x = nx, y = ny, w = nW, h = nH }
end

-------------------------------------------------------------------------
-- The guard: state across passes, and the loop protections.
--
-- adapter = {
--   windows()            list of snapshots, each with .ref (the Hyprland object)
--   areas()              list of usable areas
--   active()             address of the focused window, or nil
--   cursor()             { x, y } or nil
--   resize(snap, W, H)   ask Hyprland for that size, return the new w, h
--   move(snap, X, Y)     ask Hyprland for that position, return the new x, y
--   unfullscreen(snap)   leave full screen
--   later(ms, fn)        run fn after ms milliseconds
-- }
-------------------------------------------------------------------------

function M.new(adapter, bar)
    local g = {
        ad = adapter, bar = bar or 0,
        last = {},        -- address -> geometry seen at the previous pass
        counts = {},      -- address -> corrections in a row
        skipped = {},     -- address -> passes skipped while backing off
        deferred = {},    -- address -> passes waited while the pointer held it
        requested = {},   -- address -> size requested at the last correction
        minimum = {},     -- address -> size the program refused to go below
    }

    local function sig(w)
        return string.format("%d,%d,%d,%d", w.x, w.y, w.w, w.h)
    end

    local function forget(addr)
        g.last[addr], g.counts[addr], g.skipped[addr] = nil, nil, nil
        g.deferred[addr], g.requested[addr], g.minimum[addr] = nil, nil, nil
    end

    -- The pointer is on the active window: the user may be dragging it
    -- right now (Hyprland does not tell Lua). Wait a few passes.
    local function held(w)
        if g.ad.active() ~= w.address then return false end
        local c = g.ad.cursor()
        if not c then return false end
        return c.x >= w.x - 4 and c.x <= w.x + w.w + 4
           and c.y >= w.y - g.bar - 4 and c.y <= w.y + w.h + 4
    end

    -- mode: "strict", "gentle" (periodic pass), "now" (gentle rules, at once)
    function g.fix(w, mode, areas)
        local k = M.kind(w)
        if not k then return false end
        areas = areas or g.ad.areas()
        if #areas == 0 then return false end
        local addr = w.address
        local a = M.area_for(w, areas, g.bar)
        -- the program kept a size larger than the one requested: that is
        -- its minimum. It is not requested again (that would loop).
        local req = g.requested[addr]
        if req and (w.w > req.w or w.h > req.h) then
            g.minimum[addr] = { w = w.w, h = w.h }
        end
        g.requested[addr] = nil
        local c = M.correction(w, a, {
            mode = (mode == "strict") and "strict" or "gentle",
            bar = g.bar, minimum = g.minimum[addr], areas = areas,
            untitled = (k == "untitled"),
        })
        if not c then
            g.counts[addr], g.skipped[addr], g.deferred[addr] = nil, nil, nil
            return false
        end
        if mode == "gentle" and held(w) then
            local d = (g.deferred[addr] or 0) + 1
            g.deferred[addr] = d
            if d <= M.MAX_DEFER then return false end
        end
        g.deferred[addr] = nil
        -- a program that keeps moving itself back out is not chased in a
        -- tight loop: after MAX_FIXES corrections in a row it is corrected
        -- only once every BACKOFF passes (the manual recovery always acts)
        local n = (g.counts[addr] or 0) + 1
        if n > M.MAX_FIXES then
            local s = (g.skipped[addr] or 0) + 1
            if s < M.BACKOFF then g.skipped[addr] = s; return false end
            g.skipped[addr] = 0
        end
        g.counts[addr] = n
        -- Hyprland computes move and resize as a delta from the window's
        -- size but applies it to the layout box: if an X11 program resized
        -- or moved itself the two do not match, and the first command lands
        -- elsewhere (even at negative sizes, clamped to the minimum). From
        -- the second one on they match: repeat until the result is right.
        if c.w ~= w.w or c.h ~= w.h then
            for _ = 1, 3 do
                local rw, rh = g.ad.resize(w, c.w, c.h)
                if rw == c.w and rh == c.h then break end
            end
            g.requested[addr] = { w = c.w, h = c.h }
        end
        for _ = 1, 3 do
            local rx, ry = g.ad.move(w, c.x, c.y)
            if rx == c.x and ry == c.y then break end
        end
        return true
    end

    -- Check every window. In the gentle pass only a window that has not
    -- moved since the previous pass is touched: a window being dragged
    -- right now is moving, and we do not fight the user.
    function g.check_all(mode)
        local areas = g.ad.areas()
        local seen = {}
        for _, w in ipairs(g.ad.windows()) do
            local addr = w.address
            seen[addr] = true
            if M.kind(w) then
                local s = sig(w)
                if mode ~= "gentle" or g.last[addr] == s then
                    g.fix(w, mode, areas)
                end
                g.last[addr] = s
            end
        end
        for addr in pairs(g.last) do
            if not seen[addr] then forget(addr) end
        end
    end

    function g.check_one(addr, mode)
        for _, w in ipairs(g.ad.windows()) do
            if w.address == addr then return g.fix(w, mode) end
        end
        return false
    end

    -- after a display change everything gets a fresh start
    function g.reset()
        g.counts, g.skipped, g.deferred = {}, {}, {}
    end

    -- Manual recovery (Super + Shift + W, "zeta-windows recover", Settings
    -- › Displays): full screen windows leave full screen (the bar and the
    -- title bar come back), then every window goes back inside its screen.
    -- Maximized windows stay maximized: Hyprland keeps them in the usable area.
    function g.recover()
        g.reset()
        local left = false
        for _, w in ipairs(g.ad.windows()) do
            if w.mapped and not w.special and ((w.fullscreen or 0) & 2) ~= 0 then
                g.ad.unfullscreen(w)
                left = true
            end
        end
        g.check_all("strict")
        if left then
            -- the windows that left full screen get their size back a moment later
            g.ad.later(400, function() g.check_all("strict") end)
        end
    end

    return g
end

return M
