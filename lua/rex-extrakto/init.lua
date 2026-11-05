-- Amber / standard Lua module loader for rex-extrakto
local src = debug.getinfo(1, "S").source:gsub("^@", "")
local root_dir = src:match("(.*)[/\\]lua[/\\]rex%-extrakto")
if root_dir then
  local fn = assert(loadfile(root_dir .. "/init.lua"))
  return fn()
end
return require("init")
