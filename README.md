# rex-extrakto

An idiomatic [Rex](https://www.superlogical.com/rex) plugin for fast, fuzzy terminal text extraction and copying, inspired by [laktak/extrakto](https://github.com/laktak/extrakto).

Extract URLs, file paths, words, quotes, Git hashes, IP addresses, and lines from your Rex terminal panes into an interactive `fzf` popup layer without touching your mouse.

## Features

- **Floating Popup Layer:** Uses Rex's native `rex.session.new_layer` to overlay an interactive `fzf` window directly over your active pane.
- **Dynamic Filter Switching (`ctrl-f`):** Cycle through `all`, `path`, `url`, `word`, `line`, `quote` without leaving the prompt.
- **Dynamic Grab Area Switching (`ctrl-g`):** Toggle between `recent` (last 120 lines), `full` (entire scrollback), and `window` (all terminal panes in current window).
- **Multi-Selection:** Select multiple items with `Tab` / `Shift-Tab`.
- **Action Shortcuts:**
  - `Enter`: Copy selection to macOS clipboard (`pbcopy`).
  - `Tab`: Insert selection directly into the active Rex pane (`rex send`).
  - `Ctrl-O`: Open URL in browser or path in system viewer (`open`).
  - `Ctrl-E`: Open path in `$EDITOR` or `~/.config/mbianco/open-file-path.sh`.
  - `Esc` / `Ctrl-C`: Cancel and close popup.
- **Custom Filters:** Automatically loads definitions from `~/.config/extrakto/extrakto.conf` or `~/.config/rex/extrakto.conf`.

## Installation

Cloned or placed into `~/.config/rex/plugins/rex-extrakto`.

In `~/.config/rex/init.lua`:

```lua
-- If using the auto-loader in init.lua, it is loaded automatically.
-- Or configure explicitly:
local extrakto = require("rex-extrakto")
extrakto.setup({
  key = "ctrl+h>f",                  -- Default trigger sequence: Ctrl+H, then F
  filter = "all",                    -- Initial filter: all, path, url, word, line
  grab = "recent",                   -- Initial grab: recent, full, window
  bounds = { 0.1, 0.15, 0.8, 0.7 },  -- Floating modal bounds [x, y, w, h]
})
```

Reload config:
```sh
rex config reload
```

## Available Actions

* `extrakto`: Opens the extractor with default/declared settings.
* `extrakto_url`: Opens directly filtered to URLs.
* `extrakto_path`: Opens directly filtered to file paths.
* `extrakto_word`: Opens directly filtered to words.
* `extrakto_line`: Opens directly filtered to lines.
