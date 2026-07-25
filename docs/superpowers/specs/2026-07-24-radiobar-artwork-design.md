# RadioBar for waybar — Album Artwork Design

**Date:** 2026-07-24
**Status:** Approved
**Builds on:** `2026-07-24-radiobar-waybar-design.md` (the shipped waybar port, branch `waybar-port`)

## Goal

Show album artwork for the playing track, porting the macOS `ArtworkFetcher.swift`
behavior: iTunes Search API lookup by "Artist - Song", 600×600 art, release year,
cached. Two surfaces (both):

1. Persistent thumbnail in the bar via waybar's built-in `image` module.
2. A mako notification with the cover and release year on each track change.

Non-goals: artwork in tooltips (waybar tooltips are text-only), MPRIS art,
configurable art sources.

## Behavior

- Trigger: each **new** ICY title observed by `radiobar status`. Skip when the
  display title is just the station-name fallback (no real track info, e.g. BBC HLS).
- Lookup: `https://itunes.apple.com/search?term=<urlencoded title>&entity=song&limit=1`
  (urllib, stdlib, 10s timeout). From the first result: `artworkUrl100` with
  `100x100` → `600x600`, and the leading 4-digit year of `releaseDate`.
- Cache: `$XDG_CACHE_HOME/radiobar/` (override env `RADIOBAR_CACHE_DIR`).
  Per track (key = sha1 of title): `<key>.jpg` plus `<key>.json` sidecar
  `{"year": 1994 | null, "found": true|false}`. Failed lookups cache as misses —
  no retry storm. Cache is unbounded (cover JPEGs are ~50 KB; acceptable).
- Bar: on art available, copy to `$XDG_RUNTIME_DIR/radiobar-art.png` (override
  env `RADIOBAR_ART_PATH`) and `pkill -RTMIN+6 waybar`. On no-art or `stop`,
  remove the file (waybar's image module auto-hides). Art persists while paused.
- Notification: `notify-send -a RadioBar -i <art-or-omitted> "<title>" "<station> · <year>"`
  (year omitted when unknown). Suppressed when `RADIOBAR_NO_NOTIFY=1`.
  A last-notified marker (`$XDG_RUNTIME_DIR/radiobar-last-notify`) prevents a
  duplicate notification when `status` reconnects and mpv replays the current title.
- Threading: the fetch runs on a `threading.Thread` (daemon) spawned from the
  watch loop, so network latency never delays bar updates. One in-flight fetch
  per title (dedupe set), mirroring the Swift `inFlight` guard.

## Components (all in `linux/radiobar`)

- `itunes_lookup(title, opener) -> {"art_url": str|None, "year": int|None}` —
  pure parsing separated from I/O; opener injected for tests.
- `art_cache_paths(title) -> (jpg_path, json_path)`; `cached_track_info(title)`;
  `store_track_info(title, ...)`.
- `class ArtworkWorker` — dedupe set + thread spawn; calls injected `fetch_fn`,
  `publish_fn` (bar file + signal), `notify_fn`. `StatusTracker`/`watch` call
  `worker.track_changed(title, station)` on icy-title transitions;
  `cmd_stop`/idle path calls `worker.clear()`.
- Waybar snippet gains `"image#radioart": {"path": "<runtime>/radiobar-art.png", "size": 24, "signal": 6}`;
  add `image#radioart` next to `custom/radio` in modules array. Update
  `linux/README.md` (features, requirements note: mako for notifications) and
  the live machine's waybar config.

## Error handling

- Network/API/JSON failures → cached miss, art cleared; the track-change
  notification still fires (title/station, no cover); never raises into the
  watch loop (thread body wraps everything).
- `pkill`/`notify-send` absent or failing → ignored (bar text is unaffected).

## Testing

Pure-function pytest coverage following the existing injection patterns:
iTunes JSON parsing (URL swap, year extraction, missing-fields), cache
path/round-trip with `RADIOBAR_CACHE_DIR`, ArtworkWorker decision logic
(skip station-name titles, dedupe in-flight, notify-once marker, clear on
stop) with fake fetch/publish/notify. Live verification on this machine
against a SomaFM stream.
