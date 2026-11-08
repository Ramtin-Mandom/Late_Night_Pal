-- Late Night Pal read guard. The trusted preamble runs this (copied into the job folder as
-- lnp-guard.lua) after loading the allowlisted packages and before any generated LaTeX.
-- Generated code may read job files (relative names without ..) and TeX/font files
-- (by extension); any other absolute or ../ path is refused, so a body cannot pull a
-- user's documents or .env into the PDF. File changes and process launches outside the
-- job folder are refused. Best effort: the static check in validation.py keeps Lua out of
-- generated code in the first place; see architecture.md for the remaining limits.

local find, lower, match = string.find, string.lower, string.match
local TREE = {}
for e in ("tex sty cls cfg def fd clo ldf ltx lua luc gz otf ttf ttc pfb pfm afm tfm vf ofm ovf enc map fmt"):gmatch("%S+") do
  TREE[e] = true
end

local function outside(p)
  return find(p, "^%a:") or find(p, "^[/\\]") or find(p, "%.%.")
end

local function readable(p)
  p = tostring(p or "")
  if not outside(p) then return true end
  local name = lower(match(p, "[^/\\]+$") or "")
  return TREE[match(name, "%.(%w+)$") or ""] == true and not find(name, "^%.env")
end

local function local_only(p) return not outside(tostring(p or "")) end

local function refuse(what) return nil, "Late Night Pal: " .. what .. " is not allowed here" end

local function guard_first(tbl, key, ok)
  local f = tbl and tbl[key]
  if type(f) ~= "function" then return end
  tbl[key] = function(name, ...)
    if type(name) == "string" and not ok(name) then return refuse(key .. " " .. name) end
    return f(name, ...)
  end
end

local open = io.open
io.open = function(name, mode)
  mode = tostring(mode or "r")
  local ok = find(mode, "[wa+]") and local_only(name) or (not find(mode, "[wa+]") and readable(name))
  if not ok then return refuse("opening " .. tostring(name)) end
  return open(name, mode)
end
for _, k in ipairs({"lines", "input", "loaddata", "loadlines", "loadchunk", "exists", "size"}) do
  guard_first(io, k, readable)
end
for _, k in ipairs({"output", "savedata", "appenddata", "copydata"}) do guard_first(io, k, local_only) end
guard_first(_G, "dofile", readable)
guard_first(_G, "loadfile", readable)
guard_first(os, "remove", local_only)
guard_first(os, "rename", local_only)
for _, k in ipairs({"mkdir", "rmdir", "touch", "link", "chdir", "lock"}) do guard_first(lfs, k, local_only) end
for _, k in ipairs({"execute", "exec", "spawn", "kpsepopen"}) do
  if os[k] then os[k] = function() return refuse("starting a program") end end
end
io.popen = function() return refuse("starting a program") end
if img then
  for _, k in ipairs({"scan", "new"}) do
    local f = img[k]
    if f then img[k] = function(t, ...)
      if type(t) == "table" and t.filename and not local_only(t.filename) then return refuse("image " .. t.filename) end
      return f(t, ...)
    end end
  end
end

local function find_checked(id, name)
  if not readable(name) then return nil end
  return kpse.find_file(name, "tex") or (lfs.isfile(name) and name) or nil
end
luatexbase.add_to_callback("find_read_file", find_checked, "lnp-guard")
luatexbase.add_to_callback("find_image_file", function(name)
  if local_only(name) then return name end
  return nil
end, "lnp-guard")

-- Keep generated code from undoing the guard.
local remove = luatexbase.remove_from_callback
luatexbase.remove_from_callback = function(cb, desc, ...)
  if desc == "lnp-guard" then return nil end
  return remove(cb, desc, ...)
end
local register = callback.register
callback.register = function(cb, ...)
  if cb == "find_read_file" or cb == "find_image_file" or cb == "open_read_file" then return nil end
  return register(cb, ...)
end
package.loaded.debug = nil
debug = nil
