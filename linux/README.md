# RadioBar for waybar (omarchy / Hyprland)

The Linux port of RadioBar: live track info in your waybar, play/pause from a
hotkey, right-click to switch stations. One script + mpv, no daemon.

## Requirements

- `mpv` (`sudo pacman -S mpv`)
- waybar with a Nerd Font (omarchy default works)
- walker or fuzzel for the station menu (omarchy ships walker)
- Python 3

## Install

    cp linux/radiobar ~/.local/bin/radiobar
    chmod +x ~/.local/bin/radiobar

**Waybar** — merge `linux/waybar-snippet.jsonc` into
`~/.config/waybar/config.jsonc` (add `"custom/radio"` to a modules array and
paste the module block), append `linux/style-snippet.css` to
`~/.config/waybar/style.css`, then restart waybar (`omarchy restart waybar`
on omarchy).

**Album art (optional)** — add `"image#radioart"` to the same modules array,
right before `"custom/radio"`, and paste this block among the module
definitions (adjust the path to your `$XDG_RUNTIME_DIR`):

    "image#radioart": {
      "path": "/run/user/1000/radiobar-art.png",
      "size": 24,
      "signal": 8,
      "tooltip": false
    }

**Hotkey (Hyprland)** — add to `~/.config/hypr/bindings.conf`:

    bindd = SUPER SHIFT, R, RadioBar play/pause, exec, radiobar toggle

## Usage

| Action | How |
|---|---|
| Play/pause | Left-click the module, or SUPER+SHIFT+R |
| Switch station | Right-click the module |
| Add a station | Edit `~/.config/radiobar/stations.json` (same schema as the macOS app) |
| Stop | `radiobar stop` |

The module shows `󰐊 Artist – Song` while playing (full title in the tooltip),
`󰏤 Station` when paused, and a dim `󰐹` when off.

On every track change, RadioBar also looks up the artist/title on the
iTunes Search API and, if it finds a match, writes the cover art to
`$XDG_RUNTIME_DIR/radiobar-art.png` (for the optional `image#radioart`
waybar module above) and fires a desktop notification with the cover art
and release year. Lookups (hits and misses) are cached in
`~/.cache/radiobar/` so repeat plays of the same track don't re-query the
API. Set `RADIOBAR_NO_NOTIFY=1` to disable the desktop notification (the
art thumbnail still updates). Notifications require a running notification
daemon — mako on omarchy, started automatically as part of the desktop.

## How it works

mpv plays the stream and parses ICY (Shoutcast/Icecast) metadata natively.
`radiobar status` subscribes to mpv's JSON IPC socket
(`$XDG_RUNTIME_DIR/radiobar.sock`), observes `icy-title`/`media-title`/`pause`, and prints a
waybar JSON line on every change — so track changes hit the bar within a
second. Streams without ICY metadata (e.g. BBC's HLS) fall back to the
station name.

A background worker thread does the artwork/notification lookup so it
never blocks the waybar status output: on each track change it queries the
iTunes Search API (with an in-memory + on-disk cache under
`~/.cache/radiobar/`), writes the cover art to
`$XDG_RUNTIME_DIR/radiobar-art.png` on a hit, signals waybar
(`pkill -RTMIN+8 waybar`) to refresh the `image#radioart` module, and sends
a notification via `notify-send` (skipped if `RADIOBAR_NO_NOTIFY=1` is
set). `radiobar stop` clears the art file and re-signals waybar so the
thumbnail disappears.

## Tests

    python -m pytest linux/test_radiobar.py
