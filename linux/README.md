# RadioBar for waybar (omarchy / Hyprland)

The Linux port of RadioBar: one waybar module for everything you're
listening to. It shows live radio track info, or — when radio is silent —
whatever's playing over MPRIS (Spotify, a browser tab, Discord), with a
scrolling, colored title. RadioBar enforces a single audible source: start
playing a track anywhere and radio pauses; toggle radio back on and
everything else pauses. One script + mpv, no daemon.

## Requirements

- `mpv` (`sudo pacman -S mpv`)
- `playerctl` (`sudo pacman -S playerctl`) — feeds MPRIS player state
  (Spotify, browser, Discord, etc.) into the module. Without it, the MPRIS
  side is disabled and the module behaves as radio-only.
- waybar with a Nerd Font (omarchy default works)
- walker or fuzzel for the station menu (omarchy ships walker)
- Python 3
- optional: `imagemagick` or `ffmpeg` — downscales Spotify/browser cover art
  for the bar thumbnail; without one, MPRIS art appears only in
  notifications (radio art via iTunes is unaffected)

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
      "path": "/run/user/1000/radiobar-art.jpg",
      "size": 20,
      "signal": 6,
      "tooltip": false
    }

**Hotkey (Hyprland)** — add to `~/.config/hypr/bindings.conf`:

    bindd = SUPER SHIFT, R, RadioBar play/pause, exec, radiobar toggle

If you previously ran a separate `custom/mpris` waybar module (e.g. a
playerctl-scroll script) for Spotify/browser now-playing info, remove it —
RadioBar's `custom/radio` module now covers it, and running both will show
duplicate now-playing info in the bar.

## Usage

| Action | How |
|---|---|
| Play/pause the shown source | Left-click the module (starts your last station if nothing's playing), or SUPER+SHIFT+R |
| Previous track (MPRIS only) | Middle-click the module |
| Switch station / stop radio | Right-click the module — shows `■ Stop radio` first while radio is playing |
| Next track (MPRIS only) | `radiobar next` (bind to a hotkey if you want one) |
| Add a station | Edit `~/.config/radiobar/stations.json` (same schema as the macOS app) |
| Stop radio | `radiobar stop` |

The bar shows exactly one source at a time: radio whenever it's audible,
otherwise the most relevant MPRIS player (the one that's playing; if
several are paused, whichever changed most recently). Titles longer than
30 characters scroll in a colored window; the full title is in the
tooltip. The module shows `󰐊 Artist – Song` while playing (radio or
MPRIS), `󰏤 Station` when radio is paused, and a dim `󰐹` when everything's
off.

Only one source is ever audible: starting playback on an MPRIS player
(Spotify, a browser tab, Discord, ...) pauses radio, and resuming or
switching radio (`toggle`, `play`) pauses every other MPRIS player via
`playerctl -a pause`. RadioBar only ever pauses other apps — it never
resumes them for you.

On every track change, RadioBar fires a desktop notification and updates
the `image#radioart` thumbnail, for radio and MPRIS sources alike. For
radio, it looks up the artist/title on the iTunes Search API and, if it
finds a match, writes the cover art and release year; lookups (hits and
misses) are cached in `~/.cache/radiobar/` so repeat plays of the same
track don't re-query the API. For MPRIS players, it downloads the art
`mpris:artUrl` points to and downscales it for the bar thumbnail with
whichever of `magick`, `convert`, or `ffmpeg` it finds; without any of the
three, MPRIS art still appears in the notification, just not in the bar.
Set `RADIOBAR_NO_NOTIFY=1` to disable the desktop notification (the art
thumbnail still updates). Notifications require a running notification
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
iTunes Search API (caching hits and misses on disk under
`~/.cache/radiobar/`), writes the native 100×100 cover art to
`$XDG_RUNTIME_DIR/radiobar-art.jpg` on a hit (the 600×600 image is kept only
for the notification — waybar 0.15's `image` module hangs the whole bar on
a 600×600 image), signals waybar
(`pkill -RTMIN+6 waybar`) to refresh the `image#radioart` module, and sends
a notification via `notify-send` (skipped if `RADIOBAR_NO_NOTIFY=1` is
set). `radiobar stop` clears the art file and re-signals waybar so the
thumbnail disappears.

`radiobar status` also runs `playerctl --all-players --follow metadata`
in the background to track every MPRIS player's state and metadata. On
each event it recomputes which source should own the bar: radio if it's
playing, else whichever MPRIS player is playing; if none are playing, the
one that's paused and changed most recently; radio itself is the
fallback if nothing else has ever reported state. Playing beats paused,
and recency breaks ties among same-state MPRIS players. `radiobar toggle`
and `radiobar play` call `playerctl -a pause` before starting or resuming
radio so nothing else stays audible; conversely, any MPRIS player
transitioning to "Playing" makes RadioBar pause the mpv radio stream.
`radiobar click`/`prev`/`next` forward to `playerctl play-pause` /
`previous` / `next` on the currently-shown player when it's an MPRIS
source, or to radio's own toggle otherwise. For MPRIS art, the worker
fetches the track's `mpris:artUrl` and downscales it to 128px with
whichever of `magick`, `convert`, or `ffmpeg` is available (radio's
iTunes-sourced art is unaffected either way).

## Tests

    python -m pytest linux/test_radiobar.py
