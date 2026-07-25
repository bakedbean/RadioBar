# RadioBar for waybar — Design

**Date:** 2026-07-24
**Status:** Approved pending review
**Target:** omarchy (Arch Linux + Hyprland + waybar), added to this repo under `linux/`

## Goal

Port RadioBar's core experience to omarchy/waybar: live track info (artist – song)
displayed directly in the status bar, a global play/pause hotkey, and a
lightweight right-click station menu. Same "dirt simple" ethos as the macOS app.

Must-haves (from scoping):

- Live track info in the waybar module, updating within ~1s of a track change
- Play/pause via Hyprland global hotkey and via left-click on the module
- Right-click mini menu to switch stations (walker dmenu mode)

Explicit non-goals: volume control on the module, artwork fetching, a
full station-management UI. Stations are edited in a JSON file.

## Architecture

One Python 3 script (stdlib only), `radiobar`, installed to `~/.local/bin/radiobar`.
Playback and metadata are delegated entirely to mpv — the one runtime dependency
(`pacman -S mpv`). There is no custom daemon: if mpv isn't running, RadioBar is off.

```
waybar custom/radio ──exec──▶ radiobar status ──┐
Hyprland SUPER+SHIFT+R ─────▶ radiobar toggle ──┤   JSON IPC over
left-click ─────────────────▶ radiobar toggle ──┼──▶ $XDG_RUNTIME_DIR/radiobar.sock ──▶ mpv (audio + ICY)
right-click ────────────────▶ radiobar menu ────┘
```

mpv is launched as:

```
mpv --no-video \
    --input-ipc-server=$XDG_RUNTIME_DIR/radiobar.sock \
    --stream-lavf-o=reconnect_streamed=1,reconnect_delay_max=10 \
    <streamURL>
```

mpv decodes every format in the station list (MP3, AAC, HLS `.m3u8`) and parses
ICY metadata itself, exposing it as the `metadata/by-key/icy-title` property.
This replaces the macOS app's `MetadataParser` + second stream connection.

## Components

### `radiobar` subcommands

| Command | Behavior |
|---|---|
| `status` | Long-running. Connects to the mpv socket, `observe_property` on `metadata/by-key/icy-title`, `media-title`, and `pause`, prints one waybar JSON line (`{"text", "tooltip", "class"}`) per change. If no socket: emit idle state, re-poll every 2s. |
| `toggle` | Socket present → send `cycle pause`. Socket absent → launch mpv with the last-played station (or first station if none). |
| `play <name\|url>` | Stop any running mpv (`quit` over socket), launch mpv with the named station's URL (or a raw URL), record it as last-played. |
| `stop` | Send `quit` to mpv if running. |
| `menu` | Pipe station names through `walker --dmenu` (fallback: `fuzzel -d`), then `play` the selection. No selection → no-op. |

### Data files

- `~/.config/radiobar/stations.json` — same schema the macOS app persists
  (`name`, `streamURL`, `genre`, `websiteURL` per entry). Created on first run,
  seeded with the same 10 built-in stations. Malformed file → log to stderr and
  fall back to built-ins (never crash the bar).
- `~/.local/state/radiobar/last` — name of the last-played station, so a cold
  `toggle` can start playback without the menu.

### Display states

| State | Bar text | CSS class |
|---|---|---|
| Playing, title known | `󰐊 Artist – Song` (truncated ~40 chars; full title + station in tooltip) | `playing` |
| Playing, no title | `󰐊 <station name>` | `playing` |
| Paused | `󰏤 <station name>` | `paused` |
| mpv not running | `󰐹` (dim glyph) | `idle` |

Title fallback chain: `icy-title` → mpv `media-title` → station name. (BBC's HLS
stream has no ICY metadata; it falls back gracefully.)

### Config snippets shipped in `linux/`

- `linux/radiobar` — the script
- `linux/waybar-snippet.jsonc` — module block to paste into `~/.config/waybar/config.jsonc`:

  ```jsonc
  "custom/radio": {
    "exec": "radiobar status",
    "return-type": "json",
    "on-click": "radiobar toggle",
    "on-click-right": "radiobar menu",
    "tooltip": true
  }
  ```

- `linux/style-snippet.css` — `#custom-radio.playing/.paused/.idle` colors
- `linux/README.md` — install steps, including the Hyprland bind:

  ```
  bindd = SUPER SHIFT, R, RadioBar play/pause, exec, radiobar toggle
  ```

  (Verified free on the target machine: only `SUPER CTRL[+ALT/SHIFT], R`
  reminder binds use R.)

Install on omarchy: copy script to `~/.local/bin`, merge the two snippets,
add the bind, then `omarchy restart waybar`.

## Error handling

- **Stream drop / mpv exit:** `status` detects the closed socket, emits idle
  state immediately (never a stale title), and re-polls for a new socket every
  2s. mpv's reconnect flags absorb transient network blips before that point.
- **Toggle race:** `toggle` treats a connect-refused/stale socket file the same
  as no socket — clean it up and launch fresh.
- **Missing walker and fuzzel:** `menu` prints an error notification via
  `notify-send` and exits nonzero.
- **Malformed stations.json:** fall back to built-in list, warn on stderr.

## Testing

Pure functions with pytest coverage (`linux/test_radiobar.py`):

- Display-text formatting: truncation, glyph/state selection, tooltip content
- Title fallback chain (icy-title / media-title / station name)
- stations.json parsing, including malformed-file fallback to built-ins

Socket/mpv integration is verified manually against a SomaFM stream (ICY) and
the BBC HLS stream (no ICY).

## Out of scope / future

- Volume control (scroll on module) — easy later via `add volume` IPC
- Station add/remove UI — edit the JSON
- MPRIS integration (playerctl) — mpv ships this for free via its own MPRIS
  support if the user installs `mpv-mpris`; not part of this design
