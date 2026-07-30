# Migrating this machine's waybar from `custom/mpris` to RadioBar — Design

**Date:** 2026-07-29
**Status:** Approved
**Target:** `eben`'s omarchy install (waybar 0.15.0, Hyprland, UID 1000)

## Goal

Retire the hand-rolled `custom/mpris` waybar module on this machine and adopt
RadioBar's `custom/radio`, gaining live radio alongside the MPRIS now-playing
info the old module already showed.

This is a *deployment* spec, not a code change: every edit lands in `~/.config`,
outside this repo. It is written down because the migration has several
non-obvious constraints (a waybar 0.15.0 freeze bug, a GTK CSS specificity trap,
and a font requirement) that are easy to get wrong and painful to debug.

## Problem

`modules-left` ends with `custom/mpris`, backed by
`~/.config/waybar/scripts/mpris-scroll.py` (161 lines). That script polls
`playerctl` at 10 Hz, spawning four subprocesses per tick — roughly 40 process
spawns per second, indefinitely — and knows nothing about radio.

`config.jsonc` also carries a bare `mpris` module definition that no
`modules-*` array references: dead config from an earlier iteration.

RadioBar's `custom/radio` is a strict superset. It keeps the feature the old
script was built for — a random icon/text color pair re-chosen on every track
change (`linux/radiobar:41`, `linux/radiobar:503`) — but is event-driven,
subscribing to mpv's JSON IPC socket and one long-lived
`playerctl --all-players --follow` instead of re-shelling on a timer.

## Preconditions (verified 2026-07-29)

| Requirement | State |
|---|---|
| `mpv`, `playerctl`, `walker`, `python3`, `notify-send` | present |
| `magick`, `convert`, `ffmpeg` (art downscaling) | all three present |
| Nerd Font, monospace | `FiraCode Nerd Font`, `fc-match` spacing=100 |
| `~/.local/bin` in **waybar's** PATH | yes (inherited via uwsm) |
| `SUPER SHIFT R` | unbound — no `unbind` directive needed |
| `$XDG_RUNTIME_DIR` | `/run/user/1000` |
| waybar version | 0.15.0 — the version with the `interval` bug |
| `~/.local/bin/radiobar`, `~/.config/radiobar/` | neither exists yet |

## Changes

### 1. Install (symlink, not copy)

```
ln -sfn /home/eben/RadioBar/linux/radiobar ~/.local/bin/radiobar
```

Chosen over the README's `cp` so a `git pull` in `/home/eben/RadioBar`
propagates to the bar with no re-copy. The tradeoff accepted: the bar breaks if
that checkout moves or is deleted. No `chmod` — the source is already `+x` with
a `#!/usr/bin/env python3` shebang. No station setup — `load_stations()`
(`linux/radiobar:116`) seeds `stations.json` from built-ins on first run.

### 2. `~/.config/waybar/config.jsonc`

Swap the tail of `modules-left`:

```diff
- ..., "hyprland/workspaces#special", "custom/mpris"]
+ ..., "hyprland/workspaces#special", "image#radioart", "custom/radio"]
```

End-of-`modules-left` is the correct slot and is where `custom/mpris` already
sits: its free edge faces the empty bar center, so the marquee cannot be nudged
sideways by a neighbor whose width changes. This machine's `network` module has
variable-width bandwidth fields, but it lives in `modules-right` and therefore
cannot shift `modules-left`.

Delete both the `mpris` block (dead) and the `custom/mpris` block, replacing
them with:

```jsonc
"custom/radio": {
  "exec": "radiobar status",
  "return-type": "json",
  "on-click": "radiobar click",
  "on-click-middle": "radiobar prev",
  "on-click-right": "radiobar menu",
  "tooltip": true
},
"image#radioart": {
  "path": "/run/user/1000/radiobar-art.jpg",
  "size": 20,
  "signal": 6,
  "interval": "once",
  "tooltip": false
}
```

`"interval": "once"` is load-bearing and gets an explanatory comment in-place.
waybar 0.15.0 clamps a *missing* `interval` to 1ms, so the module would reload
the jpg ~1000×/s: ~50% CPU plus enough Dispatcher-pipe traffic to routinely trip
waybar's module-mutex deadlock and freeze the entire bar. RadioBar's
`pkill -RTMIN+6 waybar` refreshes the art on track changes, so polling is never
needed. `size: 20` sits 6px under the configured bar `height: 26`.

`mpris-scroll.py` is left on disk untouched, so reverting is a config-only edit.

### 3. `~/.config/waybar/style.css`

Append, with one deliberate deviation from `linux/style-snippet.css` — the font
is pinned to `FiraCode Nerd Font` (this bar's existing font) rather than the
snippet's `CaskaydiaMono Nerd Font`:

```css
#custom-radio { padding: 0 10px; }
#custom-radio,
#custom-radio label { font-family: 'FiraCode Nerd Font'; }
#custom-radio.playing { color: @foreground; }
#custom-radio.paused,
#custom-radio.idle { opacity: 0.5; }
```

Two constraints are in play, and both are satisfied:

- **Monospace is required.** Under a proportional font the 30-char scroll
  window's pixel width varies each tick and the module's left edge visibly jumps.
  The snippet hardcodes CaskaydiaMono only as a safe omarchy-default bet; the
  real requirement is "any monospace font," and `FiraCode Nerd Font` is
  `spacing=100`. Pinning the current font satisfies the constraint *and* matches
  the rest of the bar's glyphs.
- **The pin must be explicit, and must name the label node.** This
  `style.css` has `* { font-family: 'FiraCode Nerd Font'; }`. In GTK CSS that
  universal selector matches waybar's inner label node *directly*, which beats a
  font merely inherited from the `#custom-radio` container — hence
  `#custom-radio label` in the selector list, where the ID out-specifies `*`.
  Relying on inheritance from `*` instead would also mean a future
  `omarchy font set <proportional font>` silently starts jogging the bar.

`@foreground` is already in scope via the existing
`@import "../omarchy/current/theme/waybar.css"`.

No `#image.radioart` rule initially: `#workspaces.special`'s `padding-right: 10px`
and `#custom-radio`'s left padding already frame the thumbnail. Add margins later
only if it reads as cramped.

### 4. `~/.config/hypr/bindings.conf`

```
bindd = SUPER SHIFT, R, RadioBar play/pause, exec, radiobar toggle
```

`SUPER SHIFT R` is free. Nearest neighbors are `SUPER CTRL R` (reminders,
omarchy default) and `SUPER SHIFT M` (Spotify) — neither collides, so no
`unbind` directive is required.

## Testing

Run in order; each step gates the next.

1. `python -m pytest linux/test_radiobar.py` — repo suite still green.
2. `timeout 5 radiobar status` — emits parseable waybar JSON lines via the
   symlink, confirming PATH resolution and the shebang.
3. `omarchy restart waybar` (waybar does *not* auto-reload).
4. Confirm waybar is alive after ~10s and its log is free of module errors —
   this is the check that would catch the `interval` freeze.
5. Screenshot the bar to confirm the module and thumbnail render, that the
   marquee does not jog, and that glyph style matches its neighbors.

## Rollback

Timestamped `.bak` copies of `config.jsonc`, `style.css`, and `bindings.conf`
before any edit. Since `mpris-scroll.py` is preserved, reverting is restoring
`config.jsonc` and `style.css` and restarting waybar.

## Out of scope (YAGNI)

- Pruning the 6 pre-existing `config.jsonc.bak.*` files.
- Updating `linux/README.md` with the two findings from this migration — that a
  reader whose bar font is already monospace can pin *that* font instead of
  CaskaydiaMono, and that a symlink install is an option when working from a
  checkout. Both are genuine doc improvements; neither is part of "replace my
  module." Deferred to a follow-up.
- Any change to `linux/radiobar` itself. No defect was found.
