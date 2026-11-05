-- ~/.config/rex/plugins/rex-extrakto/init.lua
-- rex-extrakto: Idiomatic Rex plugin for fuzzy text extraction

local M = {}

local function resolve_script_path(custom_path)
  if custom_path then
    return custom_path .. "/extrakto.py"
  end
  local src = debug.getinfo(1, "S").source:gsub("^@", "")
  if src:find("[/\\]") then
    local dir = src:match("(.*)[/\\]")
    return dir .. "/extrakto.py"
  end
  local config_home = os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")
  return config_home .. "/rex/plugins/rex-extrakto/extrakto.py"
end

function M.setup(opts)
  opts = opts or {}
  local script_path = resolve_script_path(opts.path)
  local bounds = opts.bounds or { 0.1, 0.15, 0.8, 0.7 }
  local default_filter = opts.filter or "all"
  local default_grab = opts.grab or "recent"
  local key = opts.key or "ctrl+h>f"
  local url_key = opts.url_key or "ctrl+h>u"
  local bg_color = opts.bg_color or "#282c34"

  -- Main extrakto action
  rex.action{
    name = "extrakto",
    title = "Extrakto: Fuzzy Text Extractor",
    description = "Extract and fuzzy-select URLs, paths, words, and lines from terminal",
    category = "Selection",
    keywords = "extrakto fzf copy url path word select",
    args = {
      filter = "string?",
      grab = "string?",
    },
    run = function(ctx, args)
      if not ctx.block_id then
        error("extrakto: no active pane", 0)
      end

      local filter = args.filter or default_filter
      local grab = args.grab or default_grab

      local layer, err = rex.session.new_layer{
        bounds = bounds,
        focus = true,
        layout = rex.layout.block{
          flavor = "com.superlogical.terminal.shell",
          options = {
            shell = "zsh",
            theme = {
              background = bg_color,
            },
            login = true,
            command = {
              "zsh", "-l", "-c",
              [[python3 "$1" --session "$2" --block "$3" --filter "$4" --grab "$5" --bg-color "$6" 2>>/tmp/extrakto.err; ]]
                .. [[rex focus -s "$2" "$3" >/dev/null 2>&1]],
              "rex-extrakto", script_path, ctx.session_id, ctx.block_id, filter, grab, bg_color,
            },
          },
        },
      }

      if not layer then
        error("extrakto failed to create floating layer: " .. tostring(err), 0)
      end

      return layer
    end,
  }

  -- Convenience actions for command palette & direct keybindings
  rex.action{
    name = "extrakto_url",
    title = "Extrakto: Extract URLs",
    description = "Fuzzy search and select URLs from terminal",
    category = "Selection",
    keywords = "extrakto url browser link",
    run = function(ctx)
      return rex.invoke("extrakto", { filter = "url" })
    end,
  }

  rex.action{
    name = "extrakto_path",
    title = "Extrakto: Extract Paths",
    description = "Fuzzy search and select file paths from terminal",
    category = "Selection",
    keywords = "extrakto path file editor",
    run = function(ctx)
      return rex.invoke("extrakto", { filter = "path" })
    end,
  }

  rex.action{
    name = "extrakto_word",
    title = "Extrakto: Extract Words",
    description = "Fuzzy search and select words from terminal",
    category = "Selection",
    keywords = "extrakto word",
    run = function(ctx)
      return rex.invoke("extrakto", { filter = "word" })
    end,
  }

  rex.action{
    name = "extrakto_line",
    title = "Extrakto: Extract Lines",
    description = "Fuzzy search and select lines from terminal",
    category = "Selection",
    keywords = "extrakto line",
    run = function(ctx)
      return rex.invoke("extrakto", { filter = "line" })
    end,
  }

  if key and key ~= false then
    rex.bind(key, "extrakto")
  end
  if url_key and url_key ~= false then
    rex.bind(url_key, "extrakto_url")
  end
end

return M
