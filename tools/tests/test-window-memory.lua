-- SPDX-License-Identifier: GPL-3.0-or-later
-- Unit tests for usr/lib/zeta/hypr/window_memory.lua, outside Hyprland.
--
--   lua5.4 tools/tests/test-window-memory.lua [path/to/window_memory.lua]

local path = arg[1] or "live-build/config/includes.chroot/usr/lib/zeta/hypr/window_memory.lua"
local M = dofile(path)

local passed, failed = 0, 0
local function check(name, cond, detail)
    if cond then passed = passed + 1 else
        failed = failed + 1
        print("FAIL " .. name .. (detail and (": " .. detail) or ""))
    end
end
local function eq(name, got, want)
    check(name, got == want, "got " .. tostring(got) .. ", want " .. tostring(want))
end

local AREA = { x0 = 0, y0 = 0, x1 = 1920, y1 = 1008, name = "HDMI-A-1" }
local SMALL = { x0 = 0, y0 = 0, x1 = 1280, y1 = 728, name = "eDP-1" }
local function win(t)
    local s = { class = "thunar", floating = true, fullscreen = 0, special = false,
                x = 300, y = 200, w = 1000, h = 700 }
    for k, v in pairs(t or {}) do s[k] = v end
    return s
end

-- record
local c, p = M.record(win(), AREA)
eq("record class", c, "thunar")
eq("record w", p.w, 1000); eq("record x relative", p.x, 300); eq("record monitor", p.monitor, "HDMI-A-1")
check("dialog not recorded", M.record(win({ w = 300, h = 200 }), AREA) == nil)
check("tiled not recorded", M.record(win({ floating = false }), AREA) == nil)
check("fullscreen not recorded", M.record(win({ fullscreen = 1 }), AREA) == nil)
check("minimized not recorded", M.record(win({ special = true }), AREA) == nil)
check("no class not recorded", M.record(win({ class = "" }), AREA) == nil)
check("tab in class not recorded", M.record(win({ class = "a\tb" }), AREA) == nil)

-- serialize / parse round trip
local text = M.serialize({ thunar = p, ["org.gnome.Calculator"] = { w = 400, h = 500, x = 10, y = 20, monitor = "" } })
local back = M.parse(text)
eq("round trip w", back.thunar.w, 1000)
eq("round trip empty monitor", back["org.gnome.Calculator"].monitor, "")
eq("garbage ignored", next(M.parse("nonsense\n\t\t\n")), nil)

-- place: same monitor, exact place
local q = M.place(win({ x = 460, y = 154, w = 640, h = 480 }), p, AREA, 32)
eq("same monitor x", q.x, 300); eq("same monitor y", q.y, 200); eq("same monitor w", q.w, 1000)

-- place: another monitor, smaller: size clamped, centered, inside
q = M.place(win({ x = 0, y = 0, w = 640, h = 480 }), { w = 1800, h = 1000, x = 50, y = 40, monitor = "HDMI-A-1" }, SMALL, 32)
eq("small w clamped", q.w, 1280)
check("small h fits under the title bar", q.h + 32 <= 728, "h " .. q.h)
check("small inside x", q.x >= 0 and q.x + q.w <= 1280)
check("small title bar visible", q.y >= 32)

-- place: a place that would be off the right edge is pulled in
q = M.place(win({ w = 640, h = 480 }), { w = 800, h = 600, x = 1700, y = 900, monitor = "HDMI-A-1" }, AREA, 32)
check("off edge pulled in", q.x + q.w <= 1920 and q.y + q.h <= 1008, string.format("%d,%d", q.x, q.y))

-- place: nothing to do when it is already there
check("already in place", M.place(win(), p, AREA, 32) == nil)
check("nothing saved", M.place(win(), nil, AREA, 32) == nil)

-- store with an in-memory io
local files = {}
local fake_io = { open = function(name, mode)
    if mode == "r" then
        if not files[name] then return nil end
        local data = files[name]
        return { read = function() return data end, close = function() end }
    end
    local buf = {}
    return { write = function(_, s) buf[#buf + 1] = s end,
             close = function() files[name] = table.concat(buf) end }
end }
local real_rename = os.rename
os.rename = function(a, b) files[b] = files[a]; files[a] = nil; return true end
local st = M.store("/tmp/places", fake_io)
st.put("thunar", p)
check("dirty after put", st.dirty)
check("save ok", st.save())
check("clean after save", not st.dirty)
st.put("thunar", p)
check("same place is not a change", not st.dirty)
local st2 = M.store("/tmp/places", fake_io)
eq("store reads back", st2.get("thunar").w, 1000)
os.rename = real_rename

print(string.format("window memory: %d passed, %d failed", passed, failed))
os.exit(failed == 0 and 0 or 1)
