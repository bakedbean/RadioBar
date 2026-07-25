# Unified Now-Playing Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the standalone waybar MPRIS module (`~/.config/waybar/scripts/mpris-scroll.py`) into `linux/radiobar` so one bar slot shows whatever is audible — radio or any MPRIS player — with a one-audible-source guard, scrolling colored titles, unified album art, and notifications.

**Architecture:** `radiobar status` becomes a three-thread engine: a radio watcher (existing mpv IPC), an MPRIS watcher (one long-lived `playerctl --all-players --follow` subprocess), and a render loop. Watchers push into a lock-protected `StateStore`; the render loop runs a pure `arbiter` (Playing beats Paused, recency tie-break), executes the edge-triggered guard, renders via a scroll/color `Renderer`, and on track-identity change kicks the `ArtworkWorker`, notification, and an active-source file that the new `click`/`prev`/`next` subcommands read.

**Tech Stack:** Python 3 stdlib only; `pytest` for tests; runtime binaries: `mpv`, `playerctl` (graceful absence), optional `magick`/`convert`/`ffmpeg` for MPRIS art downscaling, `notify-send`, `walker`/`fuzzel`.

**Spec:** `docs/superpowers/specs/2026-07-25-unified-now-playing-design.md` — read it before starting.

## Global Constraints

- Python stdlib only — no pip dependencies. Everything lives in the single file `linux/radiobar` (extensionless, loaded by tests via `SourceFileLoader`).
- Never publish an image larger than 128 px to the bar (waybar 0.15 image module hangs the whole bar on ~600 px images). When in doubt, publish nothing.
- Event-driven: no polling loops. The only timed wakeup is the 100 ms scroll tick, and only while the visible text overflows the 30-char window.
- RadioBar may *pause* other apps (`playerctl ... pause`), never stop/quit them.
- Scroll window `SCROLL_WINDOW = 30`; pad `SCROLL_PAD = "   •   "` (7 chars); `PAUSE_TICKS = 10` (1 s at `TICK_SECONDS = 0.1`).
- Tests run with: `python -m pytest linux/test_radiobar.py -v` from the repo root. All tests must pass at every commit.
- Injected dependencies for testability (`run=subprocess.run`, `urlopen=`, `which=`, `popen=`, `sleep=`) — follow the existing style in `linux/radiobar`.
- Conventional commits, `feat(linux):` / `refactor(linux):` / `docs:` prefixes.

---

### Task 1: playerctl line parsing

**Files:**
- Modify: `linux/radiobar` (new pure function near `pick_title`)
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_playerctl_line(line: str) -> tuple[str, dict|None] | None`.
  Returns `None` for unusable lines (blank, wrong field count, empty player
  name). Returns `(player_name, None)` when the player should be **dropped**
  (status not Playing/Paused — i.e. Stopped, cleared, or vanished). Otherwise
  `(player_name, {"status": "Playing"|"Paused", "artist": str|None,
  "title": str|None, "art_url": str|None})`. Also the constant
  `PLAYERCTL_FORMAT = "{{playerName}}\t{{status}}\t{{artist}}\t{{title}}\t{{mpris:artUrl}}"`.

- [ ] **Step 1: Write the failing tests**

Append to `linux/test_radiobar.py`:

```python
class TestParsePlayerctlLine:
    def test_playing_line(self):
        line = "spotify\tPlaying\tAir\tLa Femme d'Argent\thttps://i.scdn.co/image/x\n"
        name, state = rb.parse_playerctl_line(line)
        assert name == "spotify"
        assert state == {"status": "Playing", "artist": "Air",
                         "title": "La Femme d'Argent",
                         "art_url": "https://i.scdn.co/image/x"}

    def test_empty_fields_become_none(self):
        name, state = rb.parse_playerctl_line("firefox\tPaused\t\tSome Video\t\n")
        assert name == "firefox"
        assert state == {"status": "Paused", "artist": None,
                         "title": "Some Video", "art_url": None}

    def test_blank_line_is_ignored(self):
        assert rb.parse_playerctl_line("\n") is None
        assert rb.parse_playerctl_line("   \n") is None

    def test_wrong_field_count_is_ignored(self):
        assert rb.parse_playerctl_line("garbage line\n") is None
        assert rb.parse_playerctl_line("a\tb\tc\n") is None

    def test_stopped_or_cleared_status_drops_player(self):
        assert rb.parse_playerctl_line("spotify\tStopped\t\t\t\n") == ("spotify", None)
        assert rb.parse_playerctl_line("spotify\t\t\t\t\n") == ("spotify", None)

    def test_empty_player_name_is_ignored(self):
        assert rb.parse_playerctl_line("\tPlaying\tA\tT\t\n") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestParsePlayerctlLine -v`
Expected: FAIL / ERROR with `AttributeError: ... 'parse_playerctl_line'`

- [ ] **Step 3: Implement**

In `linux/radiobar`, after `pick_title`:

```python
PLAYERCTL_FORMAT = ("{{playerName}}\t{{status}}\t{{artist}}\t{{title}}"
                    "\t{{mpris:artUrl}}")


def parse_playerctl_line(line: str):
    """One playerctl --follow line -> (player, state) | (player, None) | None.

    (player, None) means the player vanished or stopped and must be dropped.
    None means the line is unusable and should be skipped entirely.
    """
    line = line.rstrip("\n")
    if not line.strip():
        return None
    parts = line.split("\t")
    if len(parts) != 5 or not parts[0]:
        return None
    name, status, artist, title, art_url = parts
    if status not in ("Playing", "Paused"):
        return (name, None)
    return (name, {"status": status, "artist": artist or None,
                   "title": title or None, "art_url": art_url or None})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: all PASS (new and existing).

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): parse playerctl --follow metadata lines"
```

---

### Task 2: StateStore

**Files:**
- Modify: `linux/radiobar`
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Consumes: `parse_playerctl_line` output shape (Task 1).
- Produces: `class StateStore` with:
  - `set_radio(state: dict)` — replaces radio state, stamps `state["seq"]`
    with a monotonically increasing int, sets the change event. Callers pass
    either `{"running": False}` or the dict from `StatusTracker.state()`
    (Task 7): `{"running": True, "paused": bool, "icy": str|None,
    "media": str|None, "station": str}`.
  - `update_player(name: str, state: dict|None)` — `None` drops the player;
    a dict is stored with a stamped `seq`. Sets the change event.
  - `snapshot() -> (radio: dict, players: dict[str, dict])` — deep-enough
    copies safe to read without the lock.
  - `changed: threading.Event` — set on every mutation.

- [ ] **Step 1: Write the failing tests**

```python
class TestStateStore:
    def test_initial_snapshot_is_idle(self):
        store = rb.StateStore()
        radio, players = store.snapshot()
        assert radio == {"running": False} and players == {}

    def test_set_radio_stamps_increasing_seq_and_sets_event(self):
        store = rb.StateStore()
        store.set_radio({"running": True, "paused": False, "icy": None,
                         "media": None, "station": "FIP"})
        assert store.changed.is_set()
        radio1, _ = store.snapshot()
        store.set_radio({"running": True, "paused": True, "icy": None,
                         "media": None, "station": "FIP"})
        radio2, _ = store.snapshot()
        assert radio2["seq"] > radio1["seq"]

    def test_update_and_drop_player(self):
        store = rb.StateStore()
        store.update_player("spotify", {"status": "Playing", "artist": "A",
                                        "title": "T", "art_url": None})
        _, players = store.snapshot()
        assert players["spotify"]["status"] == "Playing"
        assert "seq" in players["spotify"]
        store.update_player("spotify", None)
        _, players = store.snapshot()
        assert players == {}

    def test_player_seq_advances_across_updates(self):
        store = rb.StateStore()
        store.update_player("spotify", {"status": "Paused", "artist": None,
                                        "title": "T", "art_url": None})
        store.update_player("firefox", {"status": "Playing", "artist": None,
                                        "title": "V", "art_url": None})
        _, players = store.snapshot()
        assert players["firefox"]["seq"] > players["spotify"]["seq"]

    def test_snapshot_is_a_copy(self):
        store = rb.StateStore()
        store.update_player("spotify", {"status": "Playing", "artist": None,
                                        "title": "T", "art_url": None})
        _, players = store.snapshot()
        players["spotify"]["status"] = "Paused"
        _, players2 = store.snapshot()
        assert players2["spotify"]["status"] == "Playing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestStateStore -v`
Expected: FAIL with `AttributeError: ... 'StateStore'`

- [ ] **Step 3: Implement**

```python
class StateStore:
    """Thread-safe holder for radio + MPRIS player state.

    Watcher threads mutate it; the render loop reads snapshots. Every
    mutation stamps a monotonic seq (recency for the arbiter tie-break —
    deliberately not wall-clock) and sets `changed`.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.changed = threading.Event()
        self._radio = {"running": False}
        self._players = {}
        self._seq = 0

    def set_radio(self, state: dict):
        with self._lock:
            self._seq += 1
            s = dict(state)
            s["seq"] = self._seq
            self._radio = s
        self.changed.set()

    def update_player(self, name: str, state):
        with self._lock:
            if state is None:
                self._players.pop(name, None)
            else:
                self._seq += 1
                s = dict(state)
                s["seq"] = self._seq
                self._players[name] = s
        self.changed.set()

    def snapshot(self):
        with self._lock:
            return (dict(self._radio),
                    {k: dict(v) for k, v in self._players.items()})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): thread-safe StateStore for radio + MPRIS state"
```

---

### Task 3: arbiter

**Files:**
- Modify: `linux/radiobar`
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Consumes: radio dict (`StateStore.set_radio` shape incl. `seq`), players
  dict (`StateStore` shape incl. `seq`), `pick_title` (existing).
- Produces: `arbiter(radio: dict, players: dict) -> dict` returning the
  **active** dict used by every later task:
  `{"source": "radio"|"mpris"|"idle", "player": str|None, "playing": bool,
  "artist": str|None, "title": str|None, "art_url": str|None,
  "station": str|None}`. For radio, `title` is the `pick_title` result and
  `artist` is `None`. Idle: everything None/False except `source`.

- [ ] **Step 1: Write the failing tests**

```python
def _radio(playing=True, icy="A - B", station="FIP", seq=1):
    return {"running": True, "paused": not playing, "icy": icy,
            "media": None, "station": station, "seq": seq}


def _player(status="Playing", artist="Ar", title="Ti", art_url=None, seq=1):
    return {"status": status, "artist": artist, "title": title,
            "art_url": art_url, "seq": seq}


class TestArbiter:
    def test_idle_when_nothing(self):
        active = rb.arbiter({"running": False}, {})
        assert active["source"] == "idle" and active["playing"] is False

    def test_playing_radio_beats_paused_player(self):
        active = rb.arbiter(_radio(playing=True, seq=1),
                            {"spotify": _player("Paused", seq=9)})
        assert active["source"] == "radio" and active["playing"] is True
        assert active["title"] == "A - B" and active["station"] == "FIP"

    def test_playing_player_beats_paused_radio(self):
        active = rb.arbiter(_radio(playing=False, seq=9),
                            {"spotify": _player("Playing", seq=1)})
        assert active["source"] == "mpris" and active["player"] == "spotify"
        assert active["artist"] == "Ar" and active["title"] == "Ti"

    def test_recency_breaks_playing_tie(self):
        active = rb.arbiter(_radio(playing=True, seq=5),
                            {"spotify": _player("Playing", seq=7)})
        assert active["source"] == "mpris"
        active = rb.arbiter(_radio(playing=True, seq=8),
                            {"spotify": _player("Playing", seq=7)})
        assert active["source"] == "radio"

    def test_mpv_player_ignored_while_radio_runs(self):
        active = rb.arbiter(_radio(playing=True, seq=1),
                            {"mpv": _player("Playing", seq=9)})
        assert active["source"] == "radio"

    def test_mpv_player_shown_when_radio_stopped(self):
        active = rb.arbiter({"running": False},
                            {"mpv": _player("Playing", title="Some Film")})
        assert active["source"] == "mpris" and active["player"] == "mpv"

    def test_titleless_player_ignored(self):
        active = rb.arbiter({"running": False},
                            {"spotify": _player(title=None)})
        assert active["source"] == "idle"

    def test_paused_players_recency(self):
        active = rb.arbiter({"running": False},
                            {"spotify": _player("Paused", seq=2),
                             "firefox": _player("Paused", title="V", seq=5)})
        assert active["player"] == "firefox"

    def test_radio_title_uses_pick_title_fallback(self):
        active = rb.arbiter(_radio(icy=None), {})
        assert active["title"] == "FIP"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestArbiter -v`
Expected: FAIL with `AttributeError: ... 'arbiter'`

- [ ] **Step 3: Implement**

```python
IDLE_ACTIVE = {"source": "idle", "player": None, "playing": False,
               "artist": None, "title": None, "art_url": None,
               "station": None}


def arbiter(radio: dict, players: dict) -> dict:
    """Pick the active source: Playing beats Paused, then recency (seq)."""
    candidates = []
    if radio.get("running"):
        candidates.append({
            "source": "radio", "player": None,
            "playing": not radio.get("paused"),
            "artist": None,
            "title": pick_title(radio.get("icy"), radio.get("media"),
                                radio.get("station", "")),
            "art_url": None, "station": radio.get("station", ""),
            "seq": radio.get("seq", 0),
        })
    for name, p in players.items():
        if radio.get("running") and name.startswith("mpv"):
            continue
        if not p.get("title"):
            continue
        candidates.append({
            "source": "mpris", "player": name,
            "playing": p["status"] == "Playing",
            "artist": p.get("artist"), "title": p["title"],
            "art_url": p.get("art_url"), "station": None,
            "seq": p.get("seq", 0),
        })
    if not candidates:
        return dict(IDLE_ACTIVE)
    best = max(candidates, key=lambda c: (c["playing"], c["seq"]))
    best.pop("seq")
    return best
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): arbiter picks the audible source across radio and MPRIS"
```

---

### Task 4: one-audible-source guard detector

**Files:**
- Modify: `linux/radiobar`
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Consumes: players dicts (Task 2 shape).
- Produces: `guard_action(prev_players: dict, players: dict,
  radio_playing: bool) -> bool` — pure, edge-triggered: True only when some
  non-`mpv*` player *transitioned into* `Playing` while radio is playing.
  The caller (render loop, Task 9) executes the verdict by pausing mpv.

- [ ] **Step 1: Write the failing tests**

```python
class TestGuardAction:
    def test_new_playing_player_while_radio_plays_fires(self):
        assert rb.guard_action({}, {"spotify": _player("Playing")}, True) is True

    def test_transition_paused_to_playing_fires(self):
        assert rb.guard_action({"spotify": _player("Paused")},
                               {"spotify": _player("Playing")}, True) is True

    def test_level_state_does_not_fire(self):
        # already Playing in prev — no edge, no fire (can't fight a user
        # who resumes radio while spotify is left playing)
        assert rb.guard_action({"spotify": _player("Playing")},
                               {"spotify": _player("Playing")}, True) is False

    def test_radio_not_playing_never_fires(self):
        assert rb.guard_action({}, {"spotify": _player("Playing")}, False) is False

    def test_mpv_player_never_fires(self):
        # radio's own mpv seen through mpv-mpris must not pause radio
        assert rb.guard_action({}, {"mpv": _player("Playing")}, True) is False

    def test_paused_player_does_not_fire(self):
        assert rb.guard_action({}, {"spotify": _player("Paused")}, True) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestGuardAction -v`
Expected: FAIL with `AttributeError: ... 'guard_action'`

- [ ] **Step 3: Implement**

```python
def guard_action(prev_players: dict, players: dict,
                 radio_playing: bool) -> bool:
    """Edge-triggered: did some player just start playing over the radio?"""
    if not radio_playing:
        return False
    for name, p in players.items():
        if name.startswith("mpv"):
            continue
        if p.get("status") != "Playing":
            continue
        prev = prev_players.get(name)
        if prev is None or prev.get("status") != "Playing":
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): edge-triggered one-audible-source guard detector"
```

---

### Task 5: Renderer (scroll, colors, icons)

**Files:**
- Modify: `linux/radiobar` (port scroll/color/icon logic from
  `~/.config/waybar/scripts/mpris-scroll.py`; add `import html` and
  `import random` to the imports block)
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Consumes: active dict (Task 3), `ICON_PLAY`/`ICON_PAUSE`/`ICON_IDLE`
  (existing).
- Produces:
  - Constants: `SCROLL_WINDOW = 30`, `SCROLL_PAD = "   •   "`,
    `PAUSE_TICKS = 10`, `TICK_SECONDS = 0.1`, `COLORS` (the 20-color list
    from mpris-scroll.py), `PLAYER_ICONS`, `ICON_MPRIS_DEFAULT = "󰝚"`,
    `ICON_MPRIS_PAUSED = ""`.
  - `scroll_window(text: str, width: int, offset: int) -> str` — pure.
  - `player_icon(name: str|None) -> str` — pure.
  - `mpris_display_title(active: dict) -> str` — `"Artist - Title"` or
    bare title; also reused by Task 9 for the notification/art title.
  - `class Renderer` with `render(active: dict) -> dict` (waybar JSON dict;
    advances scroll one step per call while overflowing) and
    `needs_tick() -> bool`. Constructor takes `choose=random.choice` for
    deterministic tests.

- [ ] **Step 1: Write the failing tests**

```python
class TestScrollWindow:
    def test_wraps_with_pad(self):
        text = "0123456789"  # len 10, window 6
        assert rb.scroll_window(text, 6, 0) == "012345"
        # offset 8: chars 8,9 then the pad begins
        assert rb.scroll_window(text, 6, 8) == "89" + rb.SCROLL_PAD[:4]
        # offset wraps modulo len(text) + len(pad) = 17
        assert rb.scroll_window(text, 6, 17) == rb.scroll_window(text, 6, 0)


class TestPlayerIcon:
    def test_known_players(self):
        assert rb.player_icon("spotify") == rb.PLAYER_ICONS["spotify"]
        assert rb.player_icon("de.haeckerfelix.shortwave") == \
            rb.PLAYER_ICONS["de.haeckerfelix.shortwave"]

    def test_substring_match_and_fallback(self):
        assert rb.player_icon("spotify.instance42") == rb.PLAYER_ICONS["spotify"]
        assert rb.player_icon("firefox") == rb.ICON_MPRIS_DEFAULT
        assert rb.player_icon(None) == rb.ICON_MPRIS_DEFAULT


def _mpris_active(playing=True, artist="Ar", title="Ti", player="spotify"):
    return {"source": "mpris", "player": player, "playing": playing,
            "artist": artist, "title": title, "art_url": None,
            "station": None}


def _radio_active(playing=True, title="A - B", station="FIP"):
    return {"source": "radio", "player": None, "playing": playing,
            "artist": None, "title": title, "art_url": None,
            "station": station}


class TestRenderer:
    def _renderer(self):
        return rb.Renderer(choose=lambda colors: colors[0])

    def test_idle(self):
        out = self._renderer().render(dict(rb.IDLE_ACTIVE))
        assert out["class"] == "idle" and out["text"] == rb.ICON_IDLE

    def test_mpris_playing_has_icons_colors_and_tooltip(self):
        out = self._renderer().render(_mpris_active())
        assert out["class"] == "playing" and out["markup"] == "pango"
        assert rb.PLAYER_ICONS["spotify"] in out["text"]
        assert rb.COLORS[0] in out["text"]
        assert "Ar - Ti" in out["text"]
        assert out["tooltip"] == "Ar - Ti\nSpotify"

    def test_mpris_paused_appends_status_icon(self):
        out = self._renderer().render(_mpris_active(playing=False))
        assert out["class"] == "paused"
        assert rb.ICON_MPRIS_PAUSED in out["text"]

    def test_radio_uses_play_pause_icon_only(self):
        r = self._renderer()
        out = r.render(_radio_active(playing=True))
        assert rb.ICON_PLAY in out["text"] and out["class"] == "playing"
        assert rb.ICON_MPRIS_PAUSED not in out["text"]
        out = r.render(_radio_active(playing=False))
        assert rb.ICON_PAUSE in out["text"] and out["class"] == "paused"
        assert out["tooltip"] == "A - B\nFIP"

    def test_short_title_no_tick_needed(self):
        r = self._renderer()
        r.render(_mpris_active())
        assert r.needs_tick() is False

    def test_long_title_scrolls_after_pause(self):
        r = self._renderer()
        long = _mpris_active(artist=None, title="x" * 40 + "END")
        r.render(long)
        assert r.needs_tick() is True
        # first PAUSE_TICKS renders hold the window at offset 0
        first = r.render(long)["text"]
        for _ in range(rb.PAUSE_TICKS - 1):
            held = r.render(long)["text"]
        assert held == first
        moved = r.render(long)["text"]
        assert moved != first

    def test_track_change_resets_scroll_and_recolors(self):
        picks = iter(rb.COLORS)
        r = rb.Renderer(choose=lambda colors: next(picks))
        a = r.render(_mpris_active(title="x" * 40))
        b = r.render(_mpris_active(title="y" * 40))  # new track
        # colors advanced: 2 picks per track with our fake chooser
        assert rb.COLORS[0] in a["text"] and rb.COLORS[2] in b["text"]

    def test_pango_special_chars_escaped(self):
        out = self._renderer().render(
            _mpris_active(artist="Simon & Garfunkel", title="<Sound>"))
        assert "&amp;" in out["text"] and "&lt;Sound&gt;" in out["text"]
        assert "Simon & Garfunkel" in out["tooltip"]  # tooltip unescaped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestScrollWindow linux/test_radiobar.py::TestPlayerIcon linux/test_radiobar.py::TestRenderer -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement**

Add `import html` and `import random` to the imports. Then:

```python
SCROLL_WINDOW = 30
SCROLL_PAD = "   •   "
PAUSE_TICKS = 10          # 1 s of hold at TICK_SECONDS per step
TICK_SECONDS = 0.1

COLORS = [
    "#F5C402", "#f4b8e4", "#99d1db", "#a6d189", "#8caaee",
    "#e5c890", "#ea999c", "#85c1dc", "#F57627", "#F74105",
    "#c6a0f6", "#7dc4e4", "#f0c6c6", "#b7bdf8", "#eed49f",
    "#f5a97f", "#91d7e3", "#cba6f7", "#fab387", "#94e2d5",
]

PLAYER_ICONS = {
    "spotify": "",
    "de.haeckerfelix.shortwave": "",
    "discord": "",
}
ICON_MPRIS_DEFAULT = "\U000f075a"  # 󰝚
ICON_MPRIS_PAUSED = ""


def scroll_window(text: str, width: int, offset: int) -> str:
    padded = text + SCROLL_PAD + text
    start = offset % (len(text) + len(SCROLL_PAD))
    return padded[start:start + width]


def player_icon(name) -> str:
    for key, icon in PLAYER_ICONS.items():
        if key in (name or "").lower():
            return icon
    return ICON_MPRIS_DEFAULT


def mpris_display_title(active: dict) -> str:
    if active.get("artist"):
        return f"{active['artist']} - {active['title']}"
    return active["title"]


class Renderer:
    """Folds active-source dicts into waybar JSON with scroll + colors.

    Holds scroll offset/hold state and the current track's color pair;
    render() advances the scroll one step per call while the body
    overflows SCROLL_WINDOW.
    """

    def __init__(self, choose=random.choice):
        self.choose = choose
        self.key = None
        self.offset = 0
        self.pause_ticks = 0
        self.icon_color = COLORS[0]
        self.text_color = COLORS[0]

    def render(self, active: dict) -> dict:
        if active["source"] == "idle":
            self.key = None
            return {"text": ICON_IDLE, "tooltip": "RadioBar: off",
                    "class": "idle"}
        if active["source"] == "radio":
            body, subtitle = active["title"], active["station"]
        else:
            body = mpris_display_title(active)
            subtitle = (active["player"] or "").capitalize()
        key = (active["source"], active["player"], body)
        if key != self.key:
            self.key = key
            self.offset = 0
            self.pause_ticks = PAUSE_TICKS
            self.icon_color = self.choose(COLORS)
            self.text_color = self.choose(COLORS)
        if len(body) > SCROLL_WINDOW:
            shown = scroll_window(body, SCROLL_WINDOW, self.offset)
            if self.pause_ticks > 0:
                self.pause_ticks -= 1
            else:
                self.offset += 1
                if self.offset >= len(body) + len(SCROLL_PAD):
                    self.offset = 0
                    self.pause_ticks = PAUSE_TICKS
        else:
            shown = body
        if active["source"] == "radio":
            icon = ICON_PLAY if active["playing"] else ICON_PAUSE
            status = ""
        else:
            icon = player_icon(active["player"])
            status = "" if active["playing"] else f" {ICON_MPRIS_PAUSED}"
        text = (f"<span foreground='{self.icon_color}'>{icon}</span>{status} "
                f"<span foreground='{self.text_color}'>"
                f"{html.escape(shown, quote=False)}</span>")
        return {"text": text, "tooltip": f"{body}\n{subtitle}",
                "class": "playing" if active["playing"] else "paused",
                "markup": "pango"}

    def needs_tick(self) -> bool:
        return self.key is not None and len(self.key[2]) > SCROLL_WINDOW
```

Note on the icon literals: copy the exact glyphs from
`~/.config/waybar/scripts/mpris-scroll.py` (``, ``, ``, `󰝚`, ``) —
the `\uf...` escapes above are placeholders for the same characters; pasting
the literal glyphs as mpris-scroll.py does is fine and preferred.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): scrolling colored renderer for the unified slot"
```

---

### Task 6: MPRIS album art + ArtworkWorker signature

**Files:**
- Modify: `linux/radiobar` (`fetch_track_art`, new `find_downscaler`,
  `fetch_mpris_art`; `ArtworkWorker.track_changed`)
- Test: `linux/test_radiobar.py` (new tests + update `TestArtworkWorker`
  and `TestWatchArtworkHook` fetch/track_changed signatures)

**Interfaces:**
- Consumes: existing cache helpers (`art_cache_paths`, `cached_track_info`,
  `store_track_info`), existing `publish_art`/`notify_track`.
- Produces:
  - `find_downscaler(which=shutil.which) -> callable|None`; the callable
    maps `(src: str, dst: str) -> list[str]` argv producing a ≤128 px `dst`.
  - `fetch_mpris_art(art_url, urlopen=..., run=..., which=...) -> dict`
    with the existing info shape `{"year": None, "found": bool,
    "jpg": str|None, "jpg_small": str|None}`; cache keyed by `art_url`.
    `jpg_small` is set **only** if a downscaler succeeded — this is the
    128 px bar-freeze guard.
  - `fetch_track_art(title, art_url=None, urlopen=...)` — `art_url=None`
    → existing iTunes path, unchanged; a string → `fetch_mpris_art`
    (empty/unknown scheme → miss).
  - `ArtworkWorker.track_changed(title, subtitle, art_url=None)` — third
    positional param; injected `fetch_fn` is now called as
    `fetch_fn(title, art_url)`. The existing `title == subtitle → clear`
    behavior is preserved (radio station-name fallback).

- [ ] **Step 1: Write the failing tests**

```python
class TestFindDownscaler:
    def test_prefers_magick_then_convert_then_ffmpeg(self):
        which = lambda n: "/usr/bin/" + n
        assert rb.find_downscaler(which)("in.jpg", "out.jpg")[0] == "magick"
        which = lambda n: None if n == "magick" else "/usr/bin/" + n
        assert rb.find_downscaler(which)("in.jpg", "out.jpg")[0] == "convert"
        which = lambda n: "/usr/bin/ffmpeg" if n == "ffmpeg" else None
        argv = rb.find_downscaler(which)("in.jpg", "out.jpg")
        assert argv[0] == "ffmpeg" and "out.jpg" in argv

    def test_none_when_no_tool(self):
        assert rb.find_downscaler(lambda n: None) is None


class TestFetchMprisArt:
    def _run_ok(self, calls):
        def run(argv, **kwargs):
            calls.append(argv)
            Path(argv[-1]).write_bytes(b"SMALL")

            class R:
                returncode = 0
            return R()
        return run

    def test_https_download_and_downscale(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        fake = _FakeHTTP({"i.scdn.co": b"BIGIMG"})
        calls = []
        info = rb.fetch_mpris_art("https://i.scdn.co/image/abc", urlopen=fake,
                                  run=self._run_ok(calls),
                                  which=lambda n: "/usr/bin/" + n)
        assert info["found"] and info["year"] is None
        assert Path(info["jpg"]).read_bytes() == b"BIGIMG"
        assert Path(info["jpg_small"]).read_bytes() == b"SMALL"
        assert calls and calls[0][0] == "magick"

    def test_no_downscaler_skips_bar_art_keeps_notification_art(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        fake = _FakeHTTP({"i.scdn.co": b"BIGIMG"})
        info = rb.fetch_mpris_art("https://i.scdn.co/image/abc", urlopen=fake,
                                  run=lambda *a, **k: None,
                                  which=lambda n: None)
        assert info["found"] and info["jpg"] is not None
        assert info["jpg_small"] is None  # never risk the waybar freeze

    def test_file_url_is_copied(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        src = tmp_path / "local art.jpg"
        src.write_bytes(b"LOCAL")
        url = "file://" + urllib.parse.quote(str(src))
        info = rb.fetch_mpris_art(url, urlopen=None,
                                  run=lambda *a, **k: None,
                                  which=lambda n: None)
        assert info["found"] and Path(info["jpg"]).read_bytes() == b"LOCAL"

    def test_unsupported_or_failed_is_cached_miss(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        info = rb.fetch_mpris_art("", urlopen=None,
                                  run=lambda *a, **k: None,
                                  which=lambda n: None)
        assert info == {"year": None, "found": False,
                        "jpg": None, "jpg_small": None}
        fake = _FakeHTTP({"i.scdn.co": OSError("down")})
        rb.fetch_mpris_art("https://i.scdn.co/x", urlopen=fake,
                           run=lambda *a, **k: None, which=lambda n: None)
        fake2 = _FakeHTTP({})
        again = rb.fetch_mpris_art("https://i.scdn.co/x", urlopen=fake2,
                                   run=lambda *a, **k: None,
                                   which=lambda n: None)
        assert again["found"] is False and fake2.calls == []

    def test_cached_hit_skips_network(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        fake = _FakeHTTP({"i.scdn.co": b"BIGIMG"})
        calls = []
        rb.fetch_mpris_art("https://i.scdn.co/image/abc", urlopen=fake,
                           run=self._run_ok(calls),
                           which=lambda n: "/usr/bin/" + n)
        fake2 = _FakeHTTP({})
        again = rb.fetch_mpris_art("https://i.scdn.co/image/abc",
                                   urlopen=fake2, run=lambda *a, **k: None,
                                   which=lambda n: None)
        assert again["found"] and fake2.calls == []


class TestFetchTrackArtDispatch:
    def test_none_art_url_uses_itunes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CACHE_DIR", str(tmp_path))
        fake = _FakeHTTP({"itunes.apple.com":
                          json.dumps({"results": []}).encode()})
        info = rb.fetch_track_art("A - B", urlopen=fake)
        assert info["found"] is False
        assert any("itunes.apple.com" in u for u in fake.calls)
```

Add `import urllib.parse` to the test file's imports (used by
`test_file_url_is_copied`).

Update **every** existing `TestArtworkWorker` fake `fetch_fn` from
`lambda t: ...` to `lambda t, art_url=None: ...`, and every
`w.track_changed("A - B", "FIP")` stays valid (subtitle == old station
param). Update `TestWatchArtworkHook.W.track_changed` to
`def track_changed(self, title, subtitle, art_url=None):`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: new classes FAIL with `AttributeError`; updated worker tests FAIL
with `TypeError` until the implementation changes.

- [ ] **Step 3: Implement**

```python
def find_downscaler(which=shutil.which):
    """Return an argv builder producing a <=128px copy, or None."""
    if which("magick"):
        return lambda src, dst: ["magick", src, "-resize", "128x128>", dst]
    if which("convert"):
        return lambda src, dst: ["convert", src, "-resize", "128x128>", dst]
    if which("ffmpeg"):
        return lambda src, dst: ["ffmpeg", "-y", "-loglevel", "error",
                                 "-i", src, "-vf", "scale=min(128\\,iw):-2",
                                 dst]
    return None


def fetch_mpris_art(art_url: str, urlopen=urllib.request.urlopen,
                    run=subprocess.run, which=shutil.which) -> dict:
    """Fetch MPRIS artUrl into the shared cache (keyed by URL).

    jpg_small is produced only via an external downscaler — waybar 0.15's
    image module hangs the bar on large images, so with no downscaler the
    bar art is skipped and only the notification gets the full image.
    """
    cached = cached_track_info(art_url)
    if cached is not None:
        return cached
    data = None
    if art_url.startswith(("http://", "https://")):
        try:
            with urlopen(art_url, timeout=10) as resp:
                data = resp.read()
        except (OSError, http.client.HTTPException):
            data = None
    elif art_url.startswith("file://"):
        try:
            path = urllib.parse.unquote(urllib.parse.urlparse(art_url).path)
            data = Path(path).read_bytes()
        except (OSError, ValueError):
            data = None
    if not data:
        store_track_info(art_url, year=None, image_data=None)
        return {"year": None, "found": False, "jpg": None, "jpg_small": None}
    store_track_info(art_url, year=None, image_data=data)
    jpg, jpg_small, _ = art_cache_paths(art_url)
    scaler = find_downscaler(which)
    small = None
    if scaler is not None:
        try:
            result = run(scaler(str(jpg), str(jpg_small)),
                         capture_output=True)
            if getattr(result, "returncode", 1) == 0 and jpg_small.exists():
                small = str(jpg_small)
        except OSError:
            small = None
    return {"year": None, "found": True, "jpg": str(jpg),
            "jpg_small": small}
```

`linux/radiobar` needs `from pathlib import Path` (already imported) and
`shutil` (already imported). Change `fetch_track_art`'s signature:

```python
def fetch_track_art(title: str, art_url=None,
                    urlopen=urllib.request.urlopen) -> dict:
```

with, as the first lines of the body:

```python
    if art_url is not None:
        return fetch_mpris_art(art_url, urlopen)
```

(the rest of the existing iTunes body is unchanged). In `ArtworkWorker`,
rename the `station` parameter and thread the URL through:

```python
    def track_changed(self, title, subtitle, art_url=None):
        if not title or title == subtitle:
            self.latest = None
            self.publish(None)
            return
        ...
            def job():
                try:
                    info = self.fetch(title, art_url)
                    ...
                    self.notify(title, subtitle, info.get("year"),
                                info.get("jpg"))
```

(keep the existing in-flight/latest logic exactly as it is — only the
parameter name and the two call sites change). The `watch()` call site
(`worker.track_changed(current, tracker.station)`) still type-checks with
the default `art_url=None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): MPRIS artUrl fetch with 128px downscale guard"
```

---

### Task 7: StatusTracker state dicts + watch feeds the store

**Files:**
- Modify: `linux/radiobar` (`StatusTracker`, `watch`)
- Test: `linux/test_radiobar.py` (update `TestStatusTracker`, `TestWatch`,
  remove `TestWatchArtworkHook` — the worker hook moves to Task 9's loop)

**Interfaces:**
- Consumes: `StateStore` (Task 2).
- Produces:
  - `StatusTracker.state() -> {"running": True, "paused": bool,
    "icy": str|None, "media": str|None, "station": str}`.
  - `StatusTracker.handle_event(ev) -> dict|None` now returns `state()`
    instead of a waybar dict.
  - `watch(sock, store)` — pushes `store.set_radio(tracker.state())` once
    at start and on every relevant event; raises `OSError` when the socket
    closes; no longer emits or takes a `worker`.

- [ ] **Step 1: Update the tests (they must fail first)**

Replace `TestStatusTracker` bodies to assert on state dicts:

```python
class TestStatusTracker:
    def test_initial_state(self):
        t = rb.StatusTracker("FIP")
        assert t.state() == {"running": True, "paused": False, "icy": None,
                             "media": None, "station": "FIP"}

    def test_icy_title_event_updates_state(self):
        t = rb.StatusTracker("FIP")
        out = t.handle_event({"event": "property-change",
                              "name": "metadata/by-key/icy-title",
                              "data": "Air - La Femme d'Argent"})
        assert out["icy"] == "Air - La Femme d'Argent"

    def test_pause_event_switches_state(self):
        t = rb.StatusTracker("FIP")
        out = t.handle_event({"event": "property-change",
                              "name": "pause", "data": True})
        assert out["paused"] is True
        out = t.handle_event({"event": "property-change",
                              "name": "pause", "data": False})
        assert out["paused"] is False

    def test_irrelevant_events_return_none(self):
        t = rb.StatusTracker("FIP")
        assert t.handle_event({"event": "playback-restart"}) is None
        assert t.handle_event({"request_id": 1, "error": "success"}) is None

    def test_null_icy_data_clears(self):
        t = rb.StatusTracker("FIP")
        t.handle_event({"event": "property-change",
                        "name": "metadata/by-key/icy-title", "data": "A - B"})
        out = t.handle_event({"event": "property-change",
                              "name": "metadata/by-key/icy-title",
                              "data": None})
        assert out["icy"] is None
```

Rewrite `TestWatch` so the fake-mpv server drives a real `StateStore`
(same server scaffolding as today, but assert on the store instead of
stdout, and drop `capsys`):

```python
class TestWatch:
    def test_observes_props_feeds_store_and_raises_on_close(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        rb.write_last("FIP")
        sock_path = tmp_path / "radiobar.sock"
        received = []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for _ in rb.OBSERVED_PROPS:
                    received.append(json.loads(self.rfile.readline()))
                ev = {"event": "property-change",
                      "name": "metadata/by-key/icy-title", "data": "A - B"}
                self.wfile.write(json.dumps(ev).encode() + b"\n")

        server = socketserver.UnixStreamServer(str(sock_path), Handler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        import socket as socket_mod
        client = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        client.connect(str(sock_path))
        store = rb.StateStore()
        try:
            import pytest
            with pytest.raises(OSError):
                rb.watch(client, store)
        finally:
            client.close()
            thread.join(timeout=5)
            server.server_close()
        assert [r["command"][2] for r in received] == rb.OBSERVED_PROPS
        radio, _ = store.snapshot()
        assert radio["running"] and radio["icy"] == "A - B"
        assert radio["station"] == "FIP"
```

Delete `TestWatchArtworkHook` entirely (Task 9 re-covers the behavior at
the render-loop level).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: updated tests FAIL (old return shapes / signature).

- [ ] **Step 3: Implement**

`StatusTracker`: replace `output()` with `state()`; `handle_event` returns
`self.state()` where it returned `self.output()`:

```python
    def state(self) -> dict:
        return {"running": True, "paused": self.paused, "icy": self.icy,
                "media": self.media, "station": self.station}
```

`watch` becomes:

```python
def watch(sock, store):
    """Observe mpv properties on an open socket; feed the store until close."""
    tracker = StatusTracker(read_last() or "")
    for i, prop in enumerate(OBSERVED_PROPS, start=1):
        sock.sendall(json.dumps({"command": ["observe_property", i, prop]})
                     .encode() + b"\n")
    store.set_radio(tracker.state())
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("mpv socket closed")
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            state = tracker.handle_event(ev)
            if state is not None:
                store.set_radio(state)
```

`cmd_status` still calls `watch(s, worker=worker)` at this point. To keep
this commit green and the bar functional, give `cmd_status` a minimal
bridge for this task only (Task 10 replaces it with the real render loop):
a store subclass that renders synchronously on every radio update:

```python
class _EmittingStore(StateStore):
    """Task-7 bridge: render radio updates synchronously until the full
    render loop lands (Task 9/10)."""

    def __init__(self, renderer, worker):
        super().__init__()
        self._renderer = renderer
        self._worker = worker
        self._last_title = None

    def set_radio(self, state):
        super().set_radio(state)
        radio, players = self.snapshot()
        active = arbiter(radio, players)
        emit(self._renderer.render(active))
        if active["source"] == "radio" and active["title"] != self._last_title:
            self._last_title = active["title"]
            self._worker.track_changed(active["title"], active["station"])


def cmd_status() -> int:
    renderer = Renderer()
    worker = ArtworkWorker()
    store = _EmittingStore(renderer, worker)
    while True:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(str(socket_path()))
        except OSError:
            s.close()
            emit(renderer.render(dict(IDLE_ACTIVE)))
            time.sleep(2)
            continue
        try:
            watch(s, store)
        except OSError:
            pass
        finally:
            s.close()
        worker.clear()
        emit(renderer.render(dict(IDLE_ACTIVE)))
        time.sleep(2)
```

`_EmittingStore` is scaffolding deleted in Task 10 — keep it adjacent to
`cmd_status` so its removal is obvious. Delete `waybar_output`, `truncate`,
`TITLE_LIMIT`, and their tests (`TestWaybarOutput`, `TestTruncate`) in this
task — nothing references them after this change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Manual smoke test (radio still works end-to-end)**

Run: `RADIOBAR_NO_NOTIFY=1 timeout 5 ./linux/radiobar status | head -3`
Expected: one JSON line per state (idle, or playing with pango markup if a
radio is running). No tracebacks.

- [ ] **Step 6: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "refactor(linux): StatusTracker/watch feed a StateStore; retire waybar_output"
```

---

### Task 8: active-source file + click/prev/next subcommands

**Files:**
- Modify: `linux/radiobar` (`active_path`, `write_active`, `read_active`,
  `cmd_click`, `cmd_prev`, `cmd_next`, `main`, `USAGE`)
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Consumes: active dict (Task 3), `cmd_toggle` (existing).
- Produces:
  - `active_path() -> Path` — `$RADIOBAR_ACTIVE_PATH` override, else
    `$XDG_RUNTIME_DIR/radiobar-active.json` (fallback `/tmp`).
  - `write_active(active: dict)` — atomically (tmp + `os.replace`) writes
    `{"source": ..., "player": ...}`; swallows `OSError`.
  - `read_active() -> dict|None`.
  - `cmd_click(run=subprocess.run) -> int`, `cmd_prev(run=...)`,
    `cmd_next(run=...)`; `main` dispatches `click`, `prev`, `next`;
    `USAGE` mentions them.

- [ ] **Step 1: Write the failing tests**

```python
class TestActiveFile:
    def test_roundtrip_only_source_and_player(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ACTIVE_PATH",
                           str(tmp_path / "active.json"))
        rb.write_active({"source": "mpris", "player": "spotify",
                         "playing": True, "title": "T"})
        assert rb.read_active() == {"source": "mpris", "player": "spotify"}

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_ACTIVE_PATH",
                           str(tmp_path / "absent.json"))
        assert rb.read_active() is None

    def test_corrupt_file_returns_none(self, tmp_path, monkeypatch):
        p = tmp_path / "active.json"
        p.write_text("{nope")
        monkeypatch.setenv("RADIOBAR_ACTIVE_PATH", str(p))
        assert rb.read_active() is None


class TestClickDispatch:
    def _set_active(self, tmp_path, monkeypatch, source, player=None):
        monkeypatch.setenv("RADIOBAR_ACTIVE_PATH",
                           str(tmp_path / "active.json"))
        if source is not None:
            rb.write_active({"source": source, "player": player})

    def test_mpris_active_click_play_pauses_that_player(
            self, tmp_path, monkeypatch):
        self._set_active(tmp_path, monkeypatch, "mpris", "spotify")
        calls = []
        assert rb.cmd_click(run=lambda cmd, **k: calls.append(cmd)) == 0
        assert calls == [["playerctl", "-p", "spotify", "play-pause"]]

    def test_radio_active_click_falls_through_to_toggle(
            self, tmp_path, monkeypatch):
        self._set_active(tmp_path, monkeypatch, "radio")
        toggled = []
        monkeypatch.setattr(rb, "cmd_toggle",
                            lambda run=None: toggled.append(1) or 0)
        assert rb.cmd_click(run=lambda cmd, **k: None) == 0
        assert toggled == [1]

    def test_idle_or_missing_click_falls_through_to_toggle(
            self, tmp_path, monkeypatch):
        self._set_active(tmp_path, monkeypatch, None)
        toggled = []
        monkeypatch.setattr(rb, "cmd_toggle",
                            lambda run=None: toggled.append(1) or 0)
        assert rb.cmd_click(run=lambda cmd, **k: None) == 0
        assert toggled == [1]

    def test_prev_next_only_act_on_mpris(self, tmp_path, monkeypatch):
        self._set_active(tmp_path, monkeypatch, "mpris", "spotify")
        calls = []
        assert rb.cmd_prev(run=lambda cmd, **k: calls.append(cmd)) == 0
        assert rb.cmd_next(run=lambda cmd, **k: calls.append(cmd)) == 0
        assert calls == [["playerctl", "-p", "spotify", "previous"],
                         ["playerctl", "-p", "spotify", "next"]]
        self._set_active(tmp_path, monkeypatch, "radio")
        calls2 = []
        assert rb.cmd_prev(run=lambda cmd, **k: calls2.append(cmd)) == 0
        assert calls2 == []

    def test_missing_playerctl_returns_error(self, tmp_path, monkeypatch):
        self._set_active(tmp_path, monkeypatch, "mpris", "spotify")

        def run(cmd, **k):
            raise FileNotFoundError("playerctl")
        assert rb.cmd_click(run=run) == 1


class TestMainDispatchNewCommands:
    def test_click_prev_next_dispatch(self, monkeypatch):
        for name, fn in (("click", "cmd_click"), ("prev", "cmd_prev"),
                         ("next", "cmd_next")):
            monkeypatch.setattr(rb, fn, lambda run=None: 0)
            assert rb.main([name]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement**

```python
def active_path() -> Path:
    override = os.environ.get("RADIOBAR_ACTIVE_PATH")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return Path(runtime) / "radiobar-active.json"


def write_active(active: dict):
    dest = active_path()
    try:
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps({"source": active.get("source"),
                                   "player": active.get("player")}))
        os.replace(tmp, dest)
    except OSError:
        pass


def read_active():
    try:
        data = json.loads(active_path().read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _mpris_control(action: str, run) -> int:
    active = read_active()
    if not (active and active.get("source") == "mpris"
            and active.get("player")):
        return 0
    try:
        run(["playerctl", "-p", active["player"], action],
            capture_output=True)
    except OSError:
        return 1
    return 0


def cmd_click(run=subprocess.run) -> int:
    active = read_active()
    if active and active.get("source") == "mpris" and active.get("player"):
        return _mpris_control("play-pause", run)
    return cmd_toggle()


def cmd_prev(run=subprocess.run) -> int:
    return _mpris_control("previous", run)


def cmd_next(run=subprocess.run) -> int:
    return _mpris_control("next", run)
```

In `main`, add before the final usage error (and extend `USAGE` to
`"usage: radiobar status|toggle|play <name-or-url>|stop|menu|click|prev|next"`):

```python
    if cmd == "click":
        return cmd_click()
    if cmd == "prev":
        return cmd_prev()
    if cmd == "next":
        return cmd_next()
```

Note: `cmd_click` calls `cmd_toggle()` without arguments — Task 11 gives
`cmd_toggle` a `run=subprocess.run` keyword, so the tests here patch
`rb.cmd_toggle` with a `lambda run=None: ...` to stay compatible.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): active-source file and click/prev/next subcommands"
```

---

### Task 9: NowPlaying render loop

**Files:**
- Modify: `linux/radiobar`
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Consumes: `StateStore` (2), `arbiter`/`IDLE_ACTIVE` (3), `guard_action`
  (4), `Renderer`/`mpris_display_title`/`TICK_SECONDS` (5),
  `ArtworkWorker.track_changed(title, subtitle, art_url)` (6),
  `write_active` (8), `ipc_command`/`emit` (existing).
- Produces: `class NowPlaying` with
  `__init__(store, worker, renderer=None, emit_fn=emit, ipc=ipc_command,
  write_active_fn=write_active)`, `tick()` (one full cycle: guard →
  arbiter → render/emit → on identity change: active file + worker), and
  `run()` (blocking loop: initial tick, then wait on `store.changed` with
  `TICK_SECONDS` timeout while `renderer.needs_tick()`, else no timeout).

- [ ] **Step 1: Write the failing tests**

```python
class _NP:
    """Harness: NowPlaying with everything injected and recorded."""

    def __init__(self):
        self.store = rb.StateStore()
        self.emitted, self.ipc_calls, self.actives = [], [], []
        self.worker_calls = []

        class W:
            def track_changed(w, title, subtitle, art_url=None):
                self.worker_calls.append(("track", title, subtitle, art_url))

            def clear(w):
                self.worker_calls.append(("clear",))

        self.np = rb.NowPlaying(
            self.store, W(),
            renderer=rb.Renderer(choose=lambda colors: colors[0]),
            emit_fn=self.emitted.append,
            ipc=lambda args: self.ipc_calls.append(args) or {"error": "success"},
            write_active_fn=self.actives.append)


class TestNowPlaying:
    def test_idle_tick_emits_idle_and_clears_worker(self):
        h = _NP()
        h.np.tick()
        assert h.emitted[-1]["class"] == "idle"
        assert h.worker_calls == [("clear",)]
        assert h.actives[-1]["source"] == "idle"

    def test_radio_track_kicks_worker_once(self):
        h = _NP()
        h.store.set_radio({"running": True, "paused": False, "icy": "A - B",
                           "media": None, "station": "FIP"})
        h.np.tick()
        h.np.tick()  # same identity → no second worker call
        assert h.worker_calls == [("track", "A - B", "FIP", None)]
        assert h.actives[-1]["source"] == "radio"

    def test_mpris_track_passes_art_url_and_player_subtitle(self):
        h = _NP()
        h.store.update_player("spotify",
                              {"status": "Playing", "artist": "Ar",
                               "title": "Ti", "art_url": "https://a/i"})
        h.np.tick()
        assert h.worker_calls == [("track", "Ar - Ti", "Spotify", "https://a/i")]
        assert h.actives[-1] == {"source": "mpris", "player": "spotify",
                                 "playing": True, "artist": "Ar",
                                 "title": "Ti", "art_url": "https://a/i",
                                 "station": None}

    def test_mpris_without_art_url_passes_empty_string(self):
        h = _NP()
        h.store.update_player("spotify",
                              {"status": "Playing", "artist": "Ar",
                               "title": "Ti", "art_url": None})
        h.np.tick()
        assert h.worker_calls == [("track", "Ar - Ti", "Spotify", "")]

    def test_guard_pauses_radio_when_player_starts(self):
        h = _NP()
        h.store.set_radio({"running": True, "paused": False, "icy": "A - B",
                           "media": None, "station": "FIP"})
        h.np.tick()  # radio showing
        h.store.update_player("spotify",
                              {"status": "Playing", "artist": "Ar",
                               "title": "Ti", "art_url": None})
        h.np.tick()
        assert ["set_property", "pause", True] in h.ipc_calls
        # after the guard, the emitted line is spotify (radio now paused)
        assert "Ar - Ti" in h.emitted[-1]["text"]

    def test_guard_does_not_refire_on_level_state(self):
        h = _NP()
        h.store.set_radio({"running": True, "paused": False, "icy": "A - B",
                           "media": None, "station": "FIP"})
        h.np.tick()
        h.store.update_player("spotify",
                              {"status": "Playing", "artist": "Ar",
                               "title": "Ti", "art_url": None})
        h.np.tick()
        n = h.ipc_calls.count(["set_property", "pause", True])
        h.np.tick()
        h.np.tick()
        assert h.ipc_calls.count(["set_property", "pause", True]) == n

    def test_source_flip_writes_active_file(self):
        h = _NP()
        h.store.update_player("spotify",
                              {"status": "Playing", "artist": None,
                               "title": "Ti", "art_url": None})
        h.np.tick()
        h.store.update_player("spotify", None)
        h.np.tick()
        assert [a["source"] for a in h.actives] == ["mpris", "idle"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestNowPlaying -v`
Expected: FAIL with `AttributeError: ... 'NowPlaying'`

- [ ] **Step 3: Implement**

```python
class NowPlaying:
    """Render loop: guard -> arbiter -> emit; side effects on track change."""

    def __init__(self, store, worker, renderer=None, emit_fn=emit,
                 ipc=ipc_command, write_active_fn=write_active):
        self.store = store
        self.worker = worker
        self.renderer = renderer or Renderer()
        self.emit = emit_fn
        self.ipc = ipc
        self.write_active = write_active_fn
        self.prev_players = {}
        self.last_identity = None

    def tick(self):
        radio, players = self.store.snapshot()
        radio_playing = bool(radio.get("running")) and not radio.get("paused")
        if guard_action(self.prev_players, players, radio_playing):
            self.ipc(["set_property", "pause", True])
            radio = dict(radio)
            radio["paused"] = True  # reflect before mpv's event round-trips
        self.prev_players = players
        active = arbiter(radio, players)
        self.emit(self.renderer.render(active))
        identity = (active["source"], active["player"], active["artist"],
                    active["title"])
        if identity == self.last_identity:
            return
        self.last_identity = identity
        self.write_active(active)
        if active["source"] == "idle":
            self.worker.clear()
        elif active["source"] == "radio":
            self.worker.track_changed(active["title"], active["station"])
        else:
            self.worker.track_changed(mpris_display_title(active),
                                      (active["player"] or "").capitalize(),
                                      active["art_url"] or "")

    def run(self):
        self.tick()
        while True:
            timeout = TICK_SECONDS if self.renderer.needs_tick() else None
            self.store.changed.wait(timeout=timeout)
            self.store.changed.clear()
            self.tick()
```

(`art_url or ""`: empty string routes `fetch_track_art` to the MPRIS path,
which treats it as an immediate cached miss — art cleared, notification
still fires without an icon. `None` would wrongly trigger an iTunes lookup
for an MPRIS track.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): NowPlaying render loop with guard and track-change side effects"
```

---

### Task 10: MprisSource + cmd_status rewiring

**Files:**
- Modify: `linux/radiobar` (`MprisSource`, `radio_watcher`, rewrite
  `cmd_status`, delete `_EmittingStore`)
- Test: `linux/test_radiobar.py`

**Interfaces:**
- Consumes: `StateStore` (2), `parse_playerctl_line`/`PLAYERCTL_FORMAT`
  (1), `watch` (7), `NowPlaying` (9).
- Produces:
  - `PLAYERCTL_CMD = ["playerctl", "--all-players", "--follow", "metadata",
    "--format", PLAYERCTL_FORMAT]`.
  - `class MprisSource` with `__init__(store, popen=subprocess.Popen,
    sleep=time.sleep)` and `run()` — blocking; meant for a daemon thread.
    Missing binary → one stderr warning, returns. EOF → respawn after
    `sleep(2)`.
  - `radio_watcher(store)` — blocking; the old cmd_status connect/retry
    loop feeding `watch(s, store)` and `store.set_radio({"running": False})`
    on disconnect.
  - `cmd_status()` — starts both watchers as daemon threads, runs
    `NowPlaying(store, ArtworkWorker()).run()`.

- [ ] **Step 1: Write the failing tests**

```python
class _FakeProc:
    def __init__(self, lines):
        import io
        self.stdout = io.StringIO("".join(lines))

    def wait(self):
        return 0


class _StopLoop(Exception):
    pass


class TestMprisSource:
    def test_lines_feed_store_then_respawn_then_disabled(self, capsys):
        store = rb.StateStore()
        spawns = []

        def popen(cmd, **kwargs):
            spawns.append(cmd)
            if len(spawns) == 1:
                return _FakeProc(["spotify\tPlaying\tAr\tTi\t\n",
                                  "spotify\tStopped\t\t\t\n"])
            raise FileNotFoundError("playerctl")

        slept = []
        rb.MprisSource(store, popen=popen,
                       sleep=lambda s: slept.append(s)).run()
        assert spawns[0] == rb.PLAYERCTL_CMD
        assert len(spawns) == 2      # EOF → respawn attempt
        assert slept == [2]
        _, players = store.snapshot()
        assert players == {}          # Playing then Stopped → dropped
        assert "playerctl" in capsys.readouterr().err

    def test_oserror_spawn_retries(self):
        store = rb.StateStore()
        attempts = []

        def popen(cmd, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("busy")
            raise _StopLoop()

        def sleep(s):
            pass

        import pytest
        with pytest.raises(_StopLoop):
            rb.MprisSource(store, popen=popen, sleep=sleep).run()
        assert len(attempts) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestMprisSource -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement**

```python
PLAYERCTL_CMD = ["playerctl", "--all-players", "--follow", "metadata",
                 "--format", PLAYERCTL_FORMAT]


class MprisSource:
    """Feeds MPRIS player state into the store from playerctl --follow."""

    def __init__(self, store, popen=subprocess.Popen, sleep=time.sleep):
        self.store = store
        self.popen = popen
        self.sleep = sleep

    def run(self):
        while True:
            try:
                proc = self.popen(PLAYERCTL_CMD, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True)
            except FileNotFoundError:
                print("radiobar: playerctl not found — "
                      "MPRIS sources disabled", file=sys.stderr)
                return
            except OSError:
                self.sleep(2)
                continue
            for line in proc.stdout:
                parsed = parse_playerctl_line(line)
                if parsed is not None:
                    self.store.update_player(*parsed)
            proc.wait()
            self.sleep(2)


def radio_watcher(store):
    """Reconnect loop feeding mpv events into the store."""
    while True:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(str(socket_path()))
        except OSError:
            s.close()
            store.set_radio({"running": False})
            time.sleep(2)
            continue
        try:
            watch(s, store)
        except OSError:
            pass
        finally:
            s.close()
        store.set_radio({"running": False})
        time.sleep(2)


def cmd_status() -> int:
    store = StateStore()
    threading.Thread(target=radio_watcher, args=(store,),
                     daemon=True).start()
    threading.Thread(target=MprisSource(store).run, daemon=True).start()
    NowPlaying(store, ArtworkWorker()).run()
    return 0
```

Delete `_EmittingStore` (Task 7 scaffolding).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Manual smoke test**

With Spotify or a YouTube tab playing:
`RADIOBAR_NO_NOTIFY=1 timeout 5 ./linux/radiobar status | head -5`
Expected: JSON lines showing the MPRIS player with pango markup; with a
long title, multiple lines ~100 ms apart (scroll). With nothing playing:
a single idle line and no further output (event-driven).

- [ ] **Step 6: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): MPRIS watcher thread and unified status engine"
```

---

### Task 11: toggle/play one-audible-source guard

**Files:**
- Modify: `linux/radiobar` (`pause_other_players`, `cmd_toggle`, `cmd_play`)
- Test: `linux/test_radiobar.py` (update `TestToggle`, `TestPlay`)

**Interfaces:**
- Consumes: `ipc_command` (existing).
- Produces:
  - `pause_other_players(run=subprocess.run)` — `playerctl -a pause`,
    swallows `OSError`/missing binary.
  - `cmd_toggle(run=subprocess.run) -> int` — queries
    `["get_property", "pause"]`; resuming (data True) or cold-starting
    pauses other players first; pausing does NOT (with mpv-mpris installed,
    `playerctl -a pause` would pause our mpv and a subsequent cycle would
    wrongly resume it). Uses explicit
    `["set_property", "pause", False/True]` instead of `cycle`.
  - `cmd_play(arg, run=subprocess.run) -> int` — pauses other players
    before quit+launch.

- [ ] **Step 1: Update/extend the tests (fail first)**

Replace `TestToggle` and extend `TestPlay`:

```python
class TestToggle:
    def test_playing_radio_gets_paused_without_touching_others(self, monkeypatch):
        sent, runs = [], []
        monkeypatch.setattr(rb, "ipc_command", lambda args: sent.append(args)
                            or {"error": "success", "data": False})
        assert rb.cmd_toggle(run=lambda cmd, **k: runs.append(cmd)) == 0
        assert sent == [["get_property", "pause"],
                        ["set_property", "pause", True]]
        assert runs == []  # pausing radio must NOT playerctl-pause others

    def test_paused_radio_resume_pauses_others_first(self, monkeypatch):
        sent, runs = [], []
        monkeypatch.setattr(rb, "ipc_command", lambda args: sent.append(args)
                            or {"error": "success", "data": True})
        assert rb.cmd_toggle(run=lambda cmd, **k: runs.append(cmd)) == 0
        assert runs == [["playerctl", "-a", "pause"]]
        assert sent == [["get_property", "pause"],
                        ["set_property", "pause", False]]

    def test_cold_start_pauses_others_and_launches_last(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        rb.write_last("FIP")
        monkeypatch.setattr(rb, "ipc_command", lambda args: None)
        launched, runs = [], []
        monkeypatch.setattr(rb, "launch_mpv", lambda st: launched.append(st))
        assert rb.cmd_toggle(run=lambda cmd, **k: runs.append(cmd)) == 0
        assert runs == [["playerctl", "-a", "pause"]]
        assert launched[0]["name"] == "FIP"

    def test_cold_start_no_history_uses_first_station(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "ipc_command", lambda args: None)
        launched = []
        monkeypatch.setattr(rb, "launch_mpv", lambda st: launched.append(st))
        assert rb.cmd_toggle(run=lambda cmd, **k: None) == 0
        assert launched[0]["name"] == rb.BUILTIN_STATIONS[0]["name"]

    def test_missing_playerctl_does_not_break_toggle(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "ipc_command", lambda args: None)
        launched = []
        monkeypatch.setattr(rb, "launch_mpv", lambda st: launched.append(st))

        def run(cmd, **k):
            raise FileNotFoundError("playerctl")
        assert rb.cmd_toggle(run=run) == 0
        assert launched
```

In `TestPlay`, add `run=lambda cmd, **k: runs.append(cmd)` capture to the
existing tests and assert `["playerctl", "-a", "pause"]` is run before
launch in `test_known_station_by_name`; keep the other cases as-is with a
no-op `run`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestToggle linux/test_radiobar.py::TestPlay -v`
Expected: FAIL (old cycle-pause behavior / TypeError on `run=`).

- [ ] **Step 3: Implement**

```python
def pause_other_players(run=subprocess.run):
    try:
        run(["playerctl", "-a", "pause"], capture_output=True)
    except OSError:
        pass


def cmd_toggle(run=subprocess.run) -> int:
    resp = ipc_command(["get_property", "pause"])
    if resp is not None:
        if resp.get("data") is True:
            pause_other_players(run)
            ipc_command(["set_property", "pause", False])
        else:
            ipc_command(["set_property", "pause", True])
        return 0
    pause_other_players(run)
    stations = load_stations()
    station = None
    last = read_last()
    if last:
        station = find_station(stations, last)
    if station is None:
        station = stations[0]
    launch_mpv(station)
    return 0
```

`cmd_play` gains `run=subprocess.run` and calls `pause_other_players(run)`
immediately before `ipc_command(["quit"])`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): toggle/play pause other players (one-audible-source guard)"
```

---

### Task 12: menu Stop entry

**Files:**
- Modify: `linux/radiobar` (`cmd_menu`, new constant `STOP_ENTRY`)
- Test: `linux/test_radiobar.py` (extend `TestCmdMenu`)

**Interfaces:**
- Consumes: `ipc_command`, `cmd_stop` (existing).
- Produces: `STOP_ENTRY = "■ Stop radio"`; `cmd_menu` prepends it to the
  station list when the mpv socket answers, and selecting it runs
  `cmd_stop()`.

- [ ] **Step 1: Write the failing tests**

Add to `TestCmdMenu` (and patch `rb.ipc_command` to `lambda args: None` in
each *existing* `TestCmdMenu` test so they keep exercising the
radio-stopped menu):

```python
    def test_stop_entry_offered_and_dispatches_when_radio_running(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "ipc_command",
                            lambda args: {"error": "success", "data": False})
        stopped = []
        monkeypatch.setattr(rb, "cmd_stop", lambda: stopped.append(1) or 0)
        monkeypatch.setattr(rb, "find_menu_cmd",
                            lambda which=None: ["walker", "--dmenu"])
        run, calls = self._fake_run(rb.STOP_ENTRY + "\n")
        assert rb.cmd_menu(run=run) == 0
        assert stopped == [1]
        assert calls[0][1]["input"].startswith(rb.STOP_ENTRY + "\n")

    def test_no_stop_entry_when_radio_stopped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RADIOBAR_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(rb, "ipc_command", lambda args: None)
        monkeypatch.setattr(rb, "find_menu_cmd",
                            lambda which=None: ["walker", "--dmenu"])
        run, calls = self._fake_run("")
        assert rb.cmd_menu(run=run) == 0
        assert rb.STOP_ENTRY not in calls[0][1]["input"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest linux/test_radiobar.py::TestCmdMenu -v`
Expected: new tests FAIL with `AttributeError: ... 'STOP_ENTRY'`

- [ ] **Step 3: Implement**

Add `STOP_ENTRY = "■ Stop radio"` near the icon constants. In `cmd_menu`,
replace the names-building and choice-handling lines:

```python
    stations = load_stations()
    names = [s["name"] for s in stations]
    if ipc_command(["get_property", "pause"]) is not None:
        names.insert(0, STOP_ENTRY)
    result = run(menu, input="\n".join(names) + "\n",
                 capture_output=True, text=True)
    choice = result.stdout.strip()
    if not choice:
        return 0
    if choice == STOP_ENTRY:
        return cmd_stop()
```

(the unknown-choice notify path below stays as-is).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/radiobar linux/test_radiobar.py
git commit -m "feat(linux): Stop radio entry in the station menu while radio runs"
```

---

### Task 13: repo snippets + README

**Files:**
- Modify: `linux/waybar-snippet.jsonc`, `linux/README.md`,
  `linux/style-snippet.css` (only if it references removed classes — check)

**Interfaces:**
- Consumes: final subcommand set (`status|toggle|play|stop|menu|click|prev|next`).
- Produces: documentation matching shipped behavior.

- [ ] **Step 1: Update `linux/waybar-snippet.jsonc`**

Change the `custom/radio` block's bindings to:

```jsonc
"custom/radio": {
  "exec": "radiobar status",
  "return-type": "json",
  "on-click": "radiobar click",
  "on-click-middle": "radiobar prev",
  "on-click-right": "radiobar menu",
  "tooltip": true
}
```

(the `image#radioart` block is unchanged).

- [ ] **Step 2: Update `linux/README.md`**

- Requirements: add `playerctl` (`sudo pacman -S playerctl`) and
  "optional: `imagemagick` or `ffmpeg` — downscales Spotify/browser cover
  art for the bar thumbnail; without one, MPRIS art appears only in
  notifications".
- Intro/features: describe the unified slot — radio when playing, otherwise
  any MPRIS player (Spotify, browser, Discord); scrolling colored titles;
  one-audible-source guard ("starting one source pauses the other; the bar
  always shows what you hear"); `■ Stop radio` menu entry.
- Usage table: Left-click = play/pause shown source (starts last station
  when idle); middle-click = previous track (MPRIS); right-click = station
  menu / Stop radio; `radiobar next` available for a hotkey.
- Note the removal instructions for an existing `custom/mpris` module
  ("if you previously ran a separate mpris waybar module, remove it —
  RadioBar now covers it").

- [ ] **Step 3: Check style-snippet.css**

`grep -n "custom-radio\|custom-mpris" linux/style-snippet.css
~/.config/waybar/style.css` — the module still emits classes
`playing|paused|idle` under `#custom-radio`; no changes expected. If the
live style.css styles `#custom-mpris`, note it for Task 14 cleanup.

- [ ] **Step 4: Run full test suite (unchanged code, sanity)**

Run: `python -m pytest linux/test_radiobar.py -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add linux/waybar-snippet.jsonc linux/README.md linux/style-snippet.css
git commit -m "docs(linux): document unified now-playing module"
```

---

### Task 14: live-machine migration + end-to-end verification

**Files:**
- Modify: `~/.config/waybar/config.jsonc` (live user config — load the
  `omarchy` skill BEFORE editing anything under `~/.config/waybar/`)
- Install: `cp linux/radiobar ~/.local/bin/radiobar && chmod +x ~/.local/bin/radiobar`

**Interfaces:**
- Consumes: everything shipped in Tasks 1–13.
- Produces: the running bar uses the unified module.

- [ ] **Step 1: Install the new script**

```bash
cp linux/radiobar ~/.local/bin/radiobar && chmod +x ~/.local/bin/radiobar
```

- [ ] **Step 2: Edit waybar config (via omarchy skill guidance)**

In `~/.config/waybar/config.jsonc`:
- Remove `"custom/mpris"` from `modules-left`.
- Delete the `"custom/mpris"` module block and the unused built-in
  `"mpris"` block.
- Update `"custom/radio"`: `"on-click": "radiobar click"`,
  `"on-click-middle": "radiobar prev"`, keep
  `"on-click-right": "radiobar menu"`.
- Leave `image#radioart` as-is.
- If `~/.config/waybar/style.css` has `#custom-mpris` rules, remove them.

- [ ] **Step 3: Restart waybar**

```bash
omarchy restart waybar
```

- [ ] **Step 4: Manual verification checklist**

1. Idle: dim `󰐹` shows; left-click starts the last station; bar shows
   colored scrolling title once ICY metadata arrives; art thumbnail +
   notification appear.
2. Start Spotify playback while radio plays → radio pauses itself within
   ~a second; bar flips to `` + track; Spotify album art in the
   thumbnail (128 px) and notification.
3. Left-click now pauses Spotify; left-click again resumes it.
4. SUPER+SHIFT+R (radiobar toggle) → Spotify pauses, radio resumes, bar
   flips back.
5. Right-click → menu shows `■ Stop radio` first; selecting it stops mpv,
   art clears, bar shows Spotify (if playing) or idle.
6. Play a YouTube tab with Spotify paused → bar shows the browser player
   (`󰝚` icon, title from the tab).
7. Long title (>30 chars) scrolls with the `•` seam and pauses at the
   start; short titles are static; with nothing playing,
   `pidof radiobar`'s process sits idle (no CPU).
8. `python -m pytest linux/test_radiobar.py -v` — all green.

- [ ] **Step 5: Final commit (if any repo files changed during verification)**

```bash
git status --short   # expect clean; commit any fixes with their own message
```

---

## Self-review notes (already applied)

- Spec coverage: arbiter (T3), guard both directions (T4+T9 status-side,
  T11 command-side), scroll/colors/icons (T5), MPRIS art + 128 px guard
  (T6), notifications-all-sources (T6/T9 — `notify_track` unchanged,
  worker notifies for every source), playerctl backend + respawn +
  graceful absence (T1/T10), active file + click/prev/next (T8), menu Stop
  entry (T12), snippets/README (T13), live migration (T14).
- The `mpris-scroll.py` retirement is config-side only (Task 14) — the
  script file itself is left in place per the spec.
- Type consistency: the active dict (source/player/playing/artist/title/
  art_url/station) is defined once in Task 3 and used verbatim in Tasks
  5, 8, 9. Worker signature `track_changed(title, subtitle, art_url=None)`
  defined in Task 6, consumed in Task 9. Store shapes defined in Task 2,
  consumed everywhere.
