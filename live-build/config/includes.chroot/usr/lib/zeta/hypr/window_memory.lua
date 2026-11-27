-- SPDX-License-Identifier: GPL-3.0-or-later
-- ZETA RAYS: window memory. A program's main window opens again with the
-- size and position it had when it was last closed, as on macOS.
--
-- Plain Lua with no hl.* call (like window_guard.lua), unit-tested outside
-- Hyprland in tools/tests/test-window-memory.lua; hyprland.lua connects it
-- to the window.open / window.close events.
--
-- One line per program (window class) in ~/.local/state/zeta/window-places:
--   class <TAB> w <TAB> h <TAB> x <TAB> y <TAB> monitor name
-- x and y are relative to the monitor's usable area, so a place stays right
-- when the bar moves or another monitor is added on the left. A place is
-- used again only on a monitor with the same name; elsewhere only the size
-- is used (centered), and the window guard keeps everything reachable.

local M = {}

M.MIN_W, M.MIN_H = 320, 220     -- smaller windows are dialogs: never remembered
M.MAX_ENTRIES = 200

local function trim_class(c)
    if type(c) ~= "string" or c == "" or c:find("[\t\n]") then return nil end
    return c
end

-- Reads the places file: { class = { w, h, x, y, monitor } }.
function M.parse(text)
    local out, n = {}, 0
    for line in (text or ""):gmatch("[^\n]+") do
        local c, w, h, x, y, mon = line:match("^([^\t]+)\t(%-?%d+)\t(%-?%d+)\t(%-?%d+)\t(%-?%d+)\t([^\t]*)$")
        if c and n < M.MAX_ENTRIES then
            out[c] = { w = tonumber(w), h = tonumber(h), x = tonumber(x), y = tonumber(y), monitor = mon }
            n = n + 1
        end
    end
    return out
end

function M.serialize(places)
    local keys = {}
    for c in pairs(places) do keys[#keys + 1] = c end
    table.sort(keys)
    local lines = {}
    for i, c in ipairs(keys) do
        if i > M.MAX_ENTRIES then break end
        local p = places[c]
        lines[#lines + 1] = string.format("%s\t%d\t%d\t%d\t%d\t%s", c,
            math.floor(p.w), math.floor(p.h), math.floor(p.x), math.floor(p.y), p.monitor or "")
    end
    return table.concat(lines, "\n") .. (#lines > 0 and "\n" or "")
end

-- What to remember of a window that closes (nil: nothing). s is a window
-- snapshot (window_guard.lua), area the usable area of its monitor
-- { x0, y0, x1, y1, name }.
function M.record(s, area)
    local class = trim_class(s.class)
    if not class or not s.floating or (s.fullscreen or 0) ~= 0 or s.special then return nil end
    if s.w < M.MIN_W or s.h < M.MIN_H or not area then return nil end
    return class, { w = s.w, h = s.h, x = s.x - area.x0, y = s.y - area.y0, monitor = area.name or "" }
end

-- Where a window that opens should go: { w, h, x, y } in layout
-- coordinates, or nil to leave it as it is. bar is the title bar height
-- (drawn above the window).
function M.place(s, saved, area, bar)
    if not saved or not area then return nil end
    bar = bar or 0
    local aw, ah = area.x1 - area.x0, area.y1 - area.y0
    local w = math.max(M.MIN_W, math.min(saved.w, aw))
    local h = math.max(M.MIN_H, math.min(saved.h, ah - bar))
    local x, y
    if saved.monitor ~= "" and saved.monitor == area.name then
        x, y = area.x0 + saved.x, area.y0 + saved.y
    else
        x, y = area.x0 + (aw - w) // 2, area.y0 + (ah - h) // 2
    end
    -- inside the usable area, title bar included
    x = math.max(area.x0, math.min(x, area.x1 - w))
    y = math.max(area.y0 + bar, math.min(y, area.y1 - h))
    if math.abs(w - s.w) < 2 and math.abs(h - s.h) < 2 and math.abs(x - s.x) < 2 and math.abs(y - s.y) < 2 then
        return nil
    end
    return { w = w, h = h, x = x, y = y }
end

-- A small store around a file: io is injected for the tests.
function M.store(path, io_)
    io_ = io_ or io
    local st = { path = path, places = {}, dirty = false }
    local f = io_.open(path, "r")
    if f then
        st.places = M.parse(f:read("*a"))
        f:close()
    end
    function st.get(class) return st.places[class] end
    function st.put(class, p)
        local old = st.places[class]
        if old and old.w == p.w and old.h == p.h and old.x == p.x and old.y == p.y
                and old.monitor == p.monitor then
            return
        end
        st.places[class] = p
        st.dirty = true
    end
    function st.forget_all()
        st.places = {}
        st.dirty = true
    end
    function st.save()
        if not st.dirty then return true end
        local tmp = st.path .. ".tmp"
        local out = io_.open(tmp, "w")
        if not out then return false end
        out:write(M.serialize(st.places))
        out:close()
        local ok = os.rename(tmp, st.path)
        if ok then st.dirty = false end
        return ok and true or false
    end
    return st
end

return M
