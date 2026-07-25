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

## How it works

mpv plays the stream and parses ICY (Shoutcast/Icecast) metadata natively.
`radiobar status` subscribes to mpv's JSON IPC socket
(`$XDG_RUNTIME_DIR/radiobar.sock`), observes `icy-title`/`media-title`/`pause`, and prints a
waybar JSON line on every change — so track changes hit the bar within a
second. Streams without ICY metadata (e.g. BBC's HLS) fall back to the
station name.

## Tests

    python -m pytest linux/test_radiobar.py
