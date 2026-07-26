# RadioBar for waybar — Unified Now-Playing Module Design

**Date:** 2026-07-25
**Status:** Approved
**Builds on:** `2026-07-24-radiobar-waybar-design.md`, `2026-07-24-radiobar-artwork-design.md`

## Goal

Merge the standalone `custom/mpris` waybar module
(`~/.config/waybar/scripts/mpris-scroll.py` — Spotify/browser/Discord monitor)
into RadioBar, so **one bar slot** shows whatever is playing: RadioBar's own
radio stream when active, otherwise the most relevant MPRIS player. Retires
`mpris-scroll.py` and its ~40 subprocess spawns per second in favor of an
event-driven design, and gives MPRIS sources RadioBar's album-art and
notification machinery.

Non-goals: controlling MPRIS players beyond play-pause/prev/next, per-player
configuration UI, seeking/volume, macOS changes, keeping the old two-slot
layout.

## Source priority (arbiter)

The bar always shows what's audible. Given radio state (from mpv IPC) and the
set of MPRIS players (from playerctl), radio is just another source:

1. `Playing` beats `Paused`, across all sources. Among equals, the source
   whose state changed most recently wins (monotonic sequence number, no
   wall-clock).
2. No radio, no players → idle (`󰐹`, click starts last station).

Two sources both `Playing` is transient — the guard below resolves it — so
the recency tie-break only matters for the moment it takes to fire.

## One-audible-source guard

RadioBar enforces "at most one audible source, last-started wins":

- **MPRIS player starts while radio is playing** → the status process pauses
  its own mpv (IPC `set pause true`). The bar flips to the MPRIS player; the
  station sits paused, resumable via hotkey/menu. The guard is edge-triggered
  (fires on a player's transition to `Playing`, not on level state), so it
  can't fight with a user resuming radio.
- **Radio starts/resumes while an MPRIS player is playing** → `cmd_toggle`
  and `cmd_play` run `playerctl -a pause` (idempotent) before starting or
  unpausing mpv. These are short-lived commands, so no coordination with the
  status process is needed.

RadioBar never *stops* another app, only pauses it.

While RadioBar's own mpv is running, MPRIS players whose name starts with
`mpv` are ignored, so an installed mpv-mpris plugin can't make the radio
stream double-report as an MPRIS source. (When radio is stopped, mpv players
are shown normally — a video played in mpv is a legitimate source.)

## Display (renderer)

Ports the look of `mpris-scroll.py`, applied to **all** sources including
radio (replacing radio's current 40-char plain truncate):

- Text: `{player_icon} {status_icon} {artist} - {title}` (radio:
  icy-title/media-title/station fallback, as today).
- Scroll: 30-char window; longer text wraps around with `   •   ` padding,
  advancing one char per 100 ms with a 1 s pause at the seam. The 100 ms
  ticker runs **only while the visible text overflows**; otherwise output is
  event-driven (no wakeups when idle or when the title fits).
- Colors: on each track change, pick a random color pair from the existing
  20-color palette — one for the player icon, one for the title — emitted as
  Pango markup. Waybar `class` field still carries `playing`/`paused`/`idle`
  for CSS.
- Icons: MPRIS sources show a player icon (`` spotify, `` shortwave,
  `` discord, `󰝚` fallback) plus a `` status icon when paused. Radio
  shows `󰐊` playing / `󰏤` paused as its sole icon (as today — no separate
  status icon). Idle shows `󰐹`.
- Tooltip: full `artist\ntitle` plus source (station name or player name).

## MPRIS backend

One long-lived subprocess, spawned by `radiobar status`:

    playerctl -a -F metadata --format '{{playerName}}\t{{status}}\t{{artist}}\t{{title}}\t{{mpris:artUrl}}'

- A reader thread parses each line into a per-player state dict
  `{status, artist, title, art_url, changed_seq}` (monotonic sequence number
  for recency — no wall-clock reads). Malformed lines are skipped.
- Player disappearance: playerctl `-F` emits an empty/cleared line for a
  vanished player; the parser drops it from the dict. Exact emission shape
  verified during implementation against playerctl ≥ 2.4 and the parser
  written to tolerate both empty-field and missing-line forms (a stale
  `Stopped` entry must not win the arbiter).
- `playerctl` binary missing → MPRIS source disabled with a single stderr
  warning; radio-only behavior is preserved. Subprocess exit → respawn with
  2 s backoff.

## Data flow & concurrency

Two watcher threads — mpv socket (existing `watch`) and playerctl stdout —
update a lock-protected state store and set a change `Event`. The render loop
wakes on the event (or on the 100 ms tick while scrolling), runs the arbiter,
and emits one waybar JSON line. When the arbiter's *track identity*
(source + artist + title) changes, it kicks the ArtWorker and notification
(existing in-flight/latest guards) and atomically rewrites the active-source
file (below).

## Album art

The existing `image#radioart` thumbnail becomes the unified art slot:

- Radio: iTunes lookup, unchanged (100×100 to the bar, 600×600 to the
  notification).
- MPRIS: use `mpris:artUrl` directly — `https://` downloaded (10 s timeout),
  `file://` copied; cached under the existing sha1-keyed cache with the same
  miss-caching. No iTunes lookup for MPRIS sources.
- **Bar-freeze guard:** waybar 0.15's image module hangs the bar on ~600 px
  images. MPRIS art (e.g. Spotify's 640×640) is downscaled to 128 px via the
  first of `magick`/`convert`/`ffmpeg` found on PATH. If no downscaler exists,
  the bar thumbnail is **skipped** for that track (never publish an image of
  unverified size); the notification still gets the full image.
- On source change the thumbnail is replaced or cleared (`pkill -RTMIN+6
  waybar`, existing mechanism); cleared when idle.

## Notifications

All sources notify on track change via `notify-send -a RadioBar` with art
when available, using the existing last-notified marker for dedup.
Body: radio `Station · Year` (as today); MPRIS: the player name, capitalized
(e.g. `Spotify`). `RADIOBAR_NO_NOTIFY=1` disables, as today.

## Click handling

`radiobar status` atomically writes `$XDG_RUNTIME_DIR/radiobar-active.json`
(`{"source": "radio"|"mpris"|"idle", "player": <name-or-null>}`) whenever the
active source changes. New subcommands read it and dispatch:

- `radiobar click` — radio → mpv pause toggle (IPC); mpris →
  `playerctl -p <player> play-pause`; idle/missing file → start last station
  (existing `cmd_toggle` fallback path).
- `radiobar prev` / `radiobar next` — mpris → `playerctl -p <player>`
  previous/next; radio or idle → no-op.
- `toggle` and `play` gain the `playerctl -a pause` guard (above) but keep
  their interface — the SUPER+SHIFT+R hotkey (`radiobar toggle`) still
  starts/resumes/pauses radio exactly as today. `stop` unchanged.
- `menu` gains a `■ Stop radio` entry at the top of the station list whenever
  radio is running (mpv socket connectable); selecting it runs the `stop`
  path. This keeps a fully-stopped radio one right-click away even when the
  bar is showing an MPRIS source.

Waybar bindings: `on-click: radiobar click`,
`on-click-middle: radiobar prev`, `on-click-right: radiobar menu`.
(`next` is available for a hotkey; not bound in the bar to keep right-click
as the station menu.)

## Components (all in `linux/radiobar`, single file)

- `parse_playerctl_line(line) -> (player, state|None)` — pure.
- `class MprisSource` — subprocess lifecycle + reader thread; holds the
  players dict.
- `arbiter(radio_state, players) -> Active(source, player, status, artist,
  title, art_ref)` — pure.
- `guard_action(prev_players, players, radio_state) -> "pause_radio"|None` —
  pure edge-transition detector; the render loop executes its verdict via
  mpv IPC.
- `class Renderer` — scroll offset/pause state machine + color pairs + icon
  maps; `render(active, tick) -> waybar dict` pure given its state.
- `ArtWorker` — gains `art_url` path (download/copy + downscale) beside the
  existing iTunes path.
- `write_active(active)` / `read_active()` — active-source file.
- `cmd_click`, `cmd_prev`, `cmd_next` — dispatch with injected runner.
- Existing `StatusTracker`/`watch` refactored to feed the store instead of
  printing.

The file stays single-file for the `cp linux/radiobar ~/.local/bin/` install
story; if it grows past ~1,200 lines in implementation, splitting becomes a
follow-up, not part of this change.

## Testing

`linux/test_radiobar.py` style — pure functions, injected I/O, no threads:
playerctl line parsing (incl. malformed/cleared lines), arbiter priorities
(playing beats paused across sources, recency tie-break, mpv-ignore rule),
guard transitions (MPRIS starts while radio plays → pause_radio; no fire on
level state, on radio-only, or on ignored mpv players), scroll windowing (short text, wrap seam, pause counter),
renderer JSON shape and class field, art path selection
(https/file/no-downscaler skip), click/prev/next dispatch against a fake
active file and runner, active-file round-trip.

## Migration

- Repo: update `waybar-snippet.jsonc` (new click bindings),
  `style-snippet.css` if needed, `linux/README.md` (requirements gain
  `playerctl`, optional `imagemagick` or `ffmpeg` for MPRIS bar art;
  document unified behavior).
- Live machine: remove `custom/mpris` from `modules-left` and its module
  block from `~/.config/waybar/config.jsonc`; update `custom/radio` click
  bindings; restart waybar. `~/.config/waybar/scripts/mpris-scroll.py`
  becomes unused (left in place; removal optional).
