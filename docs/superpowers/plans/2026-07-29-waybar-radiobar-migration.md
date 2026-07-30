# waybar `custom/mpris` → RadioBar `custom/radio` Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace this machine's hand-rolled `custom/mpris` waybar module with RadioBar's `custom/radio`, adding live radio and an album-art thumbnail alongside the MPRIS now-playing info the old module already showed.

**Architecture:** Symlink `radiobar` into `~/.local/bin`, then swap the module in `~/.config/waybar/config.jsonc` and add its CSS to `style.css`. The riskiest change (the `image#radioart` module, which can freeze waybar 0.15.0 if misconfigured) is deliberately deferred to its own task so it can be isolated and reverted independently. A Hyprland hotkey lands last.

**Tech Stack:** waybar 0.15.0, Hyprland, omarchy, Python 3 (stdlib only), mpv, playerctl, walker, grim.

Spec: `docs/superpowers/specs/2026-07-29-waybar-radiobar-migration-design.md`

## Global Constraints

- **`"interval": "once"` on `image#radioart` is mandatory.** waybar 0.15.0 clamps a missing `interval` to 1ms → ~1000 jpg reloads/sec, ~50% CPU, and a module-mutex deadlock that freezes the whole bar. Never omit it.
- **`#custom-radio`'s font must be monospace and pinned explicitly by id.** `style.css` has `* { font-family: 'FiraCode Nerd Font'; }`, which matches the module's node directly; only the id selector's higher specificity beats it, so inheriting is not enough. Use `'FiraCode Nerd Font'` (verified `fc-match` spacing=100) — *not* the snippet's CaskaydiaMono. Do **not** add `#custom-radio label`: waybar's `ALabel` does `label_.set_name(name)`, so the node *is* `label#custom-radio` and a descendant selector matches nothing.
- **`custom/radio` goes at the END of `modules-left`.** Its free edge faces the empty bar center so no neighbor can jog the marquee.
- **`$XDG_RUNTIME_DIR` is `/run/user/1000`.** Art path is `/run/user/1000/radiobar-art.jpg`.
- **`size: 20` for the art** — bar `height` is 26; stay a few px under.
- **waybar does NOT auto-reload.** Every config change needs `omarchy restart waybar`.
- **waybar's stderr is unreadable on this system** — its transient scope logs nothing to the journal and Hyprland's log has no waybar lines. Verify health by process liveness + CPU-time delta, never by grepping logs.
- **Never edit anything under `~/.local/share/omarchy/`.** Reading is fine.
- **No per-task git commits.** Every deliverable in Tasks 1–4 lives in `~/.config` or `~/.local/bin`, outside this repo. The repo's only changes are this plan and the spec (`61544aa`).

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `~/.local/bin/radiobar` | symlink → `/home/eben/RadioBar/linux/radiobar`; puts the CLI on waybar's PATH | 1 |
| `~/.config/waybar/config.jsonc` | module list + `custom/radio` and `image#radioart` definitions | 2, 3 |
| `~/.config/waybar/style.css` | `#custom-radio` padding, monospace font pin, playing/paused/idle states | 2 |
| `~/.config/hypr/bindings.conf` | `SUPER SHIFT R` → `radiobar toggle` | 4 |
| `~/.config/waybar/scripts/mpris-scroll.py` | **left untouched** — the rollback path | — |

There is no code to test, so each task's gate is a verification command whose expected output is stated, rather than a TDD cycle. Task 1 does run the repo's existing suite.

---

### Task 1: Preflight and install the `radiobar` symlink

**Files:**
- Create: `~/.local/bin/radiobar` (symlink)
- Backup: `~/.config/waybar/config.jsonc`, `~/.config/waybar/style.css`, `~/.config/hypr/bindings.conf`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `radiobar` on PATH. Tasks 2–4 invoke the subcommands `radiobar status`, `radiobar click`, `radiobar prev`, `radiobar menu`, and `radiobar toggle`. Backup files that Task 2/3/4 rollback steps restore.

- [ ] **Step 1: Confirm the repo suite is green before changing anything**

```bash
cd /home/eben/.local/state/wsx/worktrees/RadioBar/smug-thyme
uv run --with pytest pytest linux/test_radiobar.py -q
```

`python -m pytest` does NOT work here — pytest is not installed system-wide
and there is no venv, so it fails with `No module named pytest`.

Expected: all tests pass, exit 0. If anything fails, STOP — do not install a broken script into a live bar. Report the failure.

- [ ] **Step 2: Take timestamped backups of all three files this plan will edit**

```bash
TS=$(date +%s)
cp ~/.config/waybar/config.jsonc   ~/.config/waybar/config.jsonc.bak.$TS
cp ~/.config/waybar/style.css      ~/.config/waybar/style.css.bak.$TS
cp ~/.config/hypr/bindings.conf    ~/.config/hypr/bindings.conf.bak.$TS
echo "backup suffix: .bak.$TS"
```

Expected: three files created. Record the printed `$TS` value — later rollback steps refer to it.

- [ ] **Step 3: Record the waybar CPU-time baseline**

```bash
WB_UNIT=$(basename "$(cut -d: -f3 /proc/$(pgrep -x waybar)/cgroup)")
echo "unit=$WB_UNIT"
systemctl --user show -p CPUUsageNSec --value "$WB_UNIT"
```

Expected: a unit name like `app-Hyprland-waybar-ef928331.scope` and a nanosecond counter. This is the freeze-bug detector's zero point. Note that the unit name is **regenerated on every waybar restart**, so re-derive `WB_UNIT` after each restart rather than reusing it.

- [ ] **Step 4: Create the symlink**

```bash
ln -sfn /home/eben/RadioBar/linux/radiobar ~/.local/bin/radiobar
ls -l ~/.local/bin/radiobar
```

Expected: `~/.local/bin/radiobar -> /home/eben/RadioBar/linux/radiobar`. No `chmod` is needed — the target is already `+x` with a `#!/usr/bin/env python3` shebang.

- [ ] **Step 5: Verify the CLI resolves and emits valid waybar JSON**

Because waybar's stderr is invisible on this system, this is the only place a script-level error will be visible. Do not skip it.

```bash
timeout 5 radiobar status | head -3
```

Expected: one or more lines of JSON, each with at least a `text` key (likely `"class": "idle"` and a dim `󰐹`, since nothing is playing yet). A Python traceback or "command not found" here means STOP and fix before touching waybar.

- [ ] **Step 6: Confirm `stations.json` is absent — seeding is lazy, by design**

```bash
ls -l ~/.config/radiobar/stations.json 2>&1 || echo "absent as expected — seeded lazily"
```

Expected: the file does **not** exist yet. `load_stations()` (`linux/radiobar:116`) is called only by `cmd_toggle`, `cmd_play`, and `cmd_menu` — never by `cmd_status` — so `radiobar status` does not and should not create it. The station list is only needed once you actually start or select a station.

Nothing in Tasks 2–4 requires it to pre-exist: Task 2 exercises `radiobar status` only, and Task 3 Step 6's `radiobar toggle` is what seeds it. If the file *does* already exist here, that is also fine — it just means a station command ran earlier.

- [ ] **Step 7: No commit**

Nothing in this task touches the repo. Do not create a commit.

---

### Task 2: Swap `custom/mpris` for `custom/radio` (text module + CSS)

Art is deliberately **not** added here — Task 3 adds it separately so the freeze risk is isolated.

**Files:**
- Modify: `~/.config/waybar/config.jsonc` — line 8 (`modules-left`), lines 192–210 (`mpris` block), lines 211–217 (`custom/mpris` block)
- Modify: `~/.config/waybar/style.css` — append at end

**Interfaces:**
- Consumes: `radiobar` on PATH from Task 1; the `.bak.$TS` files from Task 1 Step 2.
- Produces: a live `custom/radio` module at the end of `modules-left`, styled with classes `playing` / `paused` / `idle`. Task 3 inserts `image#radioart` immediately before `custom/radio` in that same array.

- [ ] **Step 1: Replace the `modules-left` array (line 8)**

Find:

```jsonc
  "modules-left": ["custom/omarchy", "hyprland/workspaces#main", "hyprland/workspaces#special", "custom/mpris"],
```

Replace with:

```jsonc
  "modules-left": ["custom/omarchy", "hyprland/workspaces#main", "hyprland/workspaces#special", "custom/radio"],
```

- [ ] **Step 2: Replace both mpris module definitions with `custom/radio`**

Find this whole run (lines 192–217 — the `mpris` block is dead config, referenced by no `modules-*` array):

```jsonc
  "mpris": {
    "format": "{player_icon} {status_icon} {artist} - {title}",
    "format-paused": "{player_icon} {status_icon} {artist} - {title}",
    "format-stopped": "{player_icon}",
    "title-len": 30,
    "artist-len": 20,
    "player-icons": {
        "default": "󰝚", // Play icon
        "spotify": "",
        "de.haeckerfelix.shortwave": "",
        "discord": ""
    },
    "status-icons": {
        "paused": "" // Pause icon
    },
    "on-click": "playerctl play-pause",
    "on-middle-click": "playerctl previous",
    "on-right-click": "playerctl next"
  },
  "custom/mpris": {
    "exec": "$HOME/.config/waybar/scripts/mpris-scroll.py",
    "return-type": "json",
    "on-click": "playerctl play-pause",
    "on-click-middle": "playerctl previous",
    "on-click-right": "playerctl next"
  },
```

Replace with:

```jsonc
  "custom/radio": {
    "exec": "radiobar status",
    "return-type": "json",
    "on-click": "radiobar click",
    "on-click-middle": "radiobar prev",
    "on-click-right": "radiobar menu",
    "tooltip": true
  },
```

Leave `~/.config/waybar/scripts/mpris-scroll.py` on disk — it is the rollback path.

- [ ] **Step 3: Append the CSS to `~/.config/waybar/style.css`**

```css

/* RadioBar — unified radio + MPRIS now-playing module. */
#custom-radio {
  padding: 0 10px;
}

#custom-radio {
  /* The marquee needs a monospace font: the scroll window is a fixed
     character count, so under a proportional font its pixel width varies
     each tick and the title's trailing edge jitters. FiraCode NF is already
     this bar's font and is spacing=100, so pinning it satisfies the
     constraint while matching neighboring modules.
     Pin by id, and do NOT add `#custom-radio label`: style.css's
     `* { font-family: ... }` matches this very node, and the id selector
     beats it on specificity. waybar's ALabel does `label_.set_name(name)`,
     so the node IS `label#custom-radio` — a descendant selector asks for a
     label inside a label and matches nothing. */
  font-family: 'FiraCode Nerd Font';
}

#custom-radio.playing {
  color: @foreground;
}

#custom-radio.paused,
#custom-radio.idle {
  opacity: 0.5;
}
```

`@foreground` is already in scope via the existing `@import "../omarchy/current/theme/waybar.css"` at line 1.

- [ ] **Step 4: Confirm no `mpris` references remain**

```bash
grep -n 'mpris' ~/.config/waybar/config.jsonc
```

Expected: **no output.** (`mpris-scroll.py` still exists on disk, but nothing in the config should point at it.)

- [ ] **Step 5: Restart waybar**

```bash
omarchy restart waybar
```

waybar does not auto-reload, so this is mandatory.

- [ ] **Step 6: Verify waybar survived the restart**

```bash
sleep 5
pgrep -x waybar || echo "WAYBAR DEAD — config is invalid"
```

Expected: a PID. If waybar is dead, the JSONC is malformed (likely a stray or missing comma from Step 2) — this is how an invalid config surfaces, since stderr is unreadable. Fix the config and restart; if you cannot, roll back with Step 9.

- [ ] **Step 7: Verify the module is actually running, not just present**

```bash
WB_UNIT=$(basename "$(cut -d: -f3 /proc/$(pgrep -x waybar)/cgroup)")
systemctl --user status "$WB_UNIT" --no-pager | grep -A6 CGroup
```

Expected: the cgroup lists `/usr/bin/waybar` plus a `python3 .../radiobar status` child, and **no** `mpris-scroll.py` child. A missing `radiobar` child means the `exec` never launched.

- [ ] **Step 8: Verify CPU is sane and screenshot the bar**

```bash
WB_UNIT=$(basename "$(cut -d: -f3 /proc/$(pgrep -x waybar)/cgroup)")
A=$(systemctl --user show -p CPUUsageNSec --value "$WB_UNIT"); sleep 20
B=$(systemctl --user show -p CPUUsageNSec --value "$WB_UNIT")
echo "CPU over 20s: $(( (B-A)/1000000 )) ms  → $(( (B-A)/200000000 ))% of one core"
grim -g "0,0 700x26" /tmp/bar-task2.png && echo wrote /tmp/bar-task2.png
```

Expected: well under 1000 ms of CPU over the 20s window (i.e. <5% of a core). The screenshot should show the module at the end of `modules-left` with a colored icon and title, glyphs matching neighboring modules, and no clipping. Start playing something (Spotify or a radio station via right-click) and re-shoot to confirm the marquee scrolls without shifting the module's left edge.

- [ ] **Step 9: Rollback, only if needed**

```bash
cp ~/.config/waybar/config.jsonc.bak.$TS ~/.config/waybar/config.jsonc
cp ~/.config/waybar/style.css.bak.$TS    ~/.config/waybar/style.css
omarchy restart waybar
```

Restores the old `custom/mpris` module. `mpris-scroll.py` was never deleted, so this is sufficient.

- [ ] **Step 10: No commit**

Nothing in this task touches the repo. Do not create a commit.

---

### Task 3: Add the `image#radioart` album-art thumbnail

Isolated from Task 2 because this is the one change that can hang the bar. Only start it once Task 2 is verified green.

**Files:**
- Modify: `~/.config/waybar/config.jsonc` — `modules-left` array and the module definitions

**Interfaces:**
- Consumes: the working `custom/radio` module from Task 2.
- Produces: a 20px thumbnail at `/run/user/1000/radiobar-art.jpg`, refreshed by `SIGRTMIN+6`, immediately left of `custom/radio`.

- [ ] **Step 1: Insert `image#radioart` into `modules-left`, immediately before `custom/radio`**

Find:

```jsonc
  "modules-left": ["custom/omarchy", "hyprland/workspaces#main", "hyprland/workspaces#special", "custom/radio"],
```

Replace with:

```jsonc
  "modules-left": ["custom/omarchy", "hyprland/workspaces#main", "hyprland/workspaces#special", "image#radioart", "custom/radio"],
```

- [ ] **Step 2: Add the module definition next to `custom/radio`**

Find:

```jsonc
  "custom/radio": {
    "exec": "radiobar status",
    "return-type": "json",
    "on-click": "radiobar click",
    "on-click-middle": "radiobar prev",
    "on-click-right": "radiobar menu",
    "tooltip": true
  },
```

Replace with:

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
    // "once" is load-bearing, do NOT omit it: waybar 0.15.0 clamps a missing
    // interval to 1ms, so this module would reload the jpg ~1000x/s — ~50% CPU
    // and enough dispatcher traffic to trigger waybar's freeze deadlock.
    // RadioBar's `pkill -RTMIN+6 waybar` still refreshes art on track changes.
    "interval": "once",
    "tooltip": false
  },
```

- [ ] **Step 3: Verify `interval` is present before restarting**

```bash
python3 - <<'PY'
import re
src = open('/home/eben/.config/waybar/config.jsonc').read()
blk = re.search(r'"image#radioart"\s*:\s*\{.*?\n  \}', src, re.S)
assert blk, 'image#radioart block not found'
assert '"interval": "once"' in blk.group(0), 'MISSING interval:once — DO NOT RESTART WAYBAR'
print('OK: interval:once present')
PY
```

Expected: `OK: interval:once present`. If this asserts, fix it before restarting — restarting without it can freeze the bar.

- [ ] **Step 4: Restart waybar**

```bash
omarchy restart waybar
sleep 5
pgrep -x waybar || echo "WAYBAR DEAD — config is invalid"
```

Expected: a PID.

- [ ] **Step 5: Verify CPU did not spike — the freeze-bug gate**

```bash
WB_UNIT=$(basename "$(cut -d: -f3 /proc/$(pgrep -x waybar)/cgroup)")
A=$(systemctl --user show -p CPUUsageNSec --value "$WB_UNIT"); sleep 20
B=$(systemctl --user show -p CPUUsageNSec --value "$WB_UNIT")
echo "CPU over 20s: $(( (B-A)/1000000 )) ms  → $(( (B-A)/200000000 ))% of one core"
```

Expected: comparable to Task 2 Step 8 — well under 1000 ms / 5% of a core. **Anything approaching 50% of a core means the `interval` guard failed;** roll back immediately with Step 8.

- [ ] **Step 6: Verify art actually appears on a track change**

```bash
# Start a station, then check the art file lands and the bar picks it up.
radiobar toggle
sleep 15
# This is also the first station command to run, so it seeds stations.json
# (Task 1 deliberately did not — `radiobar status` never touches stations).
ls -l ~/.config/radiobar/stations.json && python3 -c "import json;print(len(json.load(open('$HOME/.config/radiobar/stations.json'))),'stations seeded')"
ls -l /run/user/1000/radiobar-art.jpg && file /run/user/1000/radiobar-art.jpg
grim -g "0,0 700x26" /tmp/bar-task3.png && echo wrote /tmp/bar-task3.png
```

Expected: a JPEG exists (radio art comes from the iTunes Search API, so it appears only once a track with a matched artist/title is playing; a station whose ICY metadata is just the station name will not produce art). The screenshot should show a 20px thumbnail left of the title with clearance from the bar edges. Also try Spotify to exercise the `mpris:artUrl` path.

Add **no** CSS for this module for now. `#workspaces.special`'s existing `padding-right: 10px` plus `#custom-radio`'s left padding already frame the thumbnail. If the screenshot shows it cramped against a neighbor, add a `#image.radioart { margin: 0 4px; }` rule then — note the selector is `#image.radioart`, not `#image-radioart`, because waybar sets the id from the module type and the post-`#` name becomes a style class.

- [ ] **Step 7: Verify `radiobar stop` clears the thumbnail**

```bash
radiobar stop
sleep 3
ls -l /run/user/1000/radiobar-art.jpg 2>&1 || echo "art cleared as expected"
grim -g "0,0 700x26" /tmp/bar-task3-stopped.png
```

Expected: the art file is gone or empty and the thumbnail has disappeared from the bar (RadioBar clears the file and re-signals waybar).

- [ ] **Step 8: Rollback, only if needed**

```bash
cp ~/.config/waybar/config.jsonc.bak.$TS ~/.config/waybar/config.jsonc
cp ~/.config/waybar/style.css.bak.$TS    ~/.config/waybar/style.css
omarchy restart waybar
```

Note this reverts Task 2 as well, since both edited the same file. To keep Task 2 and drop only the art, instead remove `"image#radioart"` from `modules-left` and delete its definition, then restart.

- [ ] **Step 9: No commit**

Nothing in this task touches the repo. Do not create a commit.

---

### Task 4: Add the `SUPER SHIFT R` play/pause hotkey

**Files:**
- Modify: `~/.config/hypr/bindings.conf`

**Interfaces:**
- Consumes: `radiobar` on PATH from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Re-confirm `SUPER SHIFT R` is still unbound**

```bash
grep -n 'SUPER SHIFT, R,' ~/.config/hypr/bindings.conf; echo "exit=$?"
omarchy menu keybindings --print 2>/dev/null | grep -i 'SUPER SHIFT R' || echo "no SUPER SHIFT R binding found"
```

Expected: no match. As of 2026-07-29 the nearest neighbors were `SUPER CTRL R` (reminders) and `SUPER SHIFT M` (Spotify) — neither collides. If a match now exists, add an `unbind = SUPER SHIFT, R` line before the new bind and tell the user what it displaced. (Note the modifiers: `unbind = SUPER, R` would target a different, unrelated keybind.)

- [ ] **Step 2: Append the binding**

Add to `~/.config/hypr/bindings.conf`, alongside the other `SUPER SHIFT` app bindings:

```
bindd = SUPER SHIFT, R, RadioBar play/pause, exec, radiobar toggle
```

`bindd` (not `bind`) is the omarchy convention — the third field is the description shown in the keybindings menu.

- [ ] **Step 3: Reload Hyprland and check for config errors**

```bash
hyprctl reload
hyprctl configerrors
```

Expected: `configerrors` reports no errors. Hyprland auto-reloads on save, but reload explicitly and confirm.

- [ ] **Step 4: Verify the binding registered**

```bash
hyprctl binds | grep -B2 -A2 'radiobar toggle' || echo "BINDING NOT REGISTERED"
```

Expected: a bind entry with `radiobar toggle` as its dispatcher argument. Then press `SUPER SHIFT R` and confirm the bar's play/pause state flips.

- [ ] **Step 5: Rollback, only if needed**

```bash
cp ~/.config/hypr/bindings.conf.bak.$TS ~/.config/hypr/bindings.conf
hyprctl reload
```

- [ ] **Step 6: No commit**

Nothing in this task touches the repo. Do not create a commit.

---

## Post-implementation

Report to the user:

- The verified CPU-time deltas from Task 2 Step 8 and Task 3 Step 5, next to the pre-migration baseline from Task 1 Step 3.
- The `.bak.$TS` suffix, so they know their rollback point.
- That `mpris-scroll.py` is still on disk and unreferenced.
- The screenshots written to `/tmp/bar-task*.png`.
- Anything that could not be verified — in particular, radio album art only appears for stations whose ICY metadata yields an iTunes match, so a negative result there is not necessarily a defect.

## Deferred (do not do unless asked)

- Pruning the 6 pre-existing `config.jsonc.bak.*` files.
- Updating `linux/README.md` with the two findings from this migration: that a reader whose bar font is already monospace can pin *that* font rather than CaskaydiaMono, and that a symlink install is an option when working from a checkout.
- Any change to `linux/radiobar`. No defect was found.
